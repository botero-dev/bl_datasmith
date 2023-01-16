
$base_path = "$PSScriptRoot/.."

Push-Location $base_path

$target_name = "ue427_template"

$target_path = "$base_path/$target_name"
mkdir "$target_path/Plugins"

$plugin_remote_path = "git@github.com:vertexforge/DatasmithBlenderContent.git"

git clone $plugin_remote_path "$target_path/Plugins/DatasmithBlenderContent"



$ue_path = "C:/Epic Games/UE_4.27"
$ubt_path = "$ue_path/Engine/Binaries/DotNET/UnrealBuildTool.exe"
& $ubt_path Development Win64 -Project="C:/abotero/vertexforge/templates/ue427_template/ue427_template.uproject" -TargetType=Editor -Progress -NoEngineChanges -NoHotReloadFromIDE

# WARNING: Trying to build an enterprise target but the enterprise directory is missing. Falling back on engine components only.
# Using 'git status' to determine working set for adaptive non-unity build (C:\abotero\vertexforge\templates).
# Creating makefile for UE4Editor (no existing makefile)




Pop-Location