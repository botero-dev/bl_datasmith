# todo: get unreal editor from somewhere

$ue_cmd = "C:/Epic Games/UE_4.27/Engine/Binaries/Win64/UE4Editor-Cmd.exe"
$project_path = "$PSScriptRoot/../ue427_template/ue427_template.uproject"
$ue_python_script = "$PSScriptRoot/../scripts/ue_import_from_exported.py"

# another way, runs full editor
& $ue_cmd $project_path -log -ExecutePythonScript="$ue_python_script"

# this way runs the editor headless
# & $ue_cmd  -run=pythonscript -script="$ue_python_script"
