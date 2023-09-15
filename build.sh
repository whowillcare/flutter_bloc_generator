# This script should be a symbolic link to a submodule dir at under {project root}/generator
# YAML files are supposed to be in the same folder as the symbolic linked shell script
fail(){
  echo -e "$@" >&2
  exit 1
}
if PYTHON=$(which python3);then
  echo "Using $PYTHON"
elif PYTHON=$(which python); then
  V=$($PYTHON -V)
  if [ "$V" = "${V:Python 3}" ];then
    fail "We need python 3, you got $V"
  fi
else
  fail "Couldn't find right python to use"
fi
SOURCEGIT=git@github.com:whowillcare/flutter_bloc_generator.git
PRG=$0
TOOL_DIR=../../../flutter_bloc_gen
LINK=$(readlink $PRG)
if [ -n "$LINK" ];then
  # it's a symbolic link
  TOOL_DIR=$(dirname $LINK)
else
  fail "
You need to run:
git submodule add $SOURCEGIT generator # at your project root
# then make a symbolic link to the build.sh at where the YAML file is assuming it's two level down to the project root
# other wise run this script with ./build.sh [level_to_project_root]
"
fi
cd $(dirname $PRG)
PROJ_ROOT="../.."
PY=${TOOL_DIR}/stategen.py
GENPY="$(realpath $PY)"

if [ $? -ne 0 ] || [ ! -r "$GENPY" ];then
	fail "Please clone from $SOURCEGIT the stategen.py located as $GENPY"
fi
runner() {
  (
      cd $PROJ_ROOT
      dart run build_runner build --delete-conflicting-outputs
  )
}
ROOT_ARG="-R"
build(){
  YAML=$(realpath $1)
  if [ ! -r "$YAML" ];then
    echo "Usage: $0 [ ${ROOT_ARG} project_root ] <YAMLFILE>"
    exit 2
  fi
  where=$(dirname $YAML)
  (
    cd $where
    local MARK="${YAML}.modified"
    local build=1
    if [ -f "$MARK" ];then
      if [ "$YAML" -nt "$MARK" ];then
        echo "You have changed to $YAML"
      else
        echo "$YAML build is still valid"
        build=0
      fi
    fi
    if [ $build -eq 1 ]; then
      $PYTHON $GENPY all $YAML && echo -e "Don't change\n$(date)" > $MARK
    fi
  )
}
if [ "$1" = "${ROOT_ARG}" ];then
  shift
  PROJ_ROOT=$1
  shift
fi
yamls="$@"
if [ -z "$yamls" ]; then
  yamls=$(ls *.yaml)
fi

for yaml in $yamls;do
  build $yaml || fail "Couldn't build $yaml properly"
done
runner
