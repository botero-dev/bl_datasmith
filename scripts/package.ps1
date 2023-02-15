

$base_path = "$PSScriptRoot/.."

Push-Location $base_path

$build_path = "export"


if (Test-Path -Path $build_path) {
    Write-Output "Cleaning output dir: $build_path"
    Remove-Item "$build_path" -Recurse
}

New-Item -ItemType directory -Path $build_path

& scripts/export_bl.ps1

& scripts/build_all.ps1
& scripts/export_ue_all.ps1


Write-Output "Copying README"
Copy-Item -Path "README.txt" -Destination "$build_path/"

$date = Get-Date -Format "yyyy-MM-dd_HHmm"
$build_filename = "${build_path}_${date}.zip"

$final_build_compress = @{
  Path = "${build_path}/*"
  CompressionLevel = "Fastest"
  DestinationPath = $build_filename
}
Write-Output "Creating $build_filename"
Compress-Archive @final_build_compress