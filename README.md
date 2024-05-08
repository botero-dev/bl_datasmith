Vertexforge Environment
=======================

This folder wraps the build environment for the Vertexforge project. It has
scripts to place them in specific places and deal with compiling and
packaging them. The scripts are located in the unsurprisingly named `scripts`
folder.

A full deployment would follow `scripts/all.ps1`

Working
--------

Blender plugin source code is at the folder `addons/blue`. This accomodation
allows us to set the repo root folder as a scripts source folder in Blender.


Building
--------

`scripts/export_bl.ps1` creates the `blue-blender.zip` file that can be loaded
in blender as an addon.

`scripts/build_all_win.ps1` builds the UE plugin with many engine versions.
`scripts/build_all_mac.sh` does the same in Mac.

you can build the plugin in remote hosts and then pull it back with the
`assemble.sh` or `assemble.ps1` scripts.


The `scripts/package_epic.ps1` makes a zip package that includes the UE
plugin, and the Blender addon in another zip file

The `scripts/package_gumroad.ps1` makes a folder with many zip files with the
plugin built for many UE versions. also a separate download of the Blender
plugin is provided.


Deploying
---------

`www` folder holds the web server project


Testing
-------

The `scripts/get_blender.ps1` script downloads blender versions to the `bin`
folder.


The `demos` folder is created from the `scripts/run_tests.ps1` script too. It
uses SVN to download the demo files from a local network server.

the `startup` folder also holds some utility that helps us debug stuff in
blender
