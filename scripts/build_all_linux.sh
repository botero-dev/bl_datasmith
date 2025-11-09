#!/usr/bin/env bash
# build_all_linux.sh
# Copyright Andrés Botero 2024

echo "build_all_linux.sh"
set -euv

script_file="$0"
script_dir=$(dirname "${BASH_SOURCE[0]}")

base_path="$script_dir/.."
pushd "$base_path" > /dev/null
base_path=$(pwd)
popd > /dev/null

# Cleanup export folder
rm -rf "$base_path/build/linux"
mkdir -p "$base_path/build/linux"

engine_versions=(
    "5.4"
    "5.5"
    "5.6"
)

# Iterate over the list and call echo with each string
for version in "${engine_versions[@]}"; do
    echo version $version
    escaped_version=$(echo "$version" | sed 's/\./\\./g')
    echo escaped_version $escaped_version
    search_path="$HOME/Epic Games"
    ue_path=$(ls "$search_path" | grep -E "Unreal_Engine_${escaped_version}\.[0-9]$")
    ue_path="$search_path/$ue_path"
    echo ue_path $ue_path
    target_path="$base_path/build/linux/UE_$version"
    "$base_path/scripts/build_single_unix.sh" --target_path "$target_path" --ue_path "$ue_path"
done

pushd build/linux > /dev/null
rm -rf "$base_path/build/linux.zip"
zip -r "$base_path/build/linux.zip" ./*

popd > /dev/null
