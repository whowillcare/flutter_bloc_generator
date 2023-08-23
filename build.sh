cd $(dirname $0)
GENPY="$(realpath ../../../flutter_bloc_gen/stategen.py)"
fail(){
  echo -e "$@" >&2
  exit 1
}
if [ $? -ne 0 ] || [ ! -r "$GENPY" ];then
	fail "Please clone from git@github.com:whowillcare/flutter_bloc_generator.git the stategen.py located as $GENPY"
fi
runner() {
  (
      cd ../..
      dart run build_runner build --delete-conflicting-outputs
  )
}
build(){
  YAML=$(realpath $1)
  if [ ! -r "$YAML" ];then
    echo "Usage: $0 <YAMLFILE>"
    exit 2
  fi
  where=$(dirname $YAML)
  cd $where
  python $GENPY all $YAML
}
yamls="$@"
if [ -z "$yamls" ]; then
  yamls=$(ls *.yaml)
fi

for yaml in $yamls;do
  build $yaml || fail "Couldn't build $yaml properly"
done
runner
