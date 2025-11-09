# remote_build_win.ps1
# Copyright 2024 Andrés Botero

$build_path = "C:/tmp/vertexforge_build"
$branch_name = "$args[0]"

Remove-Item -Path $build_path -Recurse -Force
New-Item -Path $build_path -ItemType Directory -Force

git clone git@github.com:vertexforge/vertexforge.git $build_path
Push-Location $build_path

git checkout "$branch_name"

& scripts/build_all_win.ps1

echo "FINISHED"

Pop-Location
