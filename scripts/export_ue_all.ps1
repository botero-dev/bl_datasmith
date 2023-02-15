


$base_path = "$PSScriptRoot/.."

Push-Location $base_path

& scripts/export_ue_single.ps1 -template_path ue427_template -target_name "4.27"
& scripts/export_ue_single.ps1 -template_path ue51_template -target_name "5.1"

Pop-Location
