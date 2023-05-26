

param(
    #[Parameter(Mandatory)]
    [string] $target_path,
    
    #[Parameter(Mandatory)]
    [string] $ue_path,

    [switch] $is_ue5
)

$base_path = "$PSScriptRoot/.."

Push-Location $base_path

if (!$target_path) {
    echo "missing -target_path=XXXX"
    exit 1
}

if (!$ue_path) {
    echo "missing -ue_path=XXXX"
    exit 1
}


#mkdir "$target_path/Plugins"

$plugin_remote_path = "git@github.com:vertexforge/DatasmithBlenderContent.git"

git clone $plugin_remote_path "$base_path/DatasmithBlenderContent"



$uat_path = "$ue_path/Engine/Build/BatchFiles/RunUAT.bat"
$plugin_path = "$base_path/DatasmithBlenderContent/DatasmithBlenderContent.uplugin"

& $uat_path BuildPlugin "-plugin=$plugin_path" "-package=$target_path"



Pop-Location