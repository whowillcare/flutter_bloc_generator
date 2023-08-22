import json
import os
import re
from os.path import basename
from string import Template

import yaml

ARG_DELI = '_'  # if key has this, means it has argument
MAP_KEY = 'key'  # if value is a hash, we use this variable to define the argument name
DEF_DELI = '@' # if args has this deli, we assuming the first part is the variable type

class JavaTemplate(Template):
    delimiter = '%'


class ShareKeyTemplate(Template):
    delimiter = '$@'


def flatten_json(y):
    out = {}

    def flatten(x, name=''):
        if type(x) is dict:
            for a in x:
                flatten(x[a], name + a)
        else:
            out[name] = x

    flatten(y)
    return out


def get_args(args: list):
    ret = []
    def_type = "String"
    for arg in args:
        parts = arg.split(DEF_DELI)
        tp = def_type
        vn = arg
        pl = len(parts)
        if pl == 2:  # formatted like int@name
            tp = parts[0]
            vn = parts[1]
        ret.append("%s %s" % (tp, vn))
    return ",".join(ret)


def generate_interface(name, args=None):
    if args:
        argname = get_args(args)
        return "String %s(%s)=>'';" % (name, argname)
    else:
        return "String get %s => '';" % name


def generate_override(name, value, args=None):  # value can be a dictionary
    if not args:
        return '@override String get %s => "%s";' % (name, value)
    argname = ""
    extra = ""  # extra content added to template
    isdict = isinstance(value, dict)
    if args:
        argname = get_args(args)
    if isdict:
        map_name = "map"
        extra = 'final %s = {%s};\n' % (map_name, ",\n".join([''' '%s' : "%s" ''' % (k, v)
                                                              for k, v in value.items()]))
        value = "%s[%s] ?? ''" % (map_name, args[0])
    else:
        value = '"%s"' % (repr(value.replace('"', r'\"'))[1:-1])

    return ('''
    @override
    String %s(%s){
       %sreturn %s;
    }
''') % (name, argname, extra, value)


def shift_arg(name, key):
    global ARG_DELI
    deli = ARG_DELI
    return re.sub(r'^([^%s]+)(.*)$' % deli, r'\1%s%s\2' % (deli, key), name)


def main(
        YAMLFILE,
        OUTPUTDIR,
        HELPER_NAME,
        DEFAULT_CLS,
        DEFAULT_OBJ,
        INTERFACE_ONLY,
        ARGS="",
):
    obj = yaml.safe_load(open(YAMLFILE))
    T_SETTINGS = 'settings'  # YAML has settings can override
    settings = obj.get(T_SETTINGS, {})

    l18n = settings.get("l18n", "l18n")  # give user to override in YAML file
    HELPER_NAME = settings.get("helper", HELPER_NAME)
    DEFAULT_CLS = settings.get("default_class", DEFAULT_CLS)
    DEFAULT_OBJ = settings.get("default_object", DEFAULT_OBJ)
    delegate = settings.get("delegate", "TRLocalizationDelegate")

    EXT = ".dart"
    DEFAULT_PKG = HELPER_NAME + EXT

    script_dir, script = os.path.split(__file__)
    yaml_full = os.path.realpath(YAMLFILE)  # get the relative path
    os.chdir(os.path.dirname(yaml_full))
    NOTES = "/// generated content don't modify it manually, modify %s instead\n///Via: %s %s\n" % (
        YAMLFILE, script, ARGS)

    DEFAULT_TEMPLATE = JavaTemplate(NOTES + '''
    part of '%package';
    class %interface {
      %code
      static %interface instance() => %interface();
    }
    ''')
    CLS_TEMPLATE = JavaTemplate(NOTES + '''
    part of '%package';
    
    class %cls extends %interface {
       %code
       static %cls instance() => %cls();
    }
    ''')

    SIMPLEHELPER = NOTES + '''
    import 'dart:io';
    import 'package:flutter/material.dart';
    %extra

    // where the auto generated language implementations
    %parts;
    '''

    HELPER = SIMPLEHELPER + '''
    
    class %cls {
     static const map = {
       // locale to instance map
       %code
     };
    
     // alias map
     static const aliases = %alias;
     // default locale 
     static const defaultLocale = Locale(%defaultLocale);
    
    static Locale? currentLocale;
      static dynamic supportedLocale(Locale locale){
        final sLocal = locale.toString();
        var cls = map[sLocal];
        if (cls == null ){ 
          if (aliases.containsKey(sLocal)){
            cls = map[aliases[sLocal]];
          }else {
            final short = locale.languageCode;
            cls = map[short];
          }
        }
        return cls;
      }
      static %interface get %default_obj  {
        if (currentLocale == null) {
          final PL = Platform.localeName.replaceAll(r'\.*$',"").split('_');
          currentLocale = Locale(PL[0],PL.length > 1 ? PL[1] : null) ;
        }
        final cls = supportedLocale(currentLocale!);
        final found = cls ?? map[defaultLocale.toString()];
        if (found == null){
          throw Exception('Unknown locale $currentLocale specified');
        }
        return found() as %interface;
      }
    }
    %interface %default_obj = %cls.%default_obj;
    
    class %delegate extends LocalizationsDelegate<%interface> {
      const %delegate();
    
      List<Locale> get supportedLocales {
        return %cls.map.keys.map(
            (name) { 
              List<String> code = name.split("_");
              String? cc = code.length > 1 ? code[1] : null;
              return Locale.fromSubtags(languageCode: code[0], countryCode: cc);
            }
        ).toList();
      }
      
      @override
      bool isSupported(Locale locale) => _isSupported(locale);
      @override
      Future<%interface> load(Locale locale) {
        %cls.currentLocale = locale;
       return  Future.value(%cls.%default_obj);
      }
      @override 
      bool shouldReload(TRLocalizationDelegate old) => false;
    
      bool _isSupported(Locale locale) {
        return %cls.supportedLocale(locale) != null;
      }
    } 
    extension LExt on BuildContext {
      %interface get %l18n => %cls.%default_obj;
    }
    
    '''


    sharedPrefix = 'Shared'
    language = obj.get('Languages', None)
    strings = obj.get('Strings', None)
    shared = obj.get(sharedPrefix, None)  # shared keywords
    if not language:
        print("Missing language definition")
        sys.exit(-1)


    T_NAME = 'name'
    T_LOCALE = 'locale'
    T_ALIAS = 'alias'
    T_DEFAULT = 'default'

    result = []
    names = []
    locales = {}  # locales to name map
    aliases = {}
    default_locale = ''
    for value in language:
        result.append({})
        name = value[T_NAME]
        alias = value.get(T_ALIAS, None)
        locale = value.get(T_LOCALE, None)
        default = value.get(T_DEFAULT, None)
        names.append(name)
        if locale:
            locales[name] = locale
            if not default_locale and default:
                default_locale = locale
            if alias:
                if alias is not list:
                    alias = [alias]
                for a in alias:
                    aliases[a] = locale
    if not default_locale:  # default to the first one
        default_locale = locales.get(names[0], '')

    def generate(names, result, alias, locales, default_locale, extra="", interface_only=False):
        code = {

        }
        keys = sorted(result[0].keys())
        for k in keys:
            first, *rest = k.split(ARG_DELI)
            rest = list(filter(lambda a: a, rest))  # filter out all empty string
            code.setdefault(DEFAULT_CLS, []).append(generate_interface(first, rest))
            j = 0
            for name in names:
                code.setdefault(name, []).append(generate_override(first, result[j][k], rest))
                j += 1
        template = {
            DEFAULT_CLS: DEFAULT_TEMPLATE
        }
        for k, v in code.items():
            temp = template.get(k, CLS_TEMPLATE)
            with open(os.path.join(OUTPUTDIR, "%s%s" % (k, EXT)), "w") as f:
                f.write(
                    temp.safe_substitute(dict(
                        package=DEFAULT_PKG,
                        interface=DEFAULT_CLS,
                        code="\n".join(v),
                        cls=k
                    ))
                )
        template_str = HELPER
        if interface_only:
            template_str = SIMPLEHELPER


        with open(os.path.join(OUTPUTDIR, "%s%s" % (HELPER_NAME, EXT)), "w") as f:
            f.write(
                JavaTemplate(template_str).safe_substitute(
                    dict(
                        extra=extra or "",
                        package=DEFAULT_PKG,
                        interface=DEFAULT_CLS,
                        code=",\n".join([
                            '"%s" : %s.instance' % (locales.get(k, k), k) for k in names
                        ]),
                        cls=HELPER_NAME,
                        default_obj=DEFAULT_OBJ,
                        parts=";\n".join(
                            ["part '%s%s'" % (n, EXT) for n in names + [DEFAULT_CLS]]
                        ),
                        # if there are different locale string pointing to same translation. for instance: zh_HK and zh_TW
                        alias=alias,
                        # set the default locale
                        defaultLocale=",".join(["'%s'" % locale for locale in default_locale]),
                        l18n=l18n,
                        delegate=delegate
                    )
                )
            )

    sharedKeys = [{} for i in range(len(language))]

    def convertShared(value, i):
        return ShareKeyTemplate(value).safe_substitute(**sharedKeys[i])

    if shared:
        for sk, sv in shared.items():
            if not isinstance(sv, list):
                sv = [sv] * len(language)
            i = 0
            for v in sv:
                cv = convertShared(v, i)
                sharedKeys[i][sk] = cv
                i += 1

    if strings:

        nl = len(names)
        strings = flatten_json(strings)
        for key, value in strings.items():
            key = re.sub(r'\s', '', key)
            i = 0
            if not isinstance(value, list):  # same value cross different languages
                value = [value] * nl
            if len(value) < nl:
                for j in range(len(value),
                               nl):  # if not enough list, use the first one repetitively
                    value.append(value[0])
            needConversion = False
            new_key = key
            for v in value:
                if isinstance(v, dict):
                    needConversion = True
                    v = json.dumps(v)
                sv = str(v)
                #  sv = ShareKeyTemplate(sv).safe_substitute(**sharedKeys[i])
                try:
                    sv = convertShared(sv, i)
                except IndexError as e:
                    print("For your key: %s has too many values to pack, expected less than %s"
                          % (key, len(language)), file=sys.stderr)
                    raise e
                if needConversion:
                    sv = json.loads(sv)
                    new_key = shift_arg(key, MAP_KEY)
                result[i][new_key] = sv
                i += 1
            if i != nl:
                raise "%s has less value than %d" % (key, nl)
        i = 0
        for keys in sharedKeys:
            result[i].update({"%s%s" % (sharedPrefix, k): v for k, v in keys.items()})
            i += 1
        generate(names, result, aliases, locales, default_locale.split("_"),
                 interface_only=INTERFACE_ONLY,
                 extra=obj.get('extra', ''))


SAMPLE_YAML = '''
Languages:
  - locale: en_US
    name: English
    default: true
  - locale: zh_CN
    name: Chinese
Shared:
  # we put all the shared keywords here, refer it by using $@ prefix, value can be one or an array by languages
  AppName: XSleep
  App: XSleep App
  CompanyName: XSleep Inc.
  CompanyLogo: "https://api.secure.xsleep.com/html/img/cover.png"
  CompanyLogoImgTag: "<img src='$@CompanyLogo' width='100%%' />"
  DiaryNoTitle:
    - No title
    - 无题

Strings:
  ### each string key will be generated as a method, name convention as string name, underscored with its format pattern like string_name_value and its value would look like "string named as %1$s value as %2$s
  HourMeasure:
    - Hours
    - 小时
  MinuteMeasure:
    - Minutes
    - 分钟

  Sleep:
    Set:
      Hours:
        # It's for exception, need to omit the format parameters
        toMuch:
          - "%s %s of sleep might be too much, did you want to make adjustment?"
          - "%s%s的睡眠时间是不是有点夸张了？"
        toLess:
          - "%s %s of sleep might be too less, did you want to make adjustment?"
          - "%s%s的睡眠时间是不是有点不够把？"
    Analysis:
      Color:
        - NotEnough: "#F08080" #lightcoral
          JustRight: "#5d8aa8" # air force blue
          TooMuch: "#FF8C00" # DarkOrange
          Incomplete: "#DC143C" #Crimson
      Desc:
        - NotEnough: You don't seem to have enough sleep!
          JustRight: You must have got a very good dream, mind to share?
          TooMuch: "You seem to have overslept!"
          Incomplete: You might have forgot to end your sleep?
        - NotEnough: 你好象睡得太少了呀！
          JustRight: 你肯定作了个很好的梦，记得和大家分享哦？
          TooMuch: 你可能睡过头了？
          Incomplete: 你可能忘了打卡？
'''
if __name__ == '__main__':
    import sys
    import argparse

    parser = argparse.ArgumentParser(description='Process some integers.')
    parser.add_argument('--yaml', default="strings.yaml",
                        help='Specify a YAML file containing the all string variable info')
    parser.add_argument('--output', default="./",
                        help='Specify where to save generated dart files, it will be a relative path to YAML file.')
    parser.add_argument('--helper', default="S",
                        help='Specify helper class name')
    parser.add_argument('--interface', default="TI",
                        help='Specify interface class name')
    parser.add_argument('--static', default="R",
                        help='Specify the name can be referred from outside world')
    parser.add_argument('-I', '--interface_only', action='store_true', default=False,
                        help='Save to an individual interface class file without generating others')

    parser.add_argument('--example', action='store_true',
                        help='show an example YAML')
    args = parser.parse_args()
    if args.example:
        print(SAMPLE_YAML)
        sys.exit(1)
    used = " ".join(sys.argv[1:])
    if not os.path.exists(args.output):
        os.makedirs(args.output, exist_ok=True)

    main(args.yaml, args.output, args.helper, args.interface, args.static, args.interface_only,
         ARGS=used)
