Blender Datasmith export plugin
===============================

Thanks for trying out this new version of the plugin!
Although close to release, this is preview software, so I apologize for
any issues you may encounter.

The files and folders included in this package are described below:

### blender-datasmith-export folder
You can install the plugin by copying this folder into your blender/addons folder. Alternatively you can place it in a folder you already use as addons folder.

### blender-datasmith-export.zip
This zip can be used to install the plugin in blender using the preferences pane.

### DatasmithBlenderContent
This is the UE4 Plugin folder. You need to copy this whole folder to an UE4 project Plugins folder to extend UE4 so it supports importing some blender functionality that UE4 doesn't provide by default. 

### ue4_template
This folder has an unreal project already prepared with the UE4 Blender Additions plugin. Although it doesn't pack anything special, I find it useful to just duplicate the folder whenever I need a clean environment for testing.

The plugin has only been tested with UE4 4.27, any other version is unsupported at the moment. People have reported it working on UE5, your mileage may vary.

## Telemetry
For this new version, I integrated some a simple telemetry marker. All it does is report what settings were active when you exported a scene, some scene statistics (size, export time, and so on), and error info if any error happened during the export. All the collected data is anonymous.


Please report any issue via Discord to 0xAFBF#8715

Copyright 2018-2022 Andrés Botero


OLD README:

Place the blender-datasmith-export folder in your blender/addons folder, or
add the blender-datasmith-export.zip file from the blender addons menu.

Add or merge the Plugins folder to an UE4 project before importing the
Datasmith file, also, make sure that the BlenderDatasmithAdditions plugin
is enabled in the UE4 plugins menu.

Please report any issue via Discord to 0xAFBF#8715

Copyright 2018-2022 Andrés Botero