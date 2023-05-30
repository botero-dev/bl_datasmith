

$base_path = Resolve-Path "$PSScriptRoot/.."


# assumed to exist because of .keep file
$build_folder = "$base_path/build"

# package blender plugin
$bl_product_name = "vertexforge"
$bl_source_path = "$build_folder/${bl_product_name}_repo"
$bl_target_path = "$build_folder/${bl_product_name}"



if (Test-Path -Path $bl_source_path) {
    Write-Output "Cleaning $bl_source_path folder"
    # we need to -Force because it has .git directory
    Remove-Item "$bl_source_path" -Recurse -Force
}
# assumed to exist because of .keep file
$plugin_remote_path = "git@github.com:0xafbf/blenderforge.git"
git clone $plugin_remote_path "$bl_source_path"


if (Test-Path -Path $bl_target_path) {
    Write-Output "Cleaning $bl_target_path folder"
    Remove-Item "$bl_target_path" -Recurse
}
New-Item -ItemType directory -Path $bl_target_path > $null


# TODO: inject some version data into the build


Write-Output "Exporting : $bl_source_path to $bl_target_path"
Push-Location $bl_source_path
git checkout-index --prefix="$bl_target_path/" -a
Remove-Item "$bl_target_path/docs" -Recurse
Remove-Item "$bl_target_path/testing" -Recurse
Remove-Item "$bl_target_path/CHANGELOG.md" -Recurse
Remove-Item "$bl_target_path/.gitignore" -Recurse
Pop-Location

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
