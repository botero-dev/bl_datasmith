#!/usr/bin/env bash

script_file="$0"
script_dir=$(dirname "${BASH_SOURCE[0]}")

base_path="$script_dir/.."

cd "$base_path"


target_name=""
ue_path=""
is_ue5=""

while [[ $# -gt 0 ]]; do
  case $1 in
    --target_name)
      target_name="$2"
      shift
      ;;
    --ue_path)
      ue_path="$2"
      shift
      ;;
    --is_ue5)
      is_ue5=YES
      ;;
    *)
      echo "Unknown option $1"
      exit 1
      ;;
  esac
  shift
done

if [ -z "$target_name" ]; then
	echo "Usage: $script_file --target_name TARGET_NAME --ue_path UE_PATH [--is_ue5]"
	exit 1
fi

if [ -z "$ue_path" ]; then
	echo "Usage: $script_file --target_name TARGET_NAME --ue_path UE_PATH [--is_ue5]"
	exit 1
fi

echo "running build script with params:"
echo "target_name=$target_name"
echo "ue_path=$ue_path"
echo "is_ue5=$is_ue5"


target_path="$base_path/$target_name"

#mkdir "$target_path/Plugins"

plugin_remote_path="git@github.com:vertexforge/DatasmithBlenderContent.git"

git clone $plugin_remote_path "$target_path/Plugins/DatasmithBlenderContent"


project_path="$target_path/$target_name.uproject"
project_path=$(readlink -f $project_path)
echo "project_path=$project_path"



if [ -z "$is_ue5" ]; then
	# ue4 uses mono to call the build tool
	ubt_path="$ue_path/Engine/Binaries/DotNET/UnrealBuildTool.exe"
	mono "$ubt_path" Development Mac "-Project=$project_path" -TargetType=Editor -Progress -NoEngineChanges -NoHotReloadFromIDE
else
	ubt_path="$ue_path/Engine/Binaries/DotNET/UnrealBuildTool/UnrealBuildTool"
	"$ubt_path" Development Mac "-Project=$project_path" -TargetType=Editor -Progress -NoEngineChanges -NoHotReloadFromIDE
fi


exit 0

# other way, maybe worth research if works for both ue versions:


plugin_path="$target_path/Plugins/DatasmithBlenderContent/DatasmithBlenderContent.uplugin"
plugin_path=$(readlink -f $plugin_path) # get absolute path

# this way uses Unreal Automation Tool instead, which could open other options maybe?
uat_path="/Users/Shared/Epic\ Games/UE_4.27/Engine/Build/BatchFiles/RunUAT.command"
$uat_path BuildPlugin "-plugin=$plugin_path" -package=/Users/abotero/vertexforge/BuiltPlugin

# stupid thing to do in ue4.27 mac:
# change /Users/Shared/Epic Games/UE4.27/Engine/Source/Runtime/Materials/Material.h:1280