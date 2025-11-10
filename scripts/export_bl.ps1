# export_bl.ps1
# Copyright 2024 Andrés Botero 

$base_path = Resolve-Path "$PSScriptRoot/.."


# assumed to exist because of .keep file
$build_folder = "$base_path/build"

# package blender plugin
$bl_product_name = "bl_datasmith"
$bl_target_path = "$build_folder/${bl_product_name}"


if (Test-Path -Path $bl_target_path) {
    Write-Output "Cleaning $bl_target_path folder"
    Remove-Item "$bl_target_path" -Recurse
}
Write-Output "Copying to $bl_target_path"

Copy-Item -Path "$base_path/addons/${bl_product_name}" -Destination "$bl_target_path" -Recurse
Remove-Item "$bl_target_path/__pycache__" -Recurse -ErrorAction SilentlyContinue


# Specify the file path
$init_path = "$bl_target_path/__init__.py"



& $PSScriptRoot/get_environment.ps1
$build_number = $env:BUILD_NUMBER

$fixed = $false

$new_content = foreach($line in Get-Content $init_path) {
    if($line -match '(1, 1, 0)'){
        $fixed = $true
        # modify the line
        $line -replace "0","$build_number"
    }
    else {
        # leave the line unmodified
        $line
    }
}

Set-Content -Path $init_path -Value $new_content

if (-not $fixed) {
    throw
}



$zip_path = "${bl_target_path}-blender.zip"
if (Test-Path -Path $zip_path) {
    Write-Output "Cleaning $zip_path"
    Remove-Item "$zip_path"
}

$compress = @{
  Path = $bl_target_path
  # CompressionLevel = "Optimal"
  DestinationPath = $zip_path
}
Write-Output "Creating $zip_path"
Compress-Archive @compress
