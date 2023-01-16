
$base_path = "$PSScriptRoot/.."

Push-Location $base_path

$target_name = "ue427_template"

$target_path = "$base_path/$target_name"

mkdir "$target_path/Plugins"

$plugin_remote_path = "git@github.com:vertexforge/DatasmithBlenderContent.git"

git clone $plugin_remote_path "$target_path/Plugins/DatasmithBlenderContent"



$ue_path = "C:/Epic Games/UE_4.27"
$ubt_path = "$ue_path/Engine/Binaries/DotNET/UnrealBuildTool.exe"
$project_path = "$target_path/$target_name.uproject"


& $ubt_path Development Win64 "-Project=$project_path" -TargetType=Editor -Progress -NoEngineChanges -NoHotReloadFromIDE



Pop-Location