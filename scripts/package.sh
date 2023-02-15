#!/usr/bin/env bash

script_file="$0"
script_dir=$(dirname "${BASH_SOURCE[0]}")

base_path="$script_dir/.."


pushd "$base_path"


zip -r vertexforge.zip export

popd