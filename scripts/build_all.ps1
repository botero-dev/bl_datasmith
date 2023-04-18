
$base_path = "$PSScriptRoot/.."

Push-Location $base_path

$ue4_path = "C:/Epic Games/UE_4.27"
$ue5_path = "C:/Epic Games/UE_5.1"



& scripts/build_single.ps1 -target_name ue427_template -ue_path $ue4_path
& scripts/build_single.ps1 -target_name ue51_template -ue_path $ue5_path -is_ue5



Pop-Location