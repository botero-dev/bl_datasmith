#!/usr/bin/env sh
# all.sh
# Copyright 2024 Andrés Botero 

# This is mostly a guide to run manually. check all.ps1 for better guide
# I usually run this in a linux env, so

echo "all.sh"
set -euv

./scripts/export_bl.sh
./scripts/build_all_linux.sh
./scripts/assemble.sh
./scripts/package_standalone.sh
