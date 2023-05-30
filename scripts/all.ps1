# all.ps1
# Copyright 2023 Andrés Botero 

$base_path = Resolve-Path "$PSScriptRoot/.."

& "$base_path/scripts/export_bl.ps1"
# & "$base_path/scripts/build_all_win.ps1"
# & "$base_path/scripts/remote_build_mac.ps1.ps1"
& "$base_path/scripts/package_epic.ps1"
& "$base_path/scripts/package_gumroad.ps1"

