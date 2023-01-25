

# we don't do this because mac now uses zsh
#$script_path="$BASH_SOURCE[0]/.."

script_path="$(dirname "$0")"

echo $script_path

base_path="$script_path/.."

cd "$base_path"

# TODO: receive unreal path as argument
# maybe like it is done here: https://rowannicholls.github.io/bash/intro/passing_arguments.html


target_name="ue51_template"
target_name="ue427_template"
ue_path="/Users/Shared/Epic Games/UE_5.1"
ue_path="/Users/Shared/Epic Games/UE_4.27"



target_path="$base_path/$target_name"

#mkdir "$target_path/Plugins"

plugin_remote_path="git@github.com:vertexforge/DatasmithBlenderContent.git"

git clone $plugin_remote_path "$target_path/Plugins/DatasmithBlenderContent"


ubt_path="$ue_path/Engine/Binaries/DotNET/UnrealBuildTool/UnrealBuildTool"
ubt_path="$ue_path/Engine/Binaries/DotNET/UnrealBuildTool.exe"

project_path="$target_path/$target_name.uproject"
project_path=$(readlink -f $project_path)
echo $project_path

echo mono "$ubt_path" Development Mac "-Project=$project_path" -TargetType=Editor -Progress -NoEngineChanges -NoHotReloadFromIDE

mono "$ubt_path" Development Mac "-Project=$project_path" -TargetType=Editor -Progress -NoEngineChanges -NoHotReloadFromIDE

exit 0

# other way:


plugin_path="$target_path/Plugins/DatasmithBlenderContent/DatasmithBlenderContent.uplugin"
plugin_path=$(readlink -f $plugin_path)

uat_path="/Users/Shared/Epic\ Games/UE_4.27/Engine/Build/BatchFiles/RunUAT.command"
$uat_path BuildPlugin "-plugin=$plugin_path" -package=/Users/abotero/vertexforge/BuiltPlugin

# stupid thing to do in ue4.27 mac:
# change /Users/Shared/Epic Games/UE4.27/Engine/Source/Runtime/Materials/Material.h:1280