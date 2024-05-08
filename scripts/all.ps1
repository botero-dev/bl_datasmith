# all.ps1
# Copyright 2024 Andrés Botero 

# This is mostly a guide to run manually.
$base_path = Resolve-Path "$PSScriptRoot/.."

& "$base_path/scripts/export_bl.ps1"
& "$base_path/scripts/assemble.ps1"
# assemble.ps1 calls all remote_build scripts
# & "$base_path/scripts/build_all_win.ps1"
# & "$base_path/scripts/remote_build_mac.sh"
& "$base_path/scripts/package_epic.ps1"
& "$base_path/scripts/package_gumroad.ps1"

