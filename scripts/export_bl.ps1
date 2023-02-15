

$base_path = "$PSScriptRoot/.."

Push-Location $base_path

& scripts/setup_bl.ps1

$build_path = "export"


if (Test-Path -Path $build_path) {
    Write-Output "Cleaning output dir: $build_path"
    Remove-Item "$build_path" -Recurse
}

New-Item -ItemType directory -Path $build_path

# package blender plugin

$bl_product_name = "vertexforge"

$bl_source_path = "addons/$bl_product_name"
$bl_target_path = "$build_path/$bl_product_name"

Write-Output "Creating $bl_target_path folder"
New-Item -ItemType directory -Path $bl_target_path

$abs_bl_target_path = Resolve-Path $bl_target_path


Write-Output "Exporting : $bl_source_path to $abs_bl_target_path"
Push-Location $bl_source_path
git checkout-index --prefix="$abs_bl_target_path/" -a
Remove-Item "$abs_bl_target_path/docs" -Recurse
Pop-Location

$zip_path = "${bl_target_path}.zip"
$compress = @{
  Path = $bl_target_path
  CompressionLevel = "Fastest"
  DestinationPath = $zip_path
}
Write-Output "Creating $zip_path"
Compress-Archive @compress
