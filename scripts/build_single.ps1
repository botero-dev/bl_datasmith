

param(
    #[Parameter(Mandatory)]
    [string] $target_name,
    
    #[Parameter(Mandatory)]
    [string] $ue_path,

    [switch] $is_ue5
)

$base_path = "$PSScriptRoot/.."

Push-Location $base_path

if (!$target_name) {
    echo "missing -target_name=XXXX"
    exit 1
}

if (!$ue_path) {
    echo "missing -ue_path=XXXX"
    exit 1
}





$target_path = "$base_path/$target_name"

#mkdir "$target_path/Plugins"

$plugin_remote_path = "git@github.com:vertexforge/DatasmithBlenderContent.git"

git clone $plugin_remote_path "$target_path/Plugins/DatasmithBlenderContent"



$ubt_path = "$ue_path/Engine/Binaries/DotNET/UnrealBuildTool.exe"
if ($is_ue5) {
    $ubt_path = "$ue_path/Engine/Binaries/DotNET/UnrealBuildTool/UnrealBuildTool.exe"
}

$project_path = "$target_path/$target_name.uproject"


& $ubt_path Development Win64 "-Project=$project_path" -TargetType=Editor -Progress -NoEngineChanges -NoHotReloadFromIDE



Pop-Location