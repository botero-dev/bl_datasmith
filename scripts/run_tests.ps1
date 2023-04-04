
param (
    [switch] $profiling = $false,
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
    "3" =      @{ version=3.3;  patch=5 };
    "latest" = @{ version=3.5;  patch=0};
}

$files_to_build = $()

foreach ($test_row in $test_csv_rows) {
    $base_file_path = $test_row.file_path
    $file_path = "$demos_folder/$base_file_path"
    $found = Test-Path -Path $file_path

    if (!$found) {
        echo "ERROR: file $file_path wasn't found."
        continue
    }

    $skip = $false
    if ($fast) {
        $skip = $true
        if ($test_row.fast -eq "x") {
            $skip = $false
        }
    }
    if ($skip) {
        continue
    }

    $ver = $versions[$test_row.version]
    $blender_path = $(& "$scripts_folder/get_blender.ps1" -version $ver["version"] -patch $ver["patch"])

    $cmd = @(
        "&"
        $blender_path
        $file_path
    )

    echo $($cmd -join " ")



}