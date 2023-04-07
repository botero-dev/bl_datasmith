

Push-Location

$build_path = "build"


if (Test-Path -Path $build_path) {
    Write-Output "Cleaning output dir: $build_path"
    Remove-Item "$build_path" -Recurse
}


$package_src_path = "addons/blender-datasmith-export"
$package_dst_path = "$build_path/blender-datasmith-export"

Write-Output "Creating $package_dst_path folder"
New-Item -ItemType directory -Path $package_dst_path

$abs_package_dst_path = Resolve-Path $package_dst_path


Write-Output "Exporting : $package_src_path to $abs_package_dst_path"
Push-Location $package_src_path
git checkout-index --prefix="$abs_package_dst_path/" -a
Remove-Item "$abs_package_dst_path/docs" -Recurse
Pop-Location

$zip_path = "${package_dst_path}.zip"
$compress = @{
  Path = $package_dst_path
  CompressionLevel = "Fastest"
  DestinationPath = $zip_path
}
Write-Output "Creating $zip_path"
Compress-Archive @compress



$template_src = "demos/ue4_template"
$template_path = "$build_path/ue4_template"

Write-Output "Creating $template_path folder"

New-Item -ItemType directory -Path $template_path

Copy-Item -Path "$template_src/Binaries" -Destination "$template_path/" -Recurse
Copy-Item -Path "$template_src/Content" -Destination "$template_path/" -Recurse
Copy-Item -Path "$template_src/Config" -Destination "$template_path/" -Recurse
Copy-Item -Path "$template_src/Plugins" -Destination "$template_path/" -Recurse
Copy-Item -Path "$template_src/Scripts" -Destination "$template_path/" -Recurse
Copy-Item -Path "$template_src/ue4_template.uproject" -Destination "$template_path/"


$plugin_name = "DatasmithBlenderContent"
$plugin_path = "$build_path/$plugin_name"
Write-Output "Creating $plugin_path folder"

Copy-Item -Path "$template_src/Plugins/$plugin_name" -Destination "$plugin_path" -Recurse

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