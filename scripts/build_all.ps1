
$base_path = "$PSScriptRoot/.."

Push-Location $base_path

$ue427_path = "C:/EpicGames/UE_4.27"
$ue51_path = "D:/Epic Games/UE_5.1"
$ue52_path = "D:/Epic Games/UE_5.2"


& scripts/build_single_win.ps1 -target_name "$base_path/build/ue427/DatasmithBlenderContent" -ue_path $ue427_path

& scripts/build_single_win.ps1 -target_name "$base_path/build/ue51/DatasmithBlenderContent" -ue_path $ue51_path

& scripts/build_single_win.ps1 -target_name "$base_path/build/ue52/DatasmithBlenderContent" -ue_path $ue52_path


Pop-Location