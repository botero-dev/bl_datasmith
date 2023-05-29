
param (
    [string] $version = "2.93",
    [string] $patch = "16"
)

$root_path = "$PSScriptRoot/.."



$executable_dir = "${root_path}/bin"

$version_name = "blender-${version}.${patch}-windows-x64"


$executable_path = "${executable_dir}/${version_name}/blender.exe"

if (!(Test-Path $executable_path)) {
    $null = New-Item -Path $executable_dir -ItemType directory -ErrorAction SilentlyContinue

    $base_url = "https://mirrors.ocf.berkeley.edu/blender/release"
    $full_url = "$base_url/Blender${version}/${version_name}.zip"

    $engine_download_url = $full_url
    $engine_zip_file_path = "${executable_dir}/${version_name}.zip"

    $global:ProgressPreference = "SilentlyContinue"
    Write-Host "Blender ${version}.${patch} not found, downloading."
    Invoke-WebRequest -Uri $engine_download_url -OutFile $engine_zip_file_path

    Write-Host "Blender ${version}.${patch} downloaded, unpacking."
    Expand-Archive $engine_zip_file_path -DestinationPath $executable_dir

    Write-Host "Deleting zip file."
    Remove-Item $engine_zip_file_path
    $global:ProgressPreference = "Continue"

}

echo $(Resolve-Path $executable_path)

