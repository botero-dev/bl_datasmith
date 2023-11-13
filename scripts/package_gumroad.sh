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


rm -rf "export"

engine_versions="UE_4.27 UE_5.2 UE_5.3"
IFS=" "

for engine_version in $engine_versions; do

    echo "Exporting for $engine_version"
    release_path="export/gumroad"
    export_path="$release_path/$engine_version"

    rm -rf "$export_path"

    plugin_name="DatasmithBlenderContent"

    mkdir -p "$export_path/$plugin_name"

    ue_plugin_path="$plugin_name"
    cp -r "$ue_plugin_path" "$export_path"

    cp -r "build/win/$engine_version/$plugin_name/Binaries" "$export_path/$plugin_name/Binaries"
    cp -r "build/mac/$engine_version/$plugin_name" "$export_path"

    zip -r "export/gumroad/vertexforge_1234_${engine_version}.zip" "$export_path"
done

echo "Done!"
