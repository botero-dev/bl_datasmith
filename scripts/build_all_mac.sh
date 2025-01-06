#!/usr/bin/env bash
# build_all_mac.sh
# Copyright Andrés Botero 2023

echo "build_all_mac.sh"
set -euv

script_file="$0"
script_dir=$(dirname "${BASH_SOURCE[0]}")

base_path="$script_dir/.."
pushd "$base_path" > /dev/null
base_path=$(pwd)
popd > /dev/null


# Cleanup export folder
rm -rf "$base_path/build/mac"
mkdir -p "$base_path/build/mac"


launcher_apps="$HOME/Library/Application Support/Epic/UnrealEngineLauncher/LauncherInstalled.dat"

engine_versions=(
    "UE_4.27"
    "UE_5.4"
    "UE_5.5"
)

# Iterate over the list and call echo with each string
for version in "${engine_versions[@]}"; do
	ue_path=$("$base_path/scripts/get_path_for_ue.py" "$launcher_apps" "$version")
	target_path="$base_path/build/mac/$version"
	"$base_path/scripts/build_single_unix.sh" --target_path "$target_path" --ue_path "$ue_path"
done

pushd build/mac > /dev/null
rm -rf "$base_path/build/mac.zip"
zip -r "$base_path/build/mac.zip" ./*

popd > /dev/null