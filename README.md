Vertexforge Environment
=======================

This folder wraps the build environment for the Vertexforge project. It has scripts to place them in specific places and deal with compiling and packaging them. The scripts are located in the unsurprisingly named `scripts` folder.

The `scripts/export_bl.ps1` script clones the blender plugin in an `addons` folder so we can set the working copy of this repo as a scripts folder in blender.

The `scripts/run_tests.ps1` script downloads blender versions to the `bin` folder.

The `DatasmithBlenderContent` repo is cloned to a folder of the same name

The `demos` folder is created from the `scripts/run_tests.ps1` script too. It uses SVN to download the demo files from a local network server.

`ueXX_template` folders shouldn't be needed anymore, as we're now able to build without wrapper projects

`www` folder holds the web server project

the `startup` folder also holds some utility that helps us debug stuff in blender




