# package_gumroad.ps1
# Copyright Andrés Botero 2023

Write-Host "Exporting package for Gumroad"


$base_path = Resolve-Path "$PSScriptRoot/.."
$build_path = "$base_path/build"
$repo_name = "DatasmithBlenderContent"

$engine_versions = @(
    "UE_4.27"
    "UE_5.1"
    "UE_5.2"
)

$date = Get-Date -Format "yyyy-MM-dd_HHmm"

$release_path = "$base_path/export/gumroad/$date"

foreach($engine_version in $engine_versions) {

    $export_path = "$release_path/${engine_version}"

    if (Test-Path -Path $export_path) {
        Write-Host "Cleaning export path: $export_path"
        Remove-Item "$export_path" -Recurse
    }

    New-Item -ItemType directory -Path $export_path > $null

    # we assume the other projects are checked out already
    # setup_ue already checked out unreal
    # export_bl already created the zip file for blender
    # and we will try to mix into the exported ue plugin the built versions we find in /build

    $ue_plugin_path = "$base_path/$repo_name"
    Write-Output "Exporting : $ue_plugin_path to $export_path/$repo_name"
    Push-Location $ue_plugin_path
    git checkout-index --prefix="$export_path/$repo_name/" -a
    # Remove-Item "$export_path/docs" -Recurse
    Pop-Location


    $win_path_bin = "$build_path/win/$engine_version/$repo_name/Binaries/Win64"
    if (Test-Path -Path $win_path_bin) {
        Write-Output "Copying : $win_path_bin"
        Write-Output "  to $export_path/$repo_name/Binaries/"
        Copy-Item -Path "$win_path_bin" -Destination "$export_path/$repo_name/Binaries/Win64" -Recurse -Exclude "*.pdb"
    }

    $mac_path_bin = "$build_path/mac/$engine_version/$repo_name/Binaries/Mac"
    if (Test-Path -Path $mac_path_bin) {
        Write-Output "Copying : $mac_path_bin"
        Write-Output "  to $export_path/$repo_name/Binaries/"
        Copy-Item -Path "$mac_path_bin" -Destination "$export_path/$repo_name/Binaries/Mac" -Recurse
    }


    Write-Output "Copying : $build_path/vertexforge-blender.zip to $export_path"
    Copy-Item -Path "$build_path/vertexforge-blender.zip" -Destination "$export_path/" -Recurse


    # for package_gumroad:
    # and build_all_win and build_all_mac called
    # and result were aggregated in /build/platform folders


    # Write-Host "Copying README"
    # Copy-Item -Path "README.txt" -Destination "$build_path/"

    $build_filename = "$release_path/vertexforge-${engine_version}.zip"

    $final_build_compress = @{
      Path = "${export_path}/*"
      # CompressionLevel = "Optimal"
      DestinationPath = $build_filename
    }
    Write-Output "Creating $build_filename"
    $global:ProgressPreference = "SilentlyContinue"
    Compress-Archive @final_build_compress
}

Copy-Item -Path "$build_path/vertexforge-blender.zip" -Destination "$release_path/" -Recurse
