# package_gumroad.ps1
# Copyright Andrés Botero 2023

Write-Host "Exporting package for Gumroad"

& $PSScriptRoot/get_environment.ps1

$build_number = $env:BUILD_NUMBER
Write-Host "Packaging build number $build_number"

$base_path = Resolve-Path "$PSScriptRoot/.."
$build_path = "$base_path/build"



$platform = "mac"

$platform_path = "$build_path/$platform"
$zip_path = "$build_path/${platform}.zip"
if (Test-Path -Path $zip_path) {
    Remove-Item -Path "$platform_path" -Recurse -Force -ErrorAction SilentlyContinue
    Expand-Archive -Path "$zip_path" -DestinationPath "$platform_path"
}


$platform = "win"

$platform_path = "$build_path/$platform"
$zip_path = "$build_path/${platform}.zip"
if (Test-Path -Path $zip_path) {
    Remove-Item -Path "$platform_path" -Recurse -Force -ErrorAction SilentlyContinue
    Expand-Archive -Path "$zip_path" -DestinationPath "$platform_path"
}


$plugin_name = "DatasmithBlenderContent"
$release_path = "$base_path/export/gumroad"
$addon_name = "bl_datasmith"

$bl_zip_name = "${addon_name}-${build_number}-blender.zip"
$bl_zip_path = "$release_path/$bl_zip_name"

if (Test-Path -Path $release_path) {
    Remove-Item -Path "$release_path" -Recurse -Force
}

New-Item -Path "$release_path" -ItemType Directory

Copy-Item -Path "$build_path/${addon_name}-blender.zip" -Destination "$bl_zip_path" -Recurse

$engine_versions = @(
    "UE_5.4"
    "UE_5.5"
    "UE_5.6"
)

foreach($engine_version in $engine_versions) {

    $export_path = "$release_path/${engine_version}"

    if (Test-Path -Path $export_path) {
        Write-Host "Cleaning export path: $export_path"
        Remove-Item "$export_path" -Recurse
    }

    New-Item -ItemType Directory -Path $export_path > $null

    # we assume the other projects are checked out already
    # setup_ue already checked out unreal
    # export_bl already created the zip file for blender
    # and we will try to mix into the exported ue plugin the built versions we find in /build

    Write-Output "Copying : $bl_zip_path to $export_path"
    Copy-Item -Path "$bl_zip_path" -Destination "$export_path/" -Recurse

    $ue_plugin_path = "$base_path/$plugin_name"
    Copy-Item -Path "$ue_plugin_path" -Destination "$export_path" -Recurse

    $win_path_bin = "$build_path/win/$engine_version/$plugin_name/Binaries/Win64"
    if (Test-Path -Path $win_path_bin) {
        Write-Output "Copying : $win_path_bin"
        Write-Output "  to $export_path/$plugin_name/Binaries/"
        Copy-Item -Path "$win_path_bin" -Destination "$export_path/$plugin_name/Binaries/Win64" -Recurse -Exclude "*.pdb"
    }

    $mac_path_bin = "$build_path/mac/$engine_version/$plugin_name/Binaries/Mac"
    if (Test-Path -Path $mac_path_bin) {
        Write-Output "Copying : $mac_path_bin"
        Write-Output "  to $export_path/$plugin_name/Binaries/"
        Copy-Item -Path "$mac_path_bin" -Destination "$export_path/$plugin_name/Binaries/Mac" -Recurse
    }

    # for package_gumroad:
    # and build_all_win and build_all_mac called
    # and result were aggregated in /build/platform folders

    # Write-Host "Copying README"
    # Copy-Item -Path "README.txt" -Destination "$build_path/"

    $export_name = "${addon_name}-${build_number}-${engine_version}.zip"
    $build_filename = "$release_path/$export_name"

    Remove-Item -Path "$build_filename" -ErrorAction SilentlyContinue

    $final_build_compress = @{
      Path = "${export_path}/*"
      # CompressionLevel = "Optimal"
      DestinationPath = $build_filename
    }
    Write-Output "Creating $build_filename"
    $global:ProgressPreference = "SilentlyContinue"
    Compress-Archive @final_build_compress
}

