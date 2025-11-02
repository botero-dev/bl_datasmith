# Datasmith exporter for Blender
# Copyright 2018-2022 Andrés Botero

bl_info = {
	"name": "Unreal Datasmith format",
	"author": "Andrés Botero",
	"version": (1, 1, 0),
	"blender": (2, 93, 0),
	"location": "File > Export > Datasmith (.udatasmith)",
	"description": "Export scene as Datasmith asset",
	"warning": "",
	"category": "Import-Export",
	"support": 'COMMUNITY',
	"wiki_url": "https://github.com/0xafbf/blender-datasmith-export",
}


if "bpy" in locals():
	import importlib
	if "export_datasmith" in locals():
		importlib.reload(export_datasmith)
	if "export_material" in locals():
		importlib.reload(export_material)


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

class ExportDatasmith(bpy.types.Operator, ExportHelper):
	"""Write a Datasmith file"""
	bl_idname = "export_scene.datasmith"
	bl_label = "Export Datasmith"
	bl_options = {'PRESET'}

	filename_ext = ".udatasmith"
	filter_glob: StringProperty(default="*.udatasmith", options={'HIDDEN'})


	export_selected: BoolProperty(
			name="Selected objects only",
			description="Exports only the selected objects",
			default=False,
		)
	use_instanced_meshes: BoolProperty(
			name="Use instanced meshes",
			description="Exports instancing objects and particles as UE instanced meshes. Useful for foliage",
			default=True,
		)
	apply_modifiers: BoolProperty(
			name="Apply modifiers",
			description="Applies geometry modifiers when exporting. "
				"(This may break mesh instancing)",
			default=True,
		)
	always_twosided: BoolProperty(
			name="All materials as two-sided",
			description="Adds a flag to all materials to export as two-sided.\n "
				"This is less optimal but matches better Blender's default behaviour.\n"
				"Materials with Backface Culling are exported one-sided",
			default=True,
		)
	export_animations: BoolProperty(
			name="Export animations",
			description="Export object animations (transforms only)",
			default=False,
		)
	export_metadata: BoolProperty(
			name="Write metadata",
			description="(maybe broken) Writes custom properties of objects and meshes as metadata. "
				"It may be useful to disable this when using certain addons",
			default=False,
		)
	skip_textures: BoolProperty(
			name="Skip writing textures",
			description="(maybe broken) Don't write textures when exporting the scene, "
				"allows for faster exporting, useful if you only changed "
				"transforms or shaders",
			default=False,
		)
	compatibility_mode: BoolProperty(
			name="Compatibility mode",
			description="Enable this if you don't have the UE4 plugin, "
				"Uses some nodes that UE4 has builtin, but at a reduced quality",
			default=False,
		)
	use_gamma_hack: BoolProperty(
			name="Use sRGB gamma hack (UE 4.24 and below)",
			description="Flags sRGB texture to use gamma as sRGB is not supported in old versions",
			default=False,
		)
	use_old_iterator: BoolProperty(
		name="Use old iterator",
		description="In case you want to use the old exporter, all features should "
				"be already in the new exporter. to be removed",
			default=False,
		)
	use_logging: BoolProperty(
			name="Enable logging",
			description="Enable logging to Window > System console and log file",
			default=False,
		)
	use_profiling: BoolProperty(
			name="Enable profiling",
			description="For development only, generates python profiling data",
			default=False,
		)
	use_telemetry: BoolProperty(
			name="Enable telemetry",
			description="Sends export result data to the devs to gather product defects",
			default=False,
		)
	
	def execute(self, context):
		keywords = self.as_keywords(ignore=("filter_glob",))
		from . import export_datasmith
		return export_datasmith.save(context, keywords)

def menu_func_export(self, context):
	self.layout.operator(ExportDatasmith.bl_idname, text="Datasmith (.udatasmith)")

def register():
	bpy.utils.register_class(ExportDatasmith)
	bpy.types.TOPBAR_MT_file_export.append(menu_func_export)

def unregister():
	bpy.types.TOPBAR_MT_file_export.remove(menu_func_export)
	bpy.utils.unregister_class(ExportDatasmith)


if __name__ == "__main__":
	register()
