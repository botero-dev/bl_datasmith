#!/usr/bin/env sh

echo "Removing existing folders"
rm -rf build/win
rm -rf build/mac

echo unzip build/win.zip -d build/win
unzip build/win.zip -d build/win >> /dev/null
# for some funny reason, unzipped folders don't have execute flag
chmod -R u+X "build/win"

echo find build/win -name "*.pdb" -delete
find build/win -name "*.pdb" -delete


echo unzip build/mac.zip -d build/mac
unzip build/mac.zip -d build/mac >> /dev/null
chmod -R u+X "build/mac"


rm -rf "export/gumroad"

mkdir -p "export/gumroad"

monotonic="4"
cp "export/blue_blender.zip" "export/gumroad/blue-$monotonic-blender.zip"

engine_versions="UE_4.27 UE_5.0 UE_5.1 UE_5.2 UE_5.3"
IFS=" "

base=$(pwd)
for engine_version in $engine_versions; do
    cd "$base"
    echo "Exporting for $engine_version"
    release_path="export/gumroad"
    export_path="$release_path/$engine_version"

    rm -rf "$export_path"

    plugin_name="DatasmithBlenderContent"

    mkdir -p "$export_path/$plugin_name"

    ue_plugin_path="$plugin_name"
    cp -r "$ue_plugin_path" "$export_path"
    cp "export/blue_blender.zip" "$export_path"

    cp -r "build/win/$engine_version/$plugin_name/Binaries" "$export_path/$plugin_name/Binaries"
    cp -r "build/mac/$engine_version/$plugin_name" "$export_path"

    cd "$export_path"
    zip -r "../blue-$monotonic-${engine_version}.zip" "." > /dev/null
    echo "Packaged:" "blue-$monotonic-${engine_version}.zip"
done

echo "Done!"
