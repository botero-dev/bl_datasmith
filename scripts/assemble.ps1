
$base_path = "$PSScriptRoot/.."
Push-Location $base_path


$build_path = "$base_path/build"
New-Item -Path $build_path -ItemType Directory -Force

$username="abotero"
$host_win="pag-pc-mini.local"
$host_mac="andress-mac-mini.local"

$prefix_mac="${username}@${host_mac}"

echo "Pushing MacOS boostrap code"
$script_filename="bootstrap_mac.sh"
scp "scripts/remote_build_mac.sh" "${prefix_mac}:${script_filename}"

echo "Executing MacOS code"

echo ssh "$prefix_mac" sh "$script_filename"
ssh "$prefix_mac" sh "$script_filename"

echo "Pulling MacOS artifact"
scp "${prefix_mac}:tmp/vertexforge_build/build/mac.zip" "build/mac.zip"


$prefix_win="${username}@${host_win}"

echo "Pushing Windows boostrap code"
$script_filename="bootstrap_win.ps1"
scp "scripts/remote_build_windows.ps1" "${prefix_win}:${script_filename}"

echo "Executing Windows code"
ssh "$prefix_win" powershell "./${script_filename}"

echo "Pulling Windows artifact"
scp "${prefix_win}:/tmp/vertexforge_build/build/win.zip" "build/win.zip"

Pop-Location