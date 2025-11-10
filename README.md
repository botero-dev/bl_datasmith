Blender IO Datasmith
====================

This repo contains a Blender addon to export Epic Games Datasmith format from
Blender, and a corresponding Plugin for Unreal Engine to support some features
that Blender can export into the Datasmith format.

Installation
------------
The Blender addon is provided free of charge to download from the GitHub
releases website. Additionally, you can pull the entire repository and add it
to the Blender scripts search paths. This will work seamlessly as Blender looks
up for a folder called "addons", and loads the modules from there.

The Unreal Engine plugin is provided as source code only. If you're interested
in trying it out, you can compile it yourself or you can acquire it from the
Gumroad Sale Page



This folder wraps the build environment for the Vertexforge project. It has
scripts to place them in specific places and deal with compiling and
packaging them. The scripts are located in the unsurprisingly named `scripts`
folder.

A full deployment would follow `scripts/all.ps1`

Working
-------

Blender plugin source code is at the folder `addons/bl_datasmith`. This
accomodation allows us to set the repo root folder as a scripts source folder in
Blender.


Building
--------

`scripts/export_bl.ps1` creates the `bl_datasmith-blender.zip` file that can be
loaded in blender as an addon.

`scripts/build_all_win.ps1` builds the UE plugin with many engine versions.
`scripts/build_all_mac.sh` does the same in Mac.

you can build the plugin in remote hosts and then pull it back with the
`assemble.sh` or `assemble.ps1` scripts.


The `scripts/package_epic.ps1` makes a zip package that includes the UE plugin,
and the Blender addon in another zip file

The `scripts/package_standalone.ps1` makes a folder with many zip files with the
plugin built for many UE versions. also a separate download of the Blender
plugin is provided.


Testing
-------

The `scripts/get_blender.ps1` script downloads blender versions to the `bin`
folder.


The `demos` folder is created from the `scripts/run_tests.ps1` script too. It
uses SVN to download the demo files from a local network server.

the `startup` folder also holds some utility that helps us debug stuff in
blender
