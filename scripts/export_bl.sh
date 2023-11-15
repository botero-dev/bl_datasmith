#!/usr/bin/env sh

echo "export_bl.sh"

rm -rf export/blue_blender
rm export/blue_blender.zip

cp -r addons/blue export/blue_blender

rm -rf export/blue_blender/__pycache__

cd export

zip -r "blue_blender.zip" "blue_blender"
