import argparse
import os
import re
import sys
from string import Template
import yaml

T_ALL = 'all'
T_STATE = 'state'
T_EVENT = 'event'
T_BLOC = 'bloc'
T_DEST = 'dest'
T_PREFIX = 'prefix'  # if YAML has prefix key, add all the classes with this prefix
T_NAME = 'name'
T_PART = 'part'
T_PATH = 'path'
T_CODE = 'code'
T_PARTCODE = T_PART + T_CODE
T_USEREPLAY = 'useReplay'
T_EQUATABLE = 'Equatable'
T_EQUAL = 'equal'
T_PARENT = 'parent'

class Vars:
    comm = r'(//.*$)'
    # clasname has all class name including optional ?,
    # name as the variable name,
    # value as the default value if applicable
    pattern = r'^(?:(?P<clsname>(?P<cls>[\w<,>]+)(?P<optional>\??))\s+)(?P<name>\w+)(?P<value>.*)?$'
    lesser = r'(?P<name>\w+)(?P<value>=.*)?$'
    # if user has specified JsonKey in comments or not
    json_key_pattern = r'\(jk@\s*(?P<JsonKey>.*?)\)'

    def __init__(self, arg):
        self.origin = arg
        match = re.match(self.pattern, arg)
        self.args = {'clsname': 'String'}  # default to string
        if match:
            self.args = match.groupdict()
        else:
            short = re.match(self.lesser, arg)
            if short:
                self.args.update(short.groupdict())
        if self.args.get('value', None) is None:
            self.args['value'] = ''
        value = self.args['value']
        comment = re.findall(self.comm, value)
        if comment:
            self.comment = comment[0]
            self.args['value'] = re.sub(self.comm, '', value)
            jk = re.findall(self.json_key_pattern, self.comment)
            if jk:
                self.comment = re.sub(self.json_key_pattern, '', self.comment)
                self.args['JsonKey'] = jk[0]
        else:
            self.comment = ''
        for name in "clsname cls optional name value JsonKey".split():
            value = self.args.get(name, '')
            setattr(self, name, value or '')


class DartTemplate(Template):
    delimiter = '%'


def error(*msg):
    print(*msg, file=sys.stderr)
    sys.exit(-1)


def state_gen(args, data=None):
    fields = shared_fields({
        T_EQUAL: True,
        T_PARENT: '',
        'init': False,
        'name': None,
        'jsonConverter': '',
        'props': [],
        'exclude': None,  # can exclude certain props that matches this pattern
        'include': '^.*$',  # default include all props
        'useJson' : True
    }
    )
    sync_data(args, fields, data)

    if not args.name:
        error("Missing class name")

    if not args.props:
        error("We need some properties")

    parent = args.parent
    parent_class = T_EQUATABLE if args.equal else ''
    vars = []
    for v in args.props:
        vars.append(Vars(v))

    final = []
    const = []
    fact = 'factory %clsname.fromJson(Map<String,dynamic> json)=>_$%clsnameFromJson(json);\n  Map<String, dynamic> toJson() => _$%clsnameToJson(this);\n'.replace(
        '%clsname', args.name) if args.useJson else ''
    copyWithArgs = []
    copyWithBody = []
    props = []
    init = '%clsname init() {\n   return %clsname();\n  }'.replace('%clsname',
                                                                   args.name) if args.init else ''
    for v in vars:
        final.append('%s%s\n  final %s %s' % (
            v.comment,
            "\n  @JsonKey(name: '%s')" % v.JsonKey if v.JsonKey else '',
            v.clsname, v.name)
                     )
        const.append(
            '%s this.%s%s' % (
                '' if (v.value and v.value.strip()) or v.optional else 'required', v.name, v.value))
        copyWithArgs.append('%s? %s' % (v.cls, v.name))
        copyWithBody.append(DartTemplate('%name: %name ?? this.%name').safe_substitute(name=v.name))
        if args.equal:
            to_append = v.name
            if args.include and not re.match(args.include, to_append): continue
            if args.exclude and re.match(args.exclude, to_append): continue
            props.append(to_append)

    if parent:  # parent class specified, and should be a reachable relative path
        parent_content = load_content(parent)
        if parent_content:
            result = get_class(parent_content, True)
            if result:
                parent_class = result
                args.equal = True
                # properties defined in parent_class
                keys_pattern = r'final\s+(\S*?)(\?){0,1}\s+(\S+);'
                result = re.findall(keys_pattern, parent_content)
                if result:
                    for (key_type, optional, key) in result:
                        const.append('%ssuper.%s' %
                                     ('' if optional else 'required ', key))
                        copyWithArgs.append('%s? %s' % (key_type, key))
                        copyWithBody.append(DartTemplate('%name: %name ?? this.%name').safe_substitute(name=key))
                    props.append('...super.props')

        else:
            error("%s specified but not existent or no content" % parent)
    ext = 'extends %s' % parent_class if parent_class else ''
    ret = DartTemplate("""
%part
%serial
%converter
class %clsname %ext {
  %final;

  const %clsname({%const});

  %init

  %clsname copyWith({%copyWithArgs}){
    return %clsname(
      %copyWithBody
    );
  }

  %fact

  %props

}
""").safe_substitute(
        serial='@JsonSerializable(explicitToJson: true)' if args.useJson else '',
        clsname=args.name,
        final=';\n  '.join(final),
        const=', '.join(const),
        copyWithArgs=', '.join(copyWithArgs),
        copyWithBody=',\n      '.join(copyWithBody),
        props='@override\n  List<Object?> get props => [\n    %s\n];\n' % (
            ',\n    '.join(props)) if args.equal else '',
        ext=ext,
        fact=fact,
        part="part of '%s';\n" % args.part if args.part else '',
        init=init,
        converter='@%s()' % args.jsonConverter if args.jsonConverter else ''
    )
    if args.dest:
        write_content(args.dest, ret, args.overwrite)
    return ret


def write_content(dest, ret, overwrite=True):
    if dest:
        if overwrite or not os.path.exists(dest):
            dirname = os.path.realpath(os.path.dirname(dest))
            if not dirname:
                yes = input("You didn't specify a right directory name, are you sure? (Y/N)")
                if yes.lower()[0] != 'y':
                    error("%s needs to have a directory path" % dest)
                else:
                    print("Continue anyway!")
            if dirname and not os.path.exists(dirname):
                os.makedirs(dirname)
            with open(dest, 'w') as f:
                f.write(ret)


def sync_data(args, fields, data):
    if data is None:
        data = {}
    for field, value in fields.items():
        if not getattr(args, field, None):
            setattr(args, field, data.get(field, value))
    if args.dest and args.dest.startswith('.'):  # assuming it's partial file name
        if args.part:  # we will be using the args.part to generate the dest name
            part, _ = os.path.splitext(args.part)
            args.dest = os.path.basename(part) + args.dest
    if hasattr(args, 'path') and args.dest:
        args.dest = os.path.realpath(os.path.join(args.path, args.dest))


def shared_parser(parser):
    parser.add_argument('-C', '--name', required=False,
                        help="Specify the class name")
    parser.add_argument('-P', '--path', required=False,
                        help="Specify the path to the dest file")
    parser.add_argument('--part', help='Belong to which file, add part of')
    parser.add_argument('--dest', help='Where to write the content')
    parser.add_argument('-O', '--overwrite',
                        help='Overwrite existing file', action='store_true')


def shared_fields(more: dict):
    return {
        'name': 'Demo',
        'path': '',
        'dest': None,
        'part': "",
        'overwrite': True,
        **more
    }


def state_parser(parser):
    parser.add_argument('-I', '--init', action='store_true',
                        help="Specify if init method is needed")
    parser.add_argument('-J', '--jsonConverter',
                        help="Specify special Object converter")
    parser.add_argument('-p', '--props', nargs='+', required=False,
                        help='Specify all possible props, delimited by ')
    parser.add_argument('-E', '--%s' % T_EQUAL,
                        help='Extends from equatable', action='store_true')
    parser.add_argument('--%s' % T_PARENT,
                        help="Add extends from parent class other than Equatable",
                        required=False)
    parser.add_argument('--useJson',action='store_true',
                         help='Use Json Serialization or not'
                         )
    shared_parser(parser)


def bloc_parser(parser):
    parser.add_argument('-E', '--event_file', help="Where the Bloc Event file is located"
                        , required=True)
    parser.add_argument('-S', '--state_file', help="Where the state file is"
                        , required=True)
    parser.add_argument('-R', '--repo_file', help="Where the repository class is"
                        , required=False)
    parser.add_argument('-U', '--useHydrate', action='store_true',
                        help="Specify if to use hydrate mixins or not")
    parser.add_argument('-u', '--useReplay', action='store_false',
                        help="Specify if to use replay or not")

    shared_parser(parser)


def event_parser(parser):
    parser.add_argument('-E', '--events', nargs='+', required=False, help="All the events names")
    parser.add_argument('-u', '--useReplay', action='store_false',
                        help="Specify if to use replay or not")
    shared_parser(parser)


def load_content(name):
    ret = None
    if name and os.path.exists(name):
        with open(name) as f:
            ret = f.read()
    return ret


def get_class(content, first=True):
    if not content:
        return
    result = re.findall(r'class\s+(\w+)\s*(?:extends .*?)*\s*{', content)
    if result and first:
        return result[0]
    return result


def bloc_gen(args, data=None):
    global EVENT_SHORTCUT
    fields = shared_fields(
        {
            'name': 'BaseBloc',
            'useHydrate': True,
            'state_file': None,  # need to have one
            'event_file': None,
            'repo_file': None,
            T_USEREPLAY: False,  # allow using replay mixins
        }
    )
    sync_data(args, fields, data)
    if not args.state_file:
        error("Missing state file")

    if not args.event_file:
        error("Missing event file")

    event_file = args.event_file
    state_file = args.state_file
    repo_file = args.repo_file
    dest_file = args.dest
    bloc_class = args.name
    replay_mixins = ' with ReplayBlocMixin' if args.useReplay else ''

    def event_handlers(event_name, state):
        global EVENT_SHORTCUT
        comma = ", "
        func = '_on%s' % event_name
        _short = ""
        _args = EVENT_SHORTCUT.get(event_name, None)
        if _args:
            _name, _rest = _args
            _argdef = ""
            _arg = ""
            if len(_rest) == 2 and _rest[0]:
                _argdef = comma.join(_rest[0])
                _arg = comma.join(_rest[1])
            _short = DartTemplate('''
    void %name(%argdef){
      add(%event(%arg));
    }''').safe_substitute(
                name=_name,
                argdef='{%s}' % _argdef if _argdef else '',
                arg=_arg
            )

        return [
            DartTemplate(s).safe_substitute(
                event=event_name,
                state=state,
                func=func
            )
            for s in [
                'on<%event>(%func)',
                '   Future<void> %func(%event event, Emitter<%state> emit) '
                'async {\n   //TODO add your code here\n   }\n',
                _short
            ]
        ]

    state_content = load_content(state_file)
    event_content = load_content(event_file)
    repo_content = load_content(repo_file)
    if repo_file and not repo_content:
        error("%s doesn't seem to exist" % repo_file)
    exist_content = load_content(dest_file)

    bloc_template = DartTemplate('''
%part
class %bloc_class extends %{mixins}Bloc<%event_class, %state_class>%replay_mixins{
   %repo
   %constructor
   %hydrate
   %shortcut
%event_handler
}
''')

    shortcut_mark = "/// shortcut functions"
    shortcut_mark_end = "/// end shortcut"

    def add_mark(content):
        return "%s\n%s\n   %s\n" % (shortcut_mark, content, shortcut_mark_end)

    if not event_content:
        error("Wrong content from %s" % event_file)
    event_base, *event_classes = get_class(event_content, False)
    repo_class = ""
    if repo_content:
        repo_class = get_class(repo_content)
        if not repo_class:
            error("%s is not a valid dart class file?!" % repo_file)
    state_class = get_class(state_content)
    if not state_class:
        error("Missing right content from %s" % state_file)
    ret = ""

    def get_handler_func(events):
        event_funcs = []
        event_handler = []
        event_short = []
        for event in events:
            handler, func, short = event_handlers(event, state_class)
            event_funcs.append(func)
            event_handler.append(handler)
            if short:
                event_short.append(short)
        return [
            "\n".join(event_funcs + [""]),
            ";\n      ".join(event_handler + [""]),
            "\n".join(event_short + [""]),

        ]

    if exist_content:  # brand new
        construct_handler_pattern = r'on<(\w+)>\(_on\w+\)'
        exist_events = re.findall(construct_handler_pattern, exist_content)
        event_handler_pattern = r' _on(\w+)\('
        exist_event_funcs = re.findall(event_handler_pattern, exist_content)
        if exist_events and exist_event_funcs:
            def search(a):
                return a not in exist_events

            ret = exist_content
            missed_events = list(filter(search, event_classes))
            if missed_events:
                event_funcs_str, event_handler_str, short_str = get_handler_func(missed_events)

                if event_handler_str:
                    ret = re.sub(
                        r'(super.*?{)',
                        r'\1\n      %s' % event_handler_str.strip(),
                        exist_content
                    )
                if event_funcs_str:
                    ret = re.sub(
                        r'(}\s*)$',
                        r'%s\1' % event_funcs_str,
                        ret
                    )
                if short_str:
                    hasmark = ret.find(shortcut_mark) > 0
                    shortpatter = r'(super.*?\{[^}]+\}([\s\S]*toJson\(\);)?)' if not hasmark else r'(%s\n)' % (
                        shortcut_mark)
                    ret = re.sub(
                        shortpatter,
                        r'\1\n\n    %s' % (add_mark(short_str) if not hasmark else short_str),
                        ret
                    )

    if not ret:
        repo_var = ""
        repo_def = ""
        if repo_class:
            repo_var = repo_class[0].lower() + repo_class[1:]
            repo_def = '%s %s;' % (repo_class, repo_var)
            repo_var = '{required this.%s}' % repo_var
        event_funcs_str, event_handler_str, shortcut = get_handler_func(event_classes)
        if shortcut:
            shortcut = add_mark(shortcut)
        constructor = DartTemplate('''
    %bloc_class(%repo_var) : super(const %state_class()) {
      %event_handlers
    }
''').safe_substitute(
            bloc_class=bloc_class,
            state_class=state_class,
            event_handlers=event_handler_str,
            repo_var=repo_var
        )
        ret = bloc_template.safe_substitute(
            bloc_class=bloc_class,
            state_class=state_class,
            constructor=constructor,
            event_class=event_base,
            shortcut=shortcut,
            repo=repo_def,
            event_handler=event_funcs_str,
            part="part of '%s';\n" % args.part if args.part else '',
            # mixins=" with HydratedMixin" if args.useHydrate else "",
            mixins="Hydrated" if args.useHydrate else "",
            replay_mixins=replay_mixins,
            hydrate=DartTemplate("""
   @override
   %state_class? fromJson(Map<String, dynamic> json)=>%state_class.fromJson(json);

   @override
   Map<String, dynamic>? toJson(%state_class state)=>state.toJson();
""").safe_substitute(
                state_class=state_class
            ) if args.useHydrate else "",
        )
    write_content(args.dest, ret, args.overwrite)
    return ret


EVENT_SHORTCUT = {}


def event_gen(args, data=None):
    global EVENT_SHORTCUT  # store event shortcut -> [eventname, arguments]
    fields = shared_fields({
        'name': 'BaseEvent',
        T_USEREPLAY: False,  # allow using replay mixins
        'events': [],
    }
    )

    sync_data(args, fields, data)
    vs = {}
    events = args.events
    DELI = '#'
    eventname = ''
    replay_event = ' implements ReplayEvent' if args.useReplay else ''

    def convert_to_var(inp):
        return Vars(inp)

    if isinstance(events, dict):  # from YAML file
        for k, vv in events.items():
            if not vv:
                vs[k] = []
            else:
                for v in vv:
                    vs.setdefault(k, []).append(convert_to_var(v))
    else:
        for v in args.events:
            parts = v.split(DELI)
            if len(parts) == 2:  # it contains event name
                eventname = parts[0]
                v = parts[1]
            vs.setdefault(eventname, []).append(convert_to_var(v))

    basename = args.name
    ret = "sealed class %s%s {}\n\n" % (basename, replay_event)
    event_template = '''class %event_name extends %base_name {
    %extra
}    
'''

    for en, eps in vs.items():
        extra = ""
        final = []
        const = []
        shortcut = ""
        if en.find('~') > 1:  # has shortcut name
            pattern = r'^(.+)~(.*)$'
            result = re.findall(pattern, en)
            if result:
                en = result[0][0]
                shortcut = result[0][1]
        if en.startswith("."):  # append to basename
            en = basename + en[1:]
        elif en.startswith("%"):  # prepend to basename
            en = en[1:] + basename
        sargs = None
        if shortcut:
            sargs = [[], []]  # first is the argdef, second is arg
            EVENT_SHORTCUT[en] = [shortcut, sargs]
        if len(eps) > 0:  # extra arguments needed
            for v in eps:
                if shortcut:
                    sargs[0].append('%s%s %s%s' % (
                        '' if (v.value and v.value.strip()) or v.optional else 'required ',
                        v.clsname, v.name, v.value
                    ))
                    sargs[1].append('%s: %s' % (v.name, v.name))
                final.append('%s\n  final %s %s' % (v.comment, v.clsname, v.name))
                const.append(
                    '%s this.%s%s' % (
                        '' if (v.value and v.value.strip()) or v.optional else 'required', v.name,
                        v.value))
            extra = DartTemplate('''
  %final;
  %clsname({%const});
''').safe_substitute(
                clsname=en,
                final=';\n  '.join(final),
                const=', '.join(const),
            )
        kargs = {
            "base_name": basename,
            "event_name": en,
            "extra": extra,
        }
        ret += DartTemplate(event_template).safe_substitute(**kargs)
    if args.part:
        ret = '%s\n%s' % ("part of '%s';" % args.part, ret)
    write_content(args.dest, ret, args.overwrite)
    return ret


def get_code(data, fullname):
    def rel(where):
        return os.path.relpath(where, os.path.dirname(fullname))

    code = data.get(T_CODE, '')
    partcode = data.get(T_PARTCODE, '')
    if not code and partcode:  # code is empty, part code is not
        name = os.path.basename(fullname)
        part, _ = os.path.splitext(name)
        partfile = '%s.c.dart' % part
        code = "part '%s';" % partfile
        partwhere = os.path.join(os.path.dirname(fullname), partfile)
        if not os.path.exists(partwhere):
            write_content(partwhere, "part of '%s.dart';" % part)
    return code


def all_gen(args, data=None):
    if not data:
        data = {}
    processors = [T_STATE, T_EVENT, T_BLOC]
    PART = T_PART
    PATH = T_PATH
    IMPORT = 'import'
    prefix = data.get(T_PREFIX, '')
    part = data.get(PART, '')
    if not part:
        error("%s is mandatory argument in your YAML file" % PART)

    def get_fullname(dest, mypart=part):
        return os.path.realpath(os.path.join(os.path.dirname(dest), mypart))

    def get_rel(where, full_name):
        return os.path.relpath(where, os.path.dirname(full_name))

    path = data.get(PATH, '')
    importcode = data.get(IMPORT, '')
    prepare = {}
    result = {}
    state_only = data.get('stateOnly', None)
    event_only = data.get('eventOnly', None)
    if event_only:
        processors = [T_EVENT]
    use_replay = data.get(T_BLOC, {}).get(T_USEREPLAY, False)
    if use_replay:
        sub = data[T_EVENT] or {}
        sub[T_USEREPLAY] = use_replay
    state_data = data.get(T_STATE, {})
    need_part = state_data.get('useJson', None) or data.get(T_BLOC,{}).get('useHydrate', None)
    if state_data:
     if T_PARENT in state_data:  # has parent
        parent_file = state_data.get(T_PARENT, '')
        dest = state_data.get(T_DEST, data.get(T_BLOC, {}).get(T_DEST, ''))
        fullname = get_fullname(path + os.path.sep, dest)
        real_file = get_fullname(fullname, parent_file)
        if os.path.exists(real_file):
            state_data[T_PARENT] = real_file
        else:
            error("%s specified, but %s's content is not there"%(T_PARENT, parent_file))
        importcode = "import '%s';\n%s" % (parent_file, importcode)
     equal = True  # default to use equal
     if T_EQUAL in state_data:  # use equal
        equal = state_data.get(T_EQUAL, None)
     if equal:
        importcode = "import '%s';\n%s" % ('package:equatable/equatable.dart', importcode)
    for processor in processors:
        subdata = data.get(processor, {})
        if not subdata:
            if state_only:
                break
            else:
                error("Missing %s info" % processor)
        subdata[PATH] = subdata.get(PATH, path)
        subdata[PART] = subdata.get(PART, part)
        if prefix:
            subdata[T_NAME] = '%s%s' % (prefix, subdata.get(T_NAME, processor.title()))
        func = globals()["%s_gen" % processor]
        if not func:
            error("Something went wrong, no such processor: %s" % processor)

        namespace = argparse.Namespace()
        prepare[processor] = namespace
        if processor == T_BLOC:
            state_file = 'state_file'
            event_file = 'event_file'
            subdata[state_file] = subdata.get(state_file, getattr(prepare[T_STATE], T_DEST, None))
            subdata[event_file] = subdata.get(event_file, getattr(prepare[T_EVENT], T_DEST, None))
        result[processor] = func(namespace, subdata)

    if state_only or event_only:
        KEY = T_STATE if state_only else T_EVENT
        ret = result[KEY]
        args = prepare[KEY]
        if part:
            fullname = get_fullname(args.dest)

            def rel(where):
                return get_rel(where, fullname)

            if not os.path.exists(fullname):
                name = os.path.basename(fullname)
                part, _ = os.path.splitext(name)
                part_g = "part '%s.g.dart';" % part if need_part else ''
                code = get_code(data, fullname)
                statename = rel(getattr(prepare[KEY], T_DEST))
                template = '''
%extra_import

import 'package:json_annotation/json_annotation.dart';


%part_g
part '%state';

%code
''' if state_only else '''
%extra_import
part '%state';

%code
'''
                write_content(fullname, DartTemplate(template).safe_substitute(
                    extra_import=importcode,
                    part_g=part_g,
                    part=part,
                    state=statename,
                    code=code,
                )
            )
        return ret
    args = prepare[T_BLOC]
    ret = result[T_BLOC]
    if args.part:  # it's part of a state file
        fullname = get_fullname(args.dest, args.part)

        def rel(where):
            return get_rel(where, fullname)

        blocname = rel(args.dest)
        statename = rel(getattr(prepare[T_STATE], T_DEST))
        eventname = rel(getattr(prepare[T_EVENT], T_DEST))
        repo_file = getattr(prepare[T_BLOC], 'repo_file', '')
        if not os.path.exists(fullname):
            print("%s is not there, we will create it" % fullname)
            name = os.path.basename(fullname)
            part, _ = os.path.splitext(name)
            part_g = "part '%s.g.dart';" % part if need_part else ''
            code = get_code(data, fullname)
            bloc_import = 'hydrated_bloc/hydrated_bloc.dart' if getattr(prepare[T_BLOC],
                                                                        'useHydrate', True) \
                else 'bloc/bloc.dart'
            if getattr(prepare[T_BLOC], T_USEREPLAY, True):
                importcode += "\nimport 'package:replay_bloc/replay_bloc.dart';"
            write_content(fullname, DartTemplate('''
%extra_import

import 'package:%bloc_import';
import 'package:equatable/equatable.dart';
import 'package:json_annotation/json_annotation.dart';

%repo_file

%part_g
part '%state';
part '%event';
part '%bloc';

%code
''').safe_substitute(
                extra_import=importcode,
                repo_file="import '%s';" % rel(repo_file) if repo_file else "",
                part_g=part_g,
                part=part,
                state=statename,
                event=eventname,
                bloc=blocname,
                code=code,
                bloc_import=bloc_import
            )
                          )
    return ret


def main():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(title='subcommands',
                                       dest='subcommand',
                                       description='valid subcommands',
                                       help='List of additional subcommands')
    All = subparsers.add_parser(T_ALL)
    All.set_defaults(func=all_gen)
    state = subparsers.add_parser(T_STATE)
    state_parser(state)
    state.set_defaults(func=state_gen)
    bloc = subparsers.add_parser(T_BLOC)
    bloc_parser(bloc)
    bloc.set_defaults(func=bloc_gen)
    event = subparsers.add_parser(T_EVENT)
    event_parser(event)
    event.set_defaults(func=event_gen)
    parser.add_argument('YAML', help='YAML configuration file')
    args = parser.parse_args()
    data = {}
    if args.YAML and os.path.exists(args.YAML):
        with open(args.YAML, 'r') as f:
            data = yaml.safe_load(f)
        if (T_BLOC not in data) and (T_STATE not in data): # it's a event only
            data['eventOnly'] = True
    return args.func(args, data=data.get(args.subcommand, data))


if __name__ == '__main__':
    print(main())
    print(EVENT_SHORTCUT)
