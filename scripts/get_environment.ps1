# scripts/get_environment.ps1
# Copyright Botero Tech 2023
# Created by Andrés Botero

$file_path = $PSScriptRoot

$env:PROJECT_ROOT = "$file_path/.."

$build_number = ""

$version_file = Get-Content "$env:PROJECT_ROOT/version.cfg"
foreach ($line in $version_file) {
    if ($line.StartsWith("build_number=")) {
        $project_version = $line -replace "build_number=",""
    }
}

$env:BUILD_NUMBER = $build_number
