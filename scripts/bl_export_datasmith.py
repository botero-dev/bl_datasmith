#
#
# datasmith export test suite
# run this file with the following command:
# blender -b sample_file.blend -P test_datasmith_export.py

# we don't use argparse because blender doesn't filter out the params 

import logging
import os
import shutil
import sys
import time

import bpy
import bpy.ops


print("args: %s" % sys.argv)

arg_output = None
if "--output" in sys.argv:
	idx = sys.argv.index("--output")
	arg_output = sys.argv[idx+1]

arg_log = "--log" in sys.argv
arg_animations = "--animations" in sys.argv
arg_profiling = "--profiling" in sys.argv
arg_old = "--old" in sys.argv
arg_diff = "--diff" in sys.argv

logging_level = logging.WARNING
if arg_log:
	logging_level = logging.DEBUG

logging.basicConfig(
	level=logging_level,
	# format='%(asctime)s.%(msecs)03d %(name)-12s %(levelname)-8s %(message)s',
	format='%(asctime)s.%(msecs)03d %(levelname)-8s %(message)s',
	datefmt='%Y-%m-%d %H:%M:%S'
)
log = logging.getLogger()
log.setLevel(logging_level)

target_path = arg_output
if not target_path:
	clean_path = os.path.normpath(bpy.data.filepath)
	base_dir, file_name = os.path.split(clean_path)
	file_base, file_ext = os.path.splitext(file_name)
	target_path = "%s/%s.udatasmith" % (base_dir, file_base)

# we do this again to get fresh paths in case --output was set
base_dir, file_name = os.path.split(target_path)
file_base, file_ext = os.path.splitext(file_name)


# if a file already exists with the target_path, then backup that file
# with its creation date

backup_path = None
if os.path.isfile(target_path):
	last_modification_time = os.path.getmtime(target_path)
	time_str = time.strftime('%Y%m%d_%H%M%S', time.localtime(last_modification_time))
	backup_path = "%s/%s_%s.udatasmith" % (base_dir, file_base, time_str)
	log.debug("Backing up previous run: %s", backup_path)
	shutil.copy(target_path, backup_path)


custom_args = {}
custom_args["use_gamma_hack"] = False
custom_args["apply_modifiers"] = True
custom_args["compatibility_mode"] = False
custom_args["skip_textures"] = False
custom_args["export_metadata"] = False

custom_args["export_animations"] = arg_animations
custom_args["use_logging"] = arg_log
custom_args["use_profiling"] = arg_profiling
custom_args["use_old_iterator"] = arg_old

log.info("Writing %s" % target_path)
log.info("Export settings: %s" % custom_args)

bpy.ops.export_scene.datasmith(filepath=target_path, **custom_args)
log.info("Finished export.")


if backup_path and arg_diff:

	log.info("Writing diff file...")
	import difflib

	with open(backup_path) as ff:
		from_lines = ff.readlines()
	with open(target_path) as tf:
		to_lines = tf.readlines()

	diff = difflib.unified_diff(from_lines, to_lines, backup_path, target_path)

	new_modification_time = os.path.getmtime(target_path)
	local_time = time.localtime(new_modification_time)
	new_time_str = time.strftime('%Y%m%d_%H%M%S', local_time)
	diff_path = "%s/%s_%s.diff" % (base_dir, file_base, new_time_str)
	with open(diff_path, 'w') as diff_file:
		diff_file.writelines(diff)
	static_diff_path = "%s/%s.diff" % (base_dir, file_base)
	shutil.copy(diff_path, static_diff_path)


