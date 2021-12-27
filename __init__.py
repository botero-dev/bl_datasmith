# Copyright Andrés Botero 2021

bl_info = {
	"name": "Unreal Datasmith Import",
	"author": "Andrés Botero",
	"version": (1, 0, 3),
	"blender": (2, 82, 0),
	"location": "File > Import > Datasmith (.udatasmith)",
	"description": "Import a Datasmith file",
	"warning": "",
	"category": "Import-Export",
	"support": 'COMMUNITY',
	"wiki_url": "",
}


if "bpy" in locals():
	import importlib
	if "import_datasmith" in locals():
		importlib.reload(import_datasmith)

import bpy
from bpy.props import (
		StringProperty,
		BoolProperty,
		FloatProperty,
		EnumProperty,
		)
from bpy_extras.io_utils import (
		ImportHelper,
		ExportHelper,
		path_reference_mode,
		axis_conversion,
		)

class ImportDatasmith(bpy.types.Operator, ImportHelper):
	"""Import a Datasmith file"""
	bl_idname = "import_scene.datasmith"
	bl_label = "Import Datasmith"
	bl_options = {'PRESET'}

	filename_ext = ".udatasmith"
	filter_glob: StringProperty(default="*.udatasmith", options={'HIDDEN'})

	try_update: BoolProperty(
		name = "Try update",
		description="Tries updating existing objects instead of creating new ones (TESTING)",
		default=False,
	)
	use_logging: BoolProperty(
		name="Enable logging",
		description="Enable logging to Window > System console",
		default=True,
	)
	log_level: EnumProperty(
		name="Log level",
		items=(
			("NEVER", "Never",    "Don't write a logfile"),
			("ERROR", "Errors",   "Only output critical information"),
			("WARN",  "Warnings", "Write warnings in logfile"),
			("INFO",  "Info",     "Write report info in logfile"),
			("DEBUG", "Debug",    "Write debug info in logfile"),
		),
		default="INFO",
	)

	def execute(self, context):
		keywords = self.as_keywords(ignore=("filter_glob",))
		from . import import_datasmith
		return import_datasmith.load_wrapper(context=context, **keywords)
		

def menu_func_export(self, context):
	self.layout.operator(ImportDatasmith.bl_idname, text="Datasmith (.udatasmith)")

def register():
	bpy.utils.register_class(ImportDatasmith)
	bpy.types.TOPBAR_MT_file_import.append(menu_func_export)

def unregister():
	bpy.types.TOPBAR_MT_file_import.remove(menu_func_export)
	bpy.utils.unregister_class(ImportDatasmith)


if __name__ == "__main__":
	register()
