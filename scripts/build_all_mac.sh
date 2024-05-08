#!/usr/bin/env bash
# build_all_mac.sh
# Copyright Andrés Botero 2023

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

# 5.0 doesn't build on mac 
engine_versions=(
    "UE_4.27"
    "UE_5.1"
    "UE_5.2"
    "UE_5.3"
    "UE_5.4"
)


pushd "$base_path/build/mac" >> /dev/null

# Iterate over the list and call echo with each string
for version in "${engine_versions[@]}"; do
	ue_path=$("$base_path/scripts/get_path_for_ue.py" "$launcher_apps" "$version")
	target_path="$base_path/build/mac/$version"
	"$base_path/scripts/build_single_mac.sh" --target_path "$target_path" --ue_path "$ue_path"
	zip -r mac.zip "$version/DatasmithBlenderContent/Binaries"
done

mv "$base_path/build/mac/mac.zip" "$base_path/build/mac.zip"

popd > /dev/null