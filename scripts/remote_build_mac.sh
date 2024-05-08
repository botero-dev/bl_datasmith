# remote_build_mac.sh
# Copyright 2024 Andrés Botero

build_path="tmp/vertexforge_build"

rm -rf $build_path
mkdir -p $build_path

git clone git@github.com:vertexforge/vertexforge.git $build_path
pushd $build_path

./scripts/build_all_mac.sh

echo "FINISHED"

