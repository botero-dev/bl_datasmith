#!/usr/bin/env sh
# scripts/get_environment.sh
# Copyright Botero Tech 2024
# Created by Andrés Botero

file_path=$(dirname "$0")
PROJECT_ROOT="$file_path/.."

# Read build_number from version.cfg using grep and awk
build_number=$(grep -o '^build_number=.*' "$PROJECT_ROOT/version.cfg" | sed 's/^build_number=//')

BUILD_NUMBER="$build_number"
