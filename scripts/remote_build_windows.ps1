
$build_path="C:/tmp/vertexforge_build"
Remove-Item -Path $build_path -Recurse -Force
New-Item -Path $build_path -ItemType Directory -Force

git clone git@github.com:vertexforge/vertexforge.git $build_path
Push-Location $build_path

& scripts/build_all_win.ps1

Compress-Archive -Path "build/win/*" -DestinationPath "build/win.zip"


echo "FINISHED"

Pop-Location
