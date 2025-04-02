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


# TODO: Check and optionally patch the UE 4.27 source code
# change UE4.27/Engine/Source/Runtime/Core/Public/Apple/ApplePlatformCompilerPreSetup.h:38
# add:
#pragma clang diagnostic ignored "-Wbitwise-instead-of-logical"
#pragma clang diagnostic ignored "-Wunused-but-set-variable"
#pragma clang diagnostic ignored "-Wdeprecated-builtins"
#pragma clang diagnostic ignored "-Wsingle-bit-bitfield-constant-conversion"

target_path="$target_path/DatasmithBlenderContent"
plugin_path="$base_path/DatasmithBlenderContent"

echo "Running UAT BuildPlugin"

uat_path="$ue_path/Engine/Build/BatchFiles/RunUAT.sh"
platform="Linux"

if [[ $(uname) == "Darwin" ]]; then
  uat_path="$ue_path/Engine/Build/BatchFiles/RunUAT.command"
  platform="Mac"
fi

chmod +x "$uat_path"

"$uat_path" BuildPlugin "-plugin=$plugin_path/DatasmithBlenderContent.uplugin" "-package=$target_path" "-TargetPlatforms=$platform"
