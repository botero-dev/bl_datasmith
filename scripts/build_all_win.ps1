
$base_path = "$PSScriptRoot/.."

Push-Location $base_path

$ue_launcher_data = Get-Content "$env:ProgramData/Epic/UnrealEngineLauncher/LauncherInstalled.dat" -Raw | ConvertFrom-Json

$paths = @{}
foreach ( $app in $ue_launcher_data.InstallationList ) {
    $paths[$app.AppName] = $app.InstallLocation
}

$versions = @(
    "UE_4.27"
    "UE_5.4"
    "UE_5.5"
)

foreach ( $version in $versions ) {
    Write-Host ""
    Write-Host ""
    Write-Host "Building for version $version"
    Write-Host ""
    $ue_path = $paths[$version]

    $cmd_args = @(
        "$base_path/build/win/$version/DatasmithBlenderContent",
        "$ue_path"
    )

    echo "scripts/build_single_win.ps1 $cmd_args"
    & "scripts/build_single_win.ps1" @cmd_args
}

Compress-Archive -Path "build/win/*" -DestinationPath "build/win.zip"

Pop-Location
