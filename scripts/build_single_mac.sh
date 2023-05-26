#!/usr/bin/env bash

script_file="$0"
script_dir=$(dirname "${BASH_SOURCE[0]}")

base_path="$script_dir/.."

pushd "$base_path" > /dev/null
base_path=$(pwd)
popd > /dev/null

target_path=""
ue_path=""

while [[ $# -gt 0 ]]; do
  case $1 in
    --target_path)
      target_path="$2"
      shift
      ;;
    --ue_path)
      ue_path="$2"
      shift
      ;;
    *)
      echo "Unknown option $1"
      exit 1
      ;;
  esac
  shift
done

if [ -z "$target_path" ]; then
	echo "Usage: $script_file --target_path TARGET_PATH --ue_path UE_PATH"
	exit 1
fi

if [ -z "$ue_path" ]; then
	echo "Usage: $script_file --target_path TARGET_PATH --ue_path UE_PATH"
	exit 1
fi


target_path="$target_path/DatasmithBlenderContent"


echo "Cloning UE plugin repo"
# TODO: maybe don't clone the repo and get the path as argument instead
plugin_remote_path="git@github.com:vertexforge/DatasmithBlenderContent.git"
plugin_path="$base_path/DatasmithBlenderContent"
git clone $plugin_remote_path "$plugin_path"


echo "Running UAT BuildPlugin"

uat_path="$ue_path/Engine/Build/BatchFiles/RunUAT.command"

"$uat_path" BuildPlugin "-plugin=$plugin_path/DatasmithBlenderContent.uplugin" "-package=$target_path"

# stupid thing to do in ue4.27 mac:
# change UE4.27/Engine/Source/Runtime/Core/Public/Apple/ApplePlatformCompilerPreSetup.h:38
# add:
#pragma clang diagnostic ignored "-Wunused-but-set-variable"
