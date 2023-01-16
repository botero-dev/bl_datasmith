
import unreal
import os

def ImportFromEnvironment():
	file_path = os.environ.get('DATASMITH_FILE_PATH')
	if not file_path:
		unreal.log_warning("File path not found in environment variable DATASMITH_FILE_PATH")
		return -1

	return ImportScene(file_path)


def ImportScene(ds_file_on_disk):

	print("Starting datasmith file import")


	ds_scene_in_memory = unreal.DatasmithSceneElement.construct_datasmith_scene_from_file(ds_file_on_disk)

	if ds_scene_in_memory is None:
		print("Scene loading failed.")
		return 1

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
	result = ds_scene_in_memory.import_scene("/Game/MyStudioScene")

	if not result.import_succeed:
		print("Importing failed.")
		return 1

	# Clean up the Datasmith Scene.
	ds_scene_in_memory.destroy_scene()
	print("Custom import process complete!")
	return 0
