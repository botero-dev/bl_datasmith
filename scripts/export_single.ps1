

param(
    #[Parameter(Mandatory)]
    [string] $project_name,
    [string] $bundle_name
    
)

$base_path = "$PSScriptRoot/.."

Push-Location $base_path

$plugin_path = "$base_path/$project_name/Plugins/DatasmithBlenderContent"

$export_path = "$base_path/export"

Copy-Item $plugin_path -Destination $export_path -Recurse -Exclude "*.pdb"




Pop-Location