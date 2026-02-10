Blender IO Datasmith
====================

This repo contains a Blender add-on to import and export Epic Games Datasmith
format from Blender, and a corresponding plugin for Unreal Engine to support
some features that Blender can export into the Datasmith format.


Features
--------

- Scene hierarchy
- Meshes
- Textures
- Materials and node graphs
- Instanced meshes
- Lights and cameras
- Object transform animations


Installation
------------

Check for the latest version in the Releases section in Github. You can download
packaged zip files for the Blender add-on and the Unreal Engine plugin. 

To install the Blender add-on, you can download and add it to Blender through the
preferences window. Alternatively you can download the repo and add the root of
it as a source of scripts within Blender preferences. This way is recommended
for development to make it easier to work on the add-on.

The Unreal Engine plugin should be downloaded for the relevant version and
placed in the Plugins folder of your project. You can also place it in the UE
Engine folder, but this is not widely tested.


Usage
-----

To use the plugin, just browse in the Blender import/export menus and select the
Datasmith format.

IMPORTANT: From Unreal, you can import the datasmith file normally, but you need
to fix the blender_curves asset to NOT use compression. You can do this in to
ways:

- Find the file in the Textures folder that was created when importing the
  files. Edit the texture type to use HDR uncompressed.
- Use the Dataprep asset included in the plugin folder.


Building
--------

For additional information on how to build and package the project, check
<BUILDING.md>


Support
-------

To support the project, please consider joining as a Github Sponsor clicking the
button in the sidebar.

To get support for the plugin, join the [Discord server].

[Discord server]: https://discord.gg/JnuAJcEwCb

If you identified a bug and you have consistent repro steps, you can submit an
issue in Github. Please attach any project files that can be used to reproduce
the issue as needed.


License
-------

See [LICENSE.txt](LICENSE.txt)
