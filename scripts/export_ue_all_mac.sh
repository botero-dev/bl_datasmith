#!/usr/bin/env bash

script_file="$0"
script_dir=$(dirname "${BASH_SOURCE[0]}")

base_path="$script_dir/.."

pushd "$base_path"

# first do build
scripts/build_all_mac.sh

rm -rf "export"

target_name=ue427_template
ue_version=4.27

plugin_path="export/$ue_version/DatasmithBlenderContent"
mkdir -p "$plugin_path"
cp -r "$target_name/Plugins/DatasmithBlenderContent/Binaries" "$plugin_path"

target_name=ue51_template
ue_version=5.1

plugin_path="export/$ue_version/DatasmithBlenderContent"
mkdir -p "$plugin_path"
cp -r "$target_name/Plugins/DatasmithBlenderContent/Binaries" "$plugin_path"


popd
