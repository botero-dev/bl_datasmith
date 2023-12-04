

$base_path = Resolve-Path "$PSScriptRoot/.."


# assumed to exist because of .keep file
$build_folder = "$base_path/build"

# package blender plugin
$bl_product_name = "blue"
$bl_target_path = "$build_folder/${bl_product_name}"


if (Test-Path -Path $bl_target_path) {
    Write-Output "Cleaning $bl_target_path folder"
    Remove-Item "$bl_target_path" -Recurse
}
Write-Output "Copying to $bl_target_path"

Copy-Item -Path "$base_path/addons/blue" -Destination "$bl_target_path" -Recurse
Remove-Item "$bl_target_path/__pycache__" -Recurse -ErrorAction SilentlyContinue

# TODO: inject some version data into the build


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
