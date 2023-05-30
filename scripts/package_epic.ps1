# package_epic.ps1
# Copyright Andrés Botero 2023

Write-Host "Exporting package for Epic Marketplace"

$base_path = Resolve-Path "$PSScriptRoot/.."
$build_path = "$base_path/build"
$repo_name = "DatasmithBlenderContent"

$export_path = "$base_path/export/epic/$repo_name"

if (Test-Path -Path $export_path) {
    Write-Host "Cleaning export path: $export_path"
    Remove-Item "$export_path" -Recurse
}

New-Item -ItemType directory -Path $export_path > $null

# we assume the other projects are checked out already
# setup_ue already checked out unreal
# export_bl already created the zip file for blender

$ue_plugin_path = "$base_path/$repo_name"
Write-Output "Exporting : $ue_plugin_path to $export_path"
Push-Location $ue_plugin_path
git checkout-index --prefix="$export_path/" -a
# Remove-Item "$export_path/docs" -Recurse
Pop-Location
#todo: clean .gitignore file from export path


Write-Output "Copying : $build_path/vertexforge-blender.zip to $export_path"
Copy-Item -Path "$build_path/vertexforge-blender.zip" -Destination "$export_path/" -Recurse


# for package_gumroad:
# and build_all_win and build_all_mac called
# and result were aggregated in /build/platform folders


# Write-Host "Copying README"
# Copy-Item -Path "README.txt" -Destination "$build_path/"

$date = Get-Date -Format "yyyy-MM-dd_HHmm"
$build_filename = "${export_path}_${date}.zip"

$final_build_compress = @{
  Path = "${export_path}"
  CompressionLevel = "Fastest"
  DestinationPath = $build_filename
}
Write-Output "Creating $build_filename"
Compress-Archive @final_build_compress