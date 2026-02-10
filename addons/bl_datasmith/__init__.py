# SPDX-FileCopyrightText: 2018-2025 Andrés Botero
# SPDX-License-Identifier: AGPL-3.0-only
# SPDX-FileName: __init__.py

from bpy import props, types, utils
from bpy_extras import io_utils
import importlib

bl_info = {
	"name": "Unreal Datasmith Import/Export",
	"author": "Andrés Botero",
	"version": (1, 1, 0),
	"blender": (2, 93, 0),
	"location": "File > Import/Export > Datasmith (.udatasmith)",
	"description": "Import from / Export to Datasmith scene format",
	"warning": "",
	"category": "Import-Export",
	"support": "COMMUNITY",
	"wiki_url": "https://github.com/botero-dev/bl_datasmith",
}


if "export_datasmith" in locals():
	importlib.reload(export_datasmith)  # noqa: F821
if "export_material" in locals():
	importlib.reload(export_material)  # noqa: F821
if "import_datasmith" in locals():
	importlib.reload(import_datasmith)  # noqa: F821


class ExportDatasmith(types.Operator, io_utils.ExportHelper):
	"""Write a Datasmith file"""

	bl_idname = "export_scene.datasmith"
	bl_label = "Export Datasmith"
	bl_options = {"PRESET"}

	filename_ext = ".udatasmith"
	filter_glob: props.StringProperty(default="*.udatasmith", options={"HIDDEN"})

	export_selected: props.BoolProperty(
		name="Selected objects only",
		description="Exports only the selected objects",
		default=False,
	)
	use_instanced_meshes: props.BoolProperty(
		name="Use instanced meshes",
		description="Exports instancing objects and particles as UE instanced meshes. Useful for foliage",
		default=True,
	)
	apply_modifiers: props.BoolProperty(
		name="Apply modifiers",
		description="Applies geometry modifiers when exporting. (This may break mesh instancing)",
		default=True,
	)
	always_twosided: props.BoolProperty(
		name="All materials as two-sided",
		description="Adds a flag to all materials to export as two-sided.\n This is less optimal but matches better Blender's default behaviour.\nMaterials with explicit Backface Culling are always exported one-sided",
		default=True,
	)
	export_animations: props.BoolProperty(
		name="Export animations",
		description="Export object animations (transforms only)",
		default=False,
	)
	export_metadata: props.BoolProperty(
		name="Write metadata",
		description="Writes custom properties of objects and meshes as metadata. It may cause conflicts with data of certain add-ons",
		default=False,
	)
	skip_textures: props.BoolProperty(
		name="Skip writing textures",
		description="(maybe broken) Don't write textures when exporting the scene, allows for faster exporting, useful if you only changed transforms or shaders",
		default=False,
	)
	compatibility_mode: props.BoolProperty(
		name="Compatibility mode",
		description="Enable this if you don't have the UE4 plugin, Uses some nodes that UE4 has builtin, but at a reduced quality",
		default=False,
	)
	use_gamma_hack: props.BoolProperty(
		name="Use sRGB gamma hack (UE 4.24 and below)",
		description="Flags sRGB texture to use gamma as sRGB is not supported in old versions",
		default=False,
	)
	use_old_iterator: props.BoolProperty(
		name="Use old iterator",
		description="In case you want to use the old exporter, all features should be already in the new exporter. to be removed",
		default=False,
	)
	use_logging: props.BoolProperty(
		name="Enable logging",
		description="Enable logging to Window > System console and log file",
		default=False,
	)
	use_profiling: props.BoolProperty(
		name="Enable profiling",
		description="For development only, generates python profiling data",
		default=False,
	)
	use_telemetry: props.BoolProperty(
		name="Enable telemetry",
		description="Sends export result data to the devs to gather product defects",
		default=False,
	)

	def execute(self, context):
		keywords = self.as_keywords(ignore=("filter_glob",))
		from . import export_datasmith

		return export_datasmith.save(context, keywords)


class ImportDatasmith(types.Operator, io_utils.ImportHelper):
	"""Import a Datasmith file"""

	bl_idname = "import_scene.datasmith"
	bl_label = "Import Datasmith"
	bl_options = {"PRESET"}

	filename_ext = ".udatasmith"
	filter_glob: props.StringProperty(default="*.udatasmith", options={"HIDDEN"})

	try_update: props.BoolProperty(
		name="Try update",
		description="Tries updating existing objects instead of creating new ones (TESTING)",
		default=False,
	)
	use_logging: props.BoolProperty(
		name="Enable logging",
		description="Enable logging to Window > System console",
		default=True,
	)
	log_level: props.EnumProperty(
		name="Log level",
		items=(
			("NEVER", "Never", "Don't write a logfile"),
			("ERROR", "Errors", "Only output critical information"),
			("WARN", "Warnings", "Write warnings in logfile"),
			("INFO", "Info", "Write report info in logfile"),
			("DEBUG", "Debug", "Write debug info in logfile"),
		),
		default="DEBUG",
	)

	def execute(self, context):
		keywords = self.as_keywords(ignore=("filter_glob",))
		from . import import_datasmith

		return import_datasmith.load_wrapper(context=context, **keywords)


def menu_func_export(self, context):
	self.layout.operator(ExportDatasmith.bl_idname, text="Datasmith (.udatasmith)")


def menu_func_import(self, context):
	self.layout.operator(ImportDatasmith.bl_idname, text="Datasmith (.udatasmith)")


def register():
	utils.register_class(ExportDatasmith)
	utils.register_class(ImportDatasmith)
	types.TOPBAR_MT_file_export.append(menu_func_export)
	types.TOPBAR_MT_file_import.append(menu_func_import)


def unregister():
	types.TOPBAR_MT_file_export.remove(menu_func_export)
	types.TOPBAR_MT_file_import.remove(menu_func_import)
	utils.unregister_class(ExportDatasmith)
	utils.unregister_class(ImportDatasmith)


if __name__ == "__main__":
	register()
