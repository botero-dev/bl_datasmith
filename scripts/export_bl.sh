#!/usr/bin/env sh
# export_bl.sh
# Copyright 2024 Andrés Botero 

. scripts/get_environment.sh

# Get the script directory
script_dir="$PROJECT_ROOT/scripts"
base_path="$PROJECT_ROOT"

# Assumed to exist because of .keep file
build_folder="$base_path/build"

mkdir -p "$build_folder"

# Package blender plugin
bl_product_name="bl_datasmith"
bl_folder_name="bl_datasmith"

bl_target_path="$build_folder/${bl_product_name}"

if [ -d "$bl_target_path" ]; then
    echo "Cleaning $bl_target_path folder"
    rm -rf "$bl_target_path"
fi

echo "Copying to $bl_target_path"
cp -r "$base_path/addons/$bl_folder_name" "$bl_target_path"
rm -rf "$bl_target_path/__pycache__"

# Specify the file path
init_path="$base_path/addons/$bl_folder_name/__init__.py"
target_path="$bl_target_path/__init__.py"

# Get the environment variables
. "$script_dir/get_environment.sh"
build_number=$BUILD_NUMBER

fixed=false

echo "Fixing __init__.py with build_number=$BUILD_NUMBER"

rm -f "$target_path"
while IFS= read -r line; do
    case "$line" in
        *"(1, 1, 0)"*)
            # Modify the line: replace '(1, 1, 0)' with '(1, 1, build_number)'
            fixed=true
            line=$(echo "$line" | sed "s/(1, 1, 0)/(1, 1, $build_number)/")
            ;;
    esac
    printf "%s\n" "$line" >> "$target_path"

done < "$init_path"


if ! $fixed; then
    echo "Error: The version line was not found or modified."
    exit 1
fi

# zip path is local to the build forlder
zip_path="${bl_product_name}-blender.zip"
if [ -f "$zip_path" ]; then
    echo "Cleaning $zip_path"
    rm "$zip_path"
fi

cd "$build_folder"
echo "Creating $zip_path"
zip -r "$zip_path" "$bl_product_name"
cd "$OLDPWD"
