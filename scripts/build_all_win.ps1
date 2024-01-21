
$base_path = "$PSScriptRoot/.."

Push-Location $base_path

$ue_launcher_data = Get-Content "$env:ProgramData/Epic/UnrealEngineLauncher/LauncherInstalled.dat" -Raw | ConvertFrom-Json

$paths = @{}
foreach ( $app in $ue_launcher_data.InstallationList ) {
    $paths[$app.AppName] = $app.InstallLocation
}

$versions = @(
    "UE_4.27"
    "UE_5.0"
    "UE_5.1"
    "UE_5.2"
    "UE_5.3"
)

foreach ( $version in $versions ) {
    $ue_path = $paths[$version]
    & scripts/build_single_win.ps1 -target_path "$base_path/build/win/$version/DatasmithBlenderContent" -ue_path $ue_path
}

Pop-Location
