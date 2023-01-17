


$base_path = "$PSScriptRoot/.."

Push-Location $base_path

& scripts/package_single.ps1 -template_path ue427_template -target_name "UE 4.27"
& scripts/package_single.ps1 -template_path ue51_template -target_name "UE 5.1"

Pop-Location
