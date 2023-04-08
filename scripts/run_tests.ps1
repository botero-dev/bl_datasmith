
param (
    [switch] $profiling = $false,
    [switch] $bad = $false,
    [switch] $log = $false,
    [switch] $old = $false,
    [switch] $diff = $false,
    [switch] $animations = $false,
    [switch] $fast = $false,
    [switch] $b3 = $false
)


$scripts_folder = $PSScriptRoot
$root_folder = "$scripts_folder/.."
$demos_folder = "$root_folder/demos"



$test_csv_rows = Import-Csv "$demos_folder/test_files.csv"

$versions = @{
    "2_9" =    @{ version=2.93; patch=16 };
    "3_3" =    @{ version=3.3;  patch=5  };
    "latest" = @{ version=3.5;  patch=0  };
}

# TODO: make two phase export
$files_to_build = $()

$null = New-Item -Path "$root_folder/export" -ItemType directory -ErrorAction SilentlyContinue
$report_path = "$root_folder/export/report.csv"
echo "file,status,time_seconds" > $report_path

foreach ($test_row in $test_csv_rows) {

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
    $null = New-Item -Path $target_file_dir -ItemType directory -ErrorAction SilentlyContinue

    $base_file_name = [System.IO.Path]::GetFileNameWithoutExtension($base_file_path)
    $target_file_path = "$target_file_dir/${base_file_name}.udatasmith"

    $ver = $versions[$test_row.version]
    $blender_path = $(& "$scripts_folder/get_blender.ps1" -version $ver["version"] -patch $ver["patch"])

    $command = @(
        "&", $blender_path,
        "-b", $file_path,
        "--python-exit-code", "17",
        "-P", "$scripts_folder/bl_export_datasmith.py",
        "--",
        "--output", $target_file_path
    )
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
    echo "$base_file_name,$last_result,$time_seconds" >> $report_path

}