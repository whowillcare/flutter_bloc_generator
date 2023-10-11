force=
if [ $1 = "-f" ];then
  force=1
fi
target=${1:-index.dart}
if [ -r "$target"] && [ $force != "1" ];then
  echo "$target exists, use -f to overwrite"
else
  for dart in *.dart;do if [ $dart != "$target" ];then echo "export '$dart';"; fi; done > "$target"
fi