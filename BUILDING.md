Building bl_datasmith
=====================

Building
--------

`scripts/all.ps1` shows the simplest steps to make a full build.

`scripts/export_bl.sh` creates the `bl_datasmith-blender.zip` file that can be
loaded in blender as an add-on.

These commands build the plugin for many versions of a specific OS in one run:
- `scripts/build_all_win.ps1`
- `scripts/build_all_mac.sh`
- `scripts/build_all_linux.sh`

you can build the plugin in remote hosts and then pull it back with the
`assemble.sh` or `assemble.ps1` scripts.

The `scripts/package_epic.ps1` makes a zip package that includes the UE plugin,
and the Blender add-on in another zip file

The `scripts/package_standalone.ps1` makes a folder with many zip files with the
plugin built for many UE versions. also a separate download of the Blender
plugin is provided.


Testing
-------

The `scripts/get_blender.ps1` script downloads blender versions to the `bin`
folder.

The `scripts/run_tests.ps1` script will batch export all files from a csv file.
