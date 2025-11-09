#!/usr/bin/env sh

. scripts/get_environment.sh


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

monotonic="$BUILD_NUMBER"
blender_export_path="export/gumroad/blue-$monotonic-blender.zip"
cp "build/blue-blender.zip" "$blender_export_path"

engine_versions="UE_5.4 UE_5.5 UE_5.6"
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

    ue_plugin_path="ue_template/Plugins/$plugin_name"
    cp -r "$ue_plugin_path" "$export_path"
    cp "$blender_export_path" "$export_path"
    cp -r "build/win/$engine_version/$plugin_name" "$export_path"
    cp -r "build/mac/$engine_version/$plugin_name" "$export_path"
    cp -r "build/linux/$engine_version/$plugin_name" "$export_path"

    cd "$export_path"
    zip -r "../blue-$monotonic-${engine_version}.zip" "." > /dev/null
    echo "Packaged:" "blue-$monotonic-${engine_version}.zip"
done

echo "Done!"
