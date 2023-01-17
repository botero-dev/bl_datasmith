


param(
    #[Parameter(Mandatory)]
    [string] $template_path,
    
    #[Parameter(Mandatory)]
    [string] $target_name
)

$base_path = "$PSScriptRoot/.."

Push-Location $base_path

if (!$template_path)  {
    echo "missing -template_path XXXX"
    exit 1
}

if (!$target_name) {
    echo "missing -target_name XXXX"
    exit 1
}


$source_path = "$template_path/Plugins/DatasmithBlenderContent"

$build_path = "$base_path/build/$target_name"

$target_path = "$build_path/DatasmithBlenderContent"

Write-Output "Cleaning $target_path folder"
Remove-Item $target_path -Recurse

Write-Output "Creating $target_path folder"
New-Item -ItemType directory -Path $target_path

# we are specific because we don't want PDBs
# also for mac I guess we want other extensions
Copy-Item -Destination $target_path -Path "$source_path/Binaries" -Recurse -Exclude "*.pdb"
Copy-Item -Destination $target_path -Path "$source_path/Content" -Recurse
Copy-Item -Destination $target_path -Path "$source_path/Resources" -Recurse
Copy-Item -Destination $target_path -Path "$source_path/Shaders" -Recurse
Copy-Item -Destination $target_path -Path "$source_path/Source" -Recurse
Copy-Item -Destination $target_path -Path "$source_path/DatasmithBlenderContent.uplugin"
Copy-Item -Destination $target_path -Path "$source_path/README.txt" 



