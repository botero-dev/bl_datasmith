
param (
    [switch] $profiling = $false,
    [switch] $bad = $false,
    [switch] $log = $false,
    [switch] $old = $false,
    [switch] $diff = $false,
    [switch] $animations = $false,
    [switch] $fast = $false,
    [switch] $test = $false,
    [switch] $b3 = $false,
    [string] $force_version,
    [switch] $single_thread = $false
)

if ($PSVersionTable.PSEdition -ne "Core") {
    Write-Host "This script was meant to be run from Powershell Core"
    exit 1
}


$scripts_folder = $PSScriptRoot
$root_folder = Resolve-Path "$scripts_folder/.."
$demos_folder = "$root_folder/demos"



$test_csv_rows = Import-Csv "$demos_folder/test_files.csv"

$versions = @{
    # "3_6" =    @{ version="3.6";  patch=21  };
    "3_6" =    @{ version="4.2";  patch=8  };
    "4_2" =    @{ version="4.2";  patch=8  };
    "latest" = @{ version="4.4";  patch=0  };
}

# TODO: make two phase export
$files_to_build = $()

$null = New-Item -Path "$root_folder/export/demos" -ItemType directory -ErrorAction SilentlyContinue
$report_path = "$root_folder/export/demos/report.csv"
if (-not (Test-Path $report_path)) {
    echo "timestamp, dir,name,status,time_seconds" > $report_path
}

foreach ($test_row in $test_csv_rows) {

    # skip any scene not in test group if we are using the "test"
    if ($test) {
        if (-not [boolean]$test_row.test) {
            continue
        }
    }

    # skip slow scenes if we are using the "fast" flag
    if ($fast) {
        if (-not [boolean]$test_row.fast) {
            continue
        }
    }

    # skip bad scenes if we didn't use the "bad" flag to try to use them
    if (-not $test_row.good) {
        if (-not $bad) {
            continue
        }
    }

    $base_file_path = $test_row.file_path
    $file_path = "$demos_folder/$base_file_path"
    $found = Test-Path -Path $file_path

    if (!$found) {
        echo "ERROR: file $file_path wasn't found."
        continue
    }

    $base_file_dir = Split-Path $base_file_path -Parent
    $target_file_dir = "$root_folder/export/demos/$base_file_dir"
    Write-Host "Writing to $target_file_dir"

    $null = New-Item -Path $target_file_dir -ItemType directory -ErrorAction SilentlyContinue

    $base_file_name = [System.IO.Path]::GetFileNameWithoutExtension($base_file_path)
    $target_file_path = "$target_file_dir/${base_file_name}.udatasmith"

    $desired_version = $test_row.version
    if ([boolean]$force_version) {
        $desired_version = $force_version
    }

    $ver = $versions[$desired_version]
    $blender_path = $(& "$scripts_folder/get_blender.ps1" -version $ver["version"] -patch $ver["patch"])


    $env:BLENDER_USER_SCRIPTS = "$root_folder"

    $command = @(
        "&", $blender_path,
        "-b", $file_path,
        #"--log-level", "-1",
        #"--log-file", "${target_file_path}.log",
        #"--debug-all",
        "--addons", "blue",
        "--python-exit-code", "17",
        "--python", "$scripts_folder/bl_export_datasmith.py"
    )

    if ($single_thread) {
        $command += "--threads"
        $command += "1"
    }

    $command += "--"
    $command += "--output"
    $command += $target_file_path
    if ($diff) {       $command += "--diff"    }
    if ($old) {        $command += "--old"    }
    if ($animations) { $command += "--animations"    }
    if ($log) {        $command += "--log"    }
    if ($profiling) {  $command += "--profiling"    }

    $command_str = $command -join " "
    echo $command_str
    $time = Measure-Command { iex $command_str }
    $last_result = $LASTEXITCODE
    $time_seconds = $time.TotalSeconds
    echo "($last_result) File $base_file_name took $time_seconds seconds."
    $timestamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    echo "$timestamp,$base_file_dir,$base_file_name,$last_result,$time_seconds" >> $report_path

}
