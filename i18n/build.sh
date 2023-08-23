cd $(dirname $0)
GENPY="$(realpath ../../../flutter_bloc_gen/i18n/l18n_gen.py)"
if [ $? -ne 0 ] || [ ! -r "$GENPY" ];then
	echo "Please clone from git@github.com:whowillcare/flutter_bloc_generator.git the repo located as $GENPY"
	exit 1
fi
YAMLFILE=${1:-strings.yaml}
YAML=$(realpath $YAMLFILE)
python $GENPY --yaml $YAML --interface CT --helper clock_in_text_helper
