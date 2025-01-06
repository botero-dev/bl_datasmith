

param(
    #[Parameter(Mandatory)]
    [string] $target_path,
    
    #[Parameter(Mandatory)]
    [string] $ue_path
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

$uat_path = "$ue_path/Engine/Build/BatchFiles/RunUAT.bat"
$plugin_path = "$base_path/DatasmithBlenderContent/DatasmithBlenderContent.uplugin"

$cmd_args = @(
    "BuildPlugin",
    "-plugin=$plugin_path",
    "-package=$target_path",
    "-TargetPlatforms=Win64"
)
echo "$uat_path $cmd_args"
& $uat_path @cmd_args

Pop-Location