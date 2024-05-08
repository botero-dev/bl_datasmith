#! sh
# all.sh
# Copyright 2024 Andrés Botero 

# This is mostly a guide to run manually. check all.ps1 for better guide

./scripts/export_bl.sh
./scripts/assemble.sh
# & "$base_path/scripts/package_epic.ps1"
./scripts/package_gumroad.sh
