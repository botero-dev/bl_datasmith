
$vf_root = "$PSScriptRoot/.."


echo "loading demos to $vf_root/demos"

$project_name = "blenderforge"

$svn_demos_path = "svn+ssh://ab-server.local/svn/$project_name/trunk/demos"

svn checkout "$svn_demos_path" "demos"