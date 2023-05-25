#!/usr/bin/env bash
# build_all_mac.sh
# Copyright Andrés Botero 2023

script_file="$0"
script_dir=$(dirname "${BASH_SOURCE[0]}")

base_path="$script_dir/.."



ue4_path="/Users/Shared/Epic Games/UE_4.27"
ue51_path="/Users/Shared/Epic Games/UE_5.1"
ue52_path="/Users/Shared/Epic Games/UE_5.2"

pushd "$base_path"
base_path=$(pwd)

scripts/build_single_mac.sh --target_path "$base_path/build/ue427" --ue_path "$ue4_path"
#scripts/build_single_mac.sh --target_path "$base_path/build/ue51" --ue_path "$ue51_path"
#scripts/build_single_mac.sh --target_path "$base_path/build/ue52" --ue_path "$ue52_path"

popd
