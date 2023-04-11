# blender_datasmith.py
# Copyright Andrés Botero 2023

import unreal
import os
import csv
import time


def import_csv_scenes(csv_path):

	export_base_path = os.path.dirname(csv_path)

	with open(csv_path, newline="") as csv_file:
		csv_reader = csv.reader(csv_file)
		headers_list = next(csv_reader)
		headers = {}
		for idx in range(len(headers_list)):
			name = headers_list[idx]
			headers[name] = idx
		col_dir = headers["dir"]
		col_name = headers["name"]

		imported_scenes = []
		for row in csv_reader:
			relative_path = row[col_dir]
			file = "%s/%s/%s.udatasmith" % (export_base_path, relative_path, row[col_name])
			print(row[col_name], "file:%s" % file)
			imported_scene = import_scene(file, relative_path)
			if imported_scene:
				imported_scenes.append(imported_scene)
			else:
				print("failed loading file:", file)

		print("loaded all scenes, now saving")
		unreal.EditorLoadingAndSavingUtils.save_dirty_packages(True, True)



def import_scene(ds_file_on_disk, ds_target_path):

	ds_scene_in_memory = unreal.DatasmithSceneElement.construct_datasmith_scene_from_file(ds_file_on_disk)

	if ds_scene_in_memory is None:
		print("Scene loading failed.")
		return None

	# EXAMPLE: Modify the data in the scene to filter out or combine elements...
	'''
	# Remove any mesh whose name includes a certain keyword.
	remove_keyword = "exterior"      # we'll remove any actors with this string in their names.
	meshes_to_skip = set([])         # we'll use this set to temporarily store the meshes we don't need.

	# Remove from the scene any mesh actors whose names match the string set above.
	for mesh_actor in ds_scene_in_memory.get_all_mesh_actors():
	    actor_label = mesh_actor.get_label()
	    if remove_keyword in actor_label:
	        print("removing actor named: " + actor_label)
	        # add this actor's mesh asset to the list of meshes to skip
	        mesh = mesh_actor.get_mesh_element()
	        meshes_to_skip.add(mesh)
	        ds_scene_in_memory.remove_mesh_actor(mesh_actor)

	# Remove all the meshes we don't need to import.
	for mesh in meshes_to_skip:
	    mesh_name = mesh.get_element_name()
	    print("removing mesh named " + mesh_name)
	    ds_scene_in_memory.remove_mesh(mesh)
	'''

	# Set import options.
	import_options = ds_scene_in_memory.get_options(unreal.DatasmithImportOptions)
	import_options.base_options.scene_handling = unreal.DatasmithImportScene.NEW_LEVEL

	# Finalize the process by creating assets and actors.

	# Your destination folder must start with /Game/
	result = ds_scene_in_memory.import_scene("/Game/%s" % ds_target_path)

	if not result.import_succeed:
		print("Importing failed.")
		return None

	# Clean up the Datasmith Scene.
	ds_scene_in_memory.destroy_scene()
	print("Custom import process complete!")
	return result

print("Loaded Blender Datasmith Python module.")
