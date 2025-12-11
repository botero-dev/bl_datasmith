Building bl_datasmith
=====================

Building
--------

`scripts/all.sh` shows the simplest steps to make a full build.

`scripts/export_bl.sh` creates the `bl_datasmith-blender.zip` file that can be
loaded in blender as an add-on.

These commands build the plugin for many versions of a specific OS in one run:
- `scripts/build_all_win.ps1`
- `scripts/build_all_mac.sh`
- `scripts/build_all_linux.sh`

After building the plugin in remote hosts, pull it back with `assemble.sh`.


Packaging
---------

The `scripts/package_standalone.ps1` makes a folder with many zip files with the
plugin built for many UE versions. also a separate download of the Blender
plugin is provided.


Testing
-------

The `scripts/get_blender.ps1` script downloads blender versions to the `bin`
folder.

The `scripts/run_tests.ps1` script will batch export all files from a csv file.
