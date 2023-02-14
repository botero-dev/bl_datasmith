# /usr/bin/env bash

script_file="$0"
script_dir=$(dirname "${BASH_SOURCE[0]}")

base_path="$script_dir/.."


ue4_path="/Users/Shared/Epic Games/UE_4.27"
ue5_path="/Users/Shared/Epic Games/UE_5.1"

pushd "$base_path"

$ue4_path = "C:/Epic Games/UE_4.27"
$ue5_path = "C:\Program Files\Epic Games\UE_5.1"

scripts/build_single_mac.sh --target_name ue427_template --ue_path "$ue4_path"
scripts/build_single_mac.sh --target_name ue51_template --ue_path "$ue5_path" --is_ue5

popd
