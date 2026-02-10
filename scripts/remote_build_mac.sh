#!/usr/bin/env sh
# remote_build_mac.sh
# Copyright 2024 Andrés Botero

echo "remote_build_mac.sh"
set -euv

build_path="tmp/bl_datasmith_build"
branch_name="$1"

rm -rf $build_path
mkdir -p $build_path


echo git clone "git@github.com:botero-dev/bl_datasmith.git" "$build_path"
git clone "git@github.com:botero-dev/bl_datasmith.git" "$build_path"
pushd $build_path

git checkout "$branch_name"

./scripts/build_all_mac.sh

echo "FINISHED"

