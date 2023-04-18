

$base_path = "$PSScriptRoot/.."


$target_path = "$base_path/addons"

#mkdir "$target_path/Plugins"

$plugin_remote_path = "git@github.com:0xafbf/blenderforge.git"

git clone $plugin_remote_path "$target_path/vertexforge"
