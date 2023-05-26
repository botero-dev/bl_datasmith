

$base_path = Resolve-Path "$PSScriptRoot/.."

& $base_path/scripts/setup_bl.ps1

# assumed to exist because of .keep file
$build_folder = "$base_path/build"

# package blender plugin
$bl_product_name = "vertexforge"
$bl_source_path = "$base_path/addons/$bl_product_name"
$bl_target_path = "$build_folder/$bl_product_name"



if (Test-Path -Path $bl_target_path) {
    Write-Output "Cleaning $bl_target_path folder"
    Remove-Item "$bl_target_path" -Recurse
}
New-Item -ItemType directory -Path $bl_target_path > $null


Write-Output "Exporting : $bl_source_path to $bl_target_path"
Push-Location $bl_source_path
git checkout-index --prefix="$bl_target_path/" -a
Remove-Item "$bl_target_path/docs" -Recurse
Pop-Location

$zip_path = "${bl_target_path}.zip"
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
