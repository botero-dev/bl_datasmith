

$base_path = Resolve-Path "$PSScriptRoot/.."

# assumed to exist because of .keep file
$target_path = "$base_path"

$plugin_remote_path = "git@github.com:vertexforge/DatasmithBlenderContent.git"
$bl_product_name = "DatasmithBlenderContent"

git clone $plugin_remote_path "$target_path/$bl_product_name"
