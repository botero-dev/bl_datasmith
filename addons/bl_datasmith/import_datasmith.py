# Copyright Andrés Botero 2021

import bpy
import idprop
import bmesh
import math
import os
import time
import hashlib
import shutil
from os import path
from mathutils import Matrix, Vector, Euler, Quaternion

import logging
import numpy as np
import xml.etree.ElementTree as ET

log = logging.getLogger("bl_datasmith")


matrix_normals = [
	[1, 0, 0],
	[0, -1, 0],
	[0, 0, 1],
]

# used for lights and cameras, whose forward is (0, 0, -1) and its right is (1, 0, 0)
matrix_forward = Matrix(((0, 1, 0, 0), (0, 0, -1, 0), (-1, 0, 0, 0), (0, 0, 0, 1)))


def handle_transform(node, iter):
	p = lambda x: float(node.attrib[x])
	loc = (p("tx"), p("ty"), p("tz"))
	rot = (p("qw"), p("qx"), p("qy"), p("qz"))
	scale = (p("sx"), p("sy"), p("sz"))

	action, closing = next(iter)
	assert action == "end"
	assert closing == node

	return (loc, rot, scale)


def unhandled(_ctx, node, iter):
	# if node.tag == "material":
	# import pdb
	# pdb.set_trace()
	log.debug("<%s UNHANDLED>" % node.tag)
	for action, child in iter:
		if child == node:
			assert action == "end"
			return node
	log.error("never got end event")


# same as unhandled, but won't print if unhandled
def ignore(_ctx, node, iter):
	for action, child in iter:
		if child == node:
			assert action == "end"
			return node
	log.error("never got end event")


def handle_actor_children(target, node, iter):
	# strangely, an actor 'visible' flag is in its children node
	visible_str = node.attrib["visible"]
	visible = visible_str in ["true", "True", "TRUE", "1"]
	# we also have "selector" (bool) and "selection" (int) which we won't check for now

	for action, child in iter:
		if action == "end":
			break
		actor_child = handle_actor_common(None, child, iter)
		assert actor_child != None
		target["children"].append(actor_child)

	assert child == node
	assert action == "end"


def check_close(node, iter):
	action, child = next(iter)
	assert child == node
	assert action == "end"


def fill_value(target, node, iter):
	check_close(node, iter)
	target[node.tag] = float(node.attrib["value"])


def fill_value_str(target, node, iter):
	check_close(node, iter)
	target[node.tag] = node.attrib["value"]


def fill_light_color(target, node, iter):
	check_close(node, iter)
	attr = node.attrib
	use_temp = attr["usetemp"]
	target["color"] = (float(attr["R"]), float(attr["G"]), float(attr["B"]))


def parse_kvp_bool(text_value):
	return text_value


def parse_kvp_color(text_value):
	return text_value


def parse_kvp_texture(text_value):
	return text_value


def parse_kvp_float(text_value):
	return text_value


parse_kvp = {
	"Bool": parse_kvp_bool,
	"Color": parse_kvp_color,
	"Texture": parse_kvp_texture,
	"Float": parse_kvp_float,
}


def fill_keyvalueproperty(target, node, iter):
	check_close(node, iter)
	prop_name = node.attrib["name"]
	prop_type = node.attrib["type"]

	parser = parse_kvp.get(prop_type)
	if parser == None:
		log.error(f"unable to find parser for {prop_type}")
	assert parser != None
	target[prop_name] = parser(node.attrib["val"])


def fill_transform(target, node, iter):
	check_close(node, iter)

	attr = node.attrib
	p = lambda x: float(attr[x])
	# we manually set the Y coordinate to negative
	loc = (p("tx"), p("ty"), p("tz"))
	rot = (p("qw"), p("qx"), p("qy"), p("qz"))
	scale = (p("sx"), p("sy"), p("sz"))

	target["transform"] = (loc, rot, scale)


def fill_actor_mesh(target, node, iter):
	check_close(node, iter)
	attr = node.attrib
	target["mesh"] = attr["name"]


# example: <material id="0" name="0012_Bisque-G2829c95bb6ed6ea541376445b8e86d92"/>
def fill_actor_material(target, node, iter):
	check_close(node, iter)
	attr = node.attrib
	slot = int(attr["id"])
	material_name = attr["name"]
	target_overrides = target.get("material_overrides", None)
	if not target_overrides:
		target_overrides = target["material_overrides"] = {}
	target_overrides[slot] = material_name
	# TODO: fill actor with material


actor_maps = {
	"Actor": {
		"Transform": fill_transform,
		"tag": ignore,  # just to silence the exporter
		"children": handle_actor_children,
	},
	"ActorMesh": {
		"Transform": fill_transform,
		"tag": ignore,  # just to silence the exporter
		"children": handle_actor_children,
		"mesh": fill_actor_mesh,
		"material": fill_actor_material,
	},
	"Camera": {
		"Transform": fill_transform,
		"children": handle_actor_children,
		# "DepthOfField":    fill_value,
		"SensorWidth": fill_value,
		"SensorAspectRatio": fill_value,
		"FocusDistance": fill_value,
		"FStop": fill_value,
		"FocalLength": fill_value,
	},
	"Light": {
		"Transform": fill_transform,
		"children": handle_actor_children,
		"Color": fill_light_color,
		# "Shape"
		"SourceSize": fill_value,
		"Intensity": fill_value,
		"AttenuationRadius": fill_value,
		"IntensityUnits": fill_value_str,
	},
}


def handle_actor_common(target, node, iter):
	node_type = node.tag
	actor_name = node.attrib["name"]
	actor = {
		"name": actor_name,
		"type": node_type,
		"children": [],
	}
	if node_type == "Light":
		actor["light_type"] = node.attrib["type"]
	filler_map = actor_maps.get(node_type, {})
	for action, child in iter:
		if action == "end":
			break
		handler = filler_map.get(child.tag, unhandled)
		handler(actor, child, iter)
	assert child == node
	assert action == "end"

	log.debug(f"{node_type}: {actor_name}")
	return actor


def fill_mesh_material(mesh, node, iter):
	assert next(iter) == ("end", node)
	id = node.attrib["id"]
	name = node.attrib["name"]
	materials = mesh["materials"]
	num_materials = len(materials)
	id_as_int = int(id)
	materials_lookup = mesh["materials_inv"]
	if id_as_int in materials_lookup:
		idx = materials_lookup[id_as_int]
		materials[idx] = (id, name)
	else:
		materials_lookup[id_as_int] = len(materials)
		materials.append((id, name))


import struct


# don't like this much, maybe we should benchmark specifying sizes directly
def unpack_from_file(length, format, file):
	# length = struct.calcsize(format)
	return struct.unpack(format, file.read(length))


def read_string(buffer):
	string_size = unpack_from_file(4, "<I", buffer)[0]
	string = buffer.read(string_size)
	return string


def fill_mesh_file(mesh, node, iter):
	check_close(node, iter)
	path = node.attrib["path"]
	full_path = "%s/%s" % (import_ctx["dir_path"], path)
	mesh["path"] = full_path


def load_udsmesh_file(mesh):
	full_path = mesh["path"]
	with open(full_path, "rb") as f:
		# this seems to be standard headers for UObject saved files?
		version, file_size = unpack_from_file(8, "<II", f)
		# log.debug(f"version:{version}, size:{file_size}")
		# log.debug(f"at {f.tell()}:")

		file_start = f.tell()
		name = read_string(f)
		# log.debug(f"udsmesh name:{name} version:{version} size:{file_size}")
		# log.debug(f"at {f.tell()}:")

		# this seems to be UDatasmithMesh
		# this would be MeshName and bIsCollisionMesh
		unknown_a = f.read(5)
		assert b"\x00\x01\x00\x00\x00" == unknown_a

		# TArray<DatasmithMeshSourceModel> SourceModels
		str_source_models = read_string(f)
		assert b"SourceModels\x00" == str_source_models

		# Maybe structs start with this (as TArrays may have dynamic data)
		str_struct_property = read_string(f)
		assert b"StructProperty\x00" == str_struct_property

		# Some StructProperty stuff we dont use?
		buf_null_8 = f.read(8)
		assert b"\x00\x00\x00\x00\x00\x00\x00\x00" == buf_null_8

		# The type of data in the array
		str_datasmith_source_model = read_string(f)
		assert b"DatasmithMeshSourceModel\x00" == str_datasmith_source_model

		buf_null_25 = f.read(25)
		assert b"\x00" * 25 == buf_null_25

		# unpack two int32
		mesh_size, mesh_size_2 = unpack_from_file(8, "<II", f)
		assert mesh_size == mesh_size_2

		unknown_b = unpack_from_file(8, "<II", f)
		log.debug(f"unknown_b {unknown_b}")
		# assert unknown_b[0] in (159, 160, 161)
		# assert unknown_b[1] == 0

		mesh_start = f.tell()

		# FRawMeshBulkData starts here, which calls FRawMesh operator<<

		# FRawMesh spec starts here, which seems to be an instance of FByteBulkData
		mesh_version = f.read(4)
		assert b"\x01\x00\x00\x00" == mesh_version  # mesh version
		mesh_lic_version = f.read(4)
		assert b"\x00\x00\x00\x00" == mesh_lic_version  # mesh lic version

		# FaceMaterialIndices
		num_tris = unpack_from_file(4, "<I", f)[0]
		tris_material_indices = np.frombuffer(f.read(num_tris * 4), dtype=np.int32)
		mesh["material_indices"] = tris_material_indices

		# FaceSmoothingMasks
		num_smoothing_groups = unpack_from_file(4, "<I", f)[0]
		assert num_tris == num_smoothing_groups
		smoothing_groups = np.frombuffer(f.read(num_smoothing_groups * 4), dtype=np.int32)
		mesh["smoothing_groups"] = smoothing_groups

		# VertexPositions
		num_vertices = unpack_from_file(4, "<I", f)[0]
		vertices = np.frombuffer(f.read(num_vertices * 3 * 4), dtype=np.float32)
		mesh["vertices"] = vertices

		# wedges / vertexloops are the number of triangle indices
		# WedgeIndices
		num_wedges = unpack_from_file(4, "<I", f)[0]
		triangle_indices = np.frombuffer(f.read(num_wedges * 4), dtype=np.int32)
		mesh["indices"] = triangle_indices

		# WedgeTangentX
		num_tangents_x = unpack_from_file(4, "<I", f)[0]
		assert num_tangents_x == 0

		# WedgeTangentY
		num_tangents_y = unpack_from_file(4, "<I", f)[0]
		assert num_tangents_y == 0

		# WedgeTangentZ
		num_normals = unpack_from_file(4, "<I", f)[0]
		assert num_normals == num_wedges

		normals = np.frombuffer(f.read(num_wedges * 4 * 3), dtype=np.float32)
		normals = normals.reshape((-1, 3))
		mesh["normals"] = normals

		# WedgeTexCoords
		all_uvs = []
		for uv_idx in range(8):
			num_uvs = unpack_from_file(4, "<I", f)[0]
			uvs_base = np.frombuffer(f.read(num_uvs * 4 * 2), dtype=np.float32)
			uvs = (uvs_base.reshape((-1, 2)) * np.array((1, -1))).reshape((-1,))
			all_uvs.append(uvs)

		mesh["uvs"] = all_uvs

		# WedgeColors
		num_vertex_colors = unpack_from_file(4, "<I", f)[0]
		vertex_colors = np.frombuffer(f.read(num_vertex_colors * 4), dtype=np.uint8)
		vertex_colors = vertex_colors.reshape((-1, 4))
		mesh["vertex_colors"] = vertex_colors

		# MaterialIndexToImportIndex
		mat_idx_to_import_idx_num = unpack_from_file(4, "<I", f)[0]
		assert mat_idx_to_import_idx_num == 0

		mesh_end = f.tell()
		mesh_calculated_size = mesh_end - mesh_start
		assert mesh_size == mesh_calculated_size

		# FRawMeshBulkData has a GUID (16 bytes) and bGuidIsHash (4 bytes)
		unknown_c = f.read(20)
		# log.debug(f"unknown_c {unknown_c}")
		# assert b'\x00' * 20 == unknown_c

		file_end = f.tell()
		file_calc_size = file_end - file_start
		assert file_size == file_calc_size


def handle_texture(uscene, node, iter):
	texture_name = node.attrib["name"]
	# <Texture name="Metal_Corrogated_Shiny" texturemode="0" texturefilter="3" textureaddressx="0" textureaddressy="0" rgbcurve="-1.000000" file="APTO V3_Assets/Metal_Corrogated_Shiny.jpg">
	path = node.attrib["file"]
	log.info("loading texture: %s" % path)
	filename_start = path.find("/")
	if filename_start == -1:
		filename_start = path.find("\\")
	if filename_start == -1:
		log.error("unable to find path separators in path: %s" % path)

	filename = path[filename_start + 1 :]
	texture = {"name": texture_name, "filename": filename, "path": path, "mode": node.attrib.get("texturemode")}
	for action, child in iter:
		if action == "end":
			assert child == node
			break
		assert child.tag == "Hash"
		ignore(None, child, iter)
	assert child == node
	assert action == "end"

	"""
	# seemed to be a better idea to index by filename
	# .. why? I think is because blender prefers to keep
	# file extension by default, but when implementing max
	# import, seems that indexing by name may be better
	uscene["textures"][filename] = texture
	"""

	# I now think that it may be better to keep a textures dict
	# that is keyed by index, and another keyed by file name
	# this because skp exporter works that way

	# ADDENDUM: seems that it is possible that many textures have
	# the same texture_name, so I think that the filename should
	# be considered the more unique identifier, and references
	# to this should be preferred
	uscene["textures"][texture_name] = texture
	uscene["textures_by_filename"][filename] = texture


def handle_mastermaterial(uscene, node, iter):
	material_name = node.attrib["name"]  # see also: label
	material = {
		"name": material_name,
		"type": node.tag,
	}
	# <MasterMaterial name="Default-G7a1920d61156abc05a60135aefe8bc67"  label="Default" Type="1" Quality="0" >
	for action, child in iter:
		if action == "end":
			assert child == node
			break
		assert child.tag == "KeyValueProperty"
		fill_keyvalueproperty(material, child, iter)
	assert child == node
	assert action == "end"

	# the important thing to know at this point is that `material` dict
	# has loaded many KeyValuePropertys from the MasterMaterial node
	# such as "Texture" "TextureScale" "Color" "Opacity"

	uscene["materials"][material_name] = material


def handle_material(uscene, node, iter):
	material_name = node.attrib["name"]
	material = {
		"name": material_name,
		"type": node.tag,
	}

	# <Material name="01_-_Default"  label="Default" >
	# <Shader> ... </Shader>
	for action, child in iter:
		if action == "end":
			assert child == node
			break
		else:
			unhandled(None, child, iter)

	assert child == node
	assert action == "end"

	uscene["materials"][material_name] = material


def handle_material_input(inputs_dict, node: ET.Element, iter):
	check_close(node, iter)

	input_id = node.tag  # handles cases where inputse are <0 exp=... />
	if input_id == "Input":  # handles cases where inputs are <Input Name=0 ... />
		input_id = node.attrib["Name"]
	elif input_id == "Coordinates":  # handles cases <Coordinaates ... />
		input_id = "0"

	assert input_id is not None

	input_expression = int(node.attrib["expression"])
	input_socket_idx = int(node.attrib.get("OutputIndex", 0))
	inputs_dict[input_id] = (input_expression, input_socket_idx)


def handle_pbrmaterial_input(material, node, iter):
	mat_inputs = material["inputs"]
	handle_material_input(mat_inputs, node, iter)


def handle_pbrmat_exp_generic(node: ET.Element, iter):
	material_inputs = {}
	material_props = {}
	for action, input_node in iter:
		if action == "end":
			log.info("ending %s" % node.tag)
			assert input_node == node
			break
		node_tag = input_node.tag
		if node_tag == "Input":
			handle_material_input(material_inputs, input_node, iter)
		elif node_tag == "Coordinates":
			handle_material_input(material_inputs, input_node, iter)

		elif node_tag == "KeyValueProperty":
			check_close(input_node, iter)
			attrs = input_node.attrib
			prop_data = (attrs["type"], attrs["val"])
			name = attrs["name"]
			material_props[name] = prop_data
		else:
			log.warning("expression has unrecognized param: %s" % node_tag)

	expression_data = (node.tag, node.attrib, material_inputs, material_props)
	return expression_data


def handle_pbrmat_exp_textureobject(node: ET.Element, iter):
	action, child = next(iter)
	attrib = child.attrib
	# tex_name = child.attrib["name"]
	# tex_val = child.attrib["val"]
	check_close(child, iter)
	check_close(node, iter)
	return ("TextureObject", attrib, {}, {})


def handle_pbrmaterial_expressions(material, node, iter):
	expressions = material["expressions"] = []
	for action, exp_node in iter:
		if action == "end":
			log.info("ending %s" % exp_node.tag)
			assert exp_node == node
			break

		node_type = exp_node.tag

		expression_data = None
		if node_type == "TextureObject":
			expression_data = handle_pbrmat_exp_textureobject(exp_node, iter)
		else:
			expression_data = handle_pbrmat_exp_generic(exp_node, iter)
		expressions.append(expression_data)


def handle_pbrmaterial_value(material, node, iter):
	check_close(node, iter)
	key = node.tag
	value = node.attrib["value"]
	material[key] = value


def handle_pbrmaterial(uscene, node, iter):
	material_name = node.attrib["name"]  # see also: label
	material = {"name": material_name, "type": node.tag, "inputs": {}}
	# <MasterMaterial name="Default-G7a1920d61156abc05a60135aefe8bc67"  label="Default" Type="1" Quality="0" >
	log.info("reading pbrmaterial %s" % material_name)
	for action, child in iter:
		if action == "end":
			assert child == node
			break
		child_tag = child.tag
		filler_map = {
			"Input": handle_pbrmaterial_input,
			"Expressions": handle_pbrmaterial_expressions,
			"OpacityMaskClipValue": unhandled,
			"ShadingModel": handle_pbrmaterial_value,
			"BaseColor": handle_pbrmaterial_input,
			"Roughness": handle_pbrmaterial_input,
			"Metallic": handle_pbrmaterial_input,
			"Normal": handle_pbrmaterial_input,
		}
		handler = filler_map.get(child_tag, unhandled)
		if handler == unhandled:
			log.error("pbrmaterial unhandled tag: %s" % child_tag)

		handler(material, child, iter)

	assert child == node
	assert action == "end"
	uscene["materials"][material_name] = material


def handle_staticmesh(uscene, node, iter):
	mesh_name = node.attrib["name"]  # see also: label
	mesh = {
		"name": mesh_name,
		"materials": [None],
		"materials_inv": {0: 0},
	}

	filler_map = {
		"Material": fill_mesh_material,
		"file": fill_mesh_file,
		# used to hint UE4 on mesh usage to calculate lightmap size
		"Size": ignore,
		# Tells UE4 which mesh UV to use when generating the lightmap UVs
		"LightmapUV": ignore,
		# Tells UE4 that a lightmap UV is already generated at this channel.
		# should be -1 to let UE4 calculate the lightmap
		"LightmapCoordinateIndex": ignore,
		# maybe we can use this hash to skip model importing.
		"Hash": ignore,
	}
	for action, child in iter:
		if action == "end":
			assert child == node
			break
		handler = filler_map.get(child.tag, unhandled)
		handler(mesh, child, iter)
	assert child == node
	assert action == "end"

	load_udsmesh_file(mesh)

	# all data should be loaded by now, so we just add/update the mesh
	bl_mesh = bpy.data.meshes.new(mesh["name"])
	verts, indices = mesh["vertices"], mesh["indices"]
	verts = verts * 0.01

	# flip in Y axis
	verts[1::3] *= -1
	# TODO: tunable to apply Y-axis mirror in mesh or in object

	num_vertices = len(verts) // 3
	bl_mesh.vertices.add(num_vertices)
	num_indices = len(indices)
	bl_mesh.loops.add(num_indices)
	num_tris = num_indices // 3
	bl_mesh.polygons.add(num_tris)

	num_mats = len(mesh["materials"])
	for mat in mesh["materials"]:
		bl_mesh.materials.append(None)

	bl_mesh.vertices.foreach_set("co", verts)

	material_fix_map = mesh["materials_inv"]
	global_indices = mesh["material_indices"]
	fixed_indices = np.empty(num_tris, np.uint8)
	for idx in range(num_tris):
		fixed_indices[idx] = material_fix_map.get(global_indices[idx], 0)
	bl_mesh.polygons.foreach_set("material_index", fixed_indices)

	# failed experiment: to use a generator to feed the functions below
	# we instead need to make an array of 3s
	def loop_total_gen():
		while True:
			yield 3

	bl_mesh.polygons.foreach_set("loop_start", range(0, num_indices, 3))
	bl_mesh.polygons.foreach_set("loop_total", [3] * num_tris)
	bl_mesh.polygons.foreach_set("vertices", indices)

	mesh_uvs = mesh["uvs"]
	for uv_set in mesh_uvs:
		if len(uv_set) == 0:
			continue
		uv_layer = bl_mesh.uv_layers.new()
		uv_layer.data.foreach_set("uv", uv_set)

	bl_mesh.update(calc_edges=True)

	# Seems to work only after bl_mesh.update
	normals = mesh["normals"]
	normals = normals.reshape((-1, 3))
	bl_mesh.normals_split_custom_set(normals)

	mesh["bl_mesh"] = bl_mesh
	log.debug(f"mesh: {mesh['name']}")
	uscene["meshes"][mesh_name] = mesh
	return mesh


def handle_root_tag(uscene, node, iter):
	node_type = node.tag
	if node_type in actor_maps:
		actor = handle_actor_common(None, node, iter)
		uscene["actors"].append(actor)
		return actor

	# non-actors (like meshes, materials, textures)
	root_tags = {
		"StaticMesh": handle_staticmesh,
		"Texture": handle_texture,
		"MasterMaterial": handle_mastermaterial,
		"UEPbrMaterial": handle_pbrmaterial,
		"Material": handle_material,
	}

	handler = root_tags.get(node.tag, unhandled)
	log.debug("handling root tag: %s" % node.tag)
	result = handler(uscene, node, iter)
	return result


def handle_scene(iter, path):
	uscene = {
		"actors": [],
		"materials": {},
		"meshes": {},
		"textures": {},
		"textures_by_filename": {},
		"path": path,
	}

	action, root = next(iter)
	assert root.tag == "DatasmithUnrealScene"
	assert action == "start"
	for action, child in iter:
		if action == "end":
			break
		handle_root_tag(uscene, child, iter)
	assert child == root
	log.info("finished parsing the xml, doing post process")

	log.info("linking textures")
	textures = uscene["textures_by_filename"]
	for texture in textures.values():
		link_texture(uscene, texture)

	log.info("linking materials")
	materials = uscene["materials"]
	for material in materials.values():
		link_material(uscene, material)

	log.info("linking meshes")
	meshes = uscene["meshes"]
	for mesh in meshes.values():
		link_mesh(uscene, mesh)

	log.info("linking actors")
	actors = uscene["actors"]
	num_actors = len(actors)
	processed_actors = 0
	for actor in actors:
		log.info("processing root actor %d/%d: %s" % (processed_actors, num_actors, actor["name"]))
		link_actor(uscene, actor)
		processed_actors += 1

	log.info(f"finished scene! {child}")


def color_from_string(color_string):
	r = 0
	g = 0
	b = 0
	a = 0
	cursor = 0
	cursor_end = 0

	assert color_string[cursor_end : cursor_end + 3] == "(R="
	cursor = cursor_end + 3
	cursor_end = color_string.index(",", cursor)
	r = float(color_string[cursor:cursor_end])

	assert color_string[cursor_end : cursor_end + 3] == ",G="
	cursor = cursor_end + 3
	cursor_end = color_string.index(",", cursor)
	g = float(color_string[cursor:cursor_end])

	assert color_string[cursor_end : cursor_end + 3] == ",B="
	cursor = cursor_end + 3
	cursor_end = color_string.index(",", cursor)
	b = float(color_string[cursor:cursor_end])

	assert color_string[cursor_end : cursor_end + 3] == ",A="
	cursor = cursor_end + 3
	cursor_end = color_string.index(")", cursor)
	a = float(color_string[cursor:cursor_end])

	return (r, g, b, a)


def link_texture(uscene, texture):
	texture_path = texture["path"]
	full_path = "%s/%s" % (uscene["path"], texture_path)

	tex_name = texture["name"]
	log.info("linking texture %s %s" % (tex_name, full_path))
	try:
		image = bpy.data.images.load(full_path, check_existing=True)
		tex_mode = texture["mode"]
		if tex_mode == "1" or tex_mode == "3":
			image.colorspace_settings.name = "Non-Color"
	except Exception:
		log.error("texture not found: %s %s" % (tex_name, full_path))
		image = None
	texture["image"] = image


def pbrmaterial_node_Texture(uscene, exp, node_tree):
	exp_type, exp_attrs, exp_inputs, exp_props = exp
	tex_name = exp_attrs["PathName"]
	texture = uscene["textures"].get(tex_name)
	image = None
	if texture:
		image = texture.get("image")
	else:
		log.warning("texture %s referenced from material not found")
	node = node_tree.nodes.new("ShaderNodeTexImage")
	node.image = image

	# ue maps 0:rgb 1:r 2:g 3:b 4:a 5:rgba
	# TODO: remap r/g/b correctly
	outputs = {
		0: node.outputs[0],
		4: node.outputs[1],
		5: node.outputs[0],
	}

	return {"node": node, "outputs": outputs}


def pbrmaterial_node_Color(uscene, exp, node_tree):
	exp_type, exp_attrs, exp_inputs, exp_props = exp
	color = color_from_string(exp_attrs["constant"])
	node = node_tree.nodes.new("ShaderNodeRGB")
	node.outputs[0].default_value = color
	return {"node": node}


def pbrmaterial_node_Desaturation(uscene, exp, node_tree):
	exp_type, exp_attrs, exp_inputs, exp_props = exp
	nodes = node_tree.nodes

	node_in_color = nodes.new("NodeReroute")
	sockets = {}
	sockets["0"] = node_in_color.inputs[0]

	node_rgb_to_bw = nodes.new("ShaderNodeRGBToBW")
	node_tree.links.new(node_in_color.outputs[0], node_rgb_to_bw.inputs["Color"])

	node = node_lerp = nodes.new("ShaderNodeMixRGB")
	node_tree.links.new(node_in_color.outputs[0], node_lerp.inputs["Color1"])
	node_tree.links.new(node_rgb_to_bw.outputs[0], node_lerp.inputs["Color2"])

	sockets["1"] = node_lerp.inputs["Fac"]
	node_lerp.inputs["Fac"].default_value = 1.0
	return {"node": node, "inputs": sockets}


def pbrmaterial_node_Scalar(uscene, exp, node_tree):
	exp_type, exp_attrs, exp_inputs, exp_props = exp
	node = node_tree.nodes.new("ShaderNodeValue")
	node.outputs[0].default_value = float(exp_attrs["constant"])
	return {"node": node}


def pbrmaterial_node_Add(uscene, exp, node_tree):
	node = node_tree.nodes.new("ShaderNodeVectorMath")
	node.operation = "ADD"
	return {
		"node": node,
		"inputs": {
			"0": node.inputs[0],
			"1": node.inputs[1],
		},
	}


def pbrmaterial_node_Multiply(uscene, exp, node_tree):
	node = node_tree.nodes.new("ShaderNodeVectorMath")
	node.operation = "MULTIPLY"
	return {
		"node": node,
		"inputs": {
			"0": node.inputs[0],
			"1": node.inputs[1],
		},
	}


def pbrmaterial_node_Power(uscene, exp, node_tree):
	exp_type, exp_attrs, exp_inputs, exp_props = exp
	node = node_tree.nodes.new("ShaderNodeMath")
	node.operation = "POWER"
	default_exponent = exp_props.get("ConstExponent", None)
	if default_exponent:
		prop_type, prop_value_string = default_exponent
		assert prop_type == "Float"
		prop_value = float(prop_value_string)
		node.inputs[1].default_value = prop_value

	return {
		"node": node,
		"inputs": {
			"0": node.inputs[0],
			"1": node.inputs[1],
		},
	}


def pbrmaterial_node_VertexNormalWS(uscene, exp, node_tree):
	node = node_tree.nodes.new("ShaderNodeNewGeometry")
	return {
		"node": node,
		"outputs": {
			0: node.outputs["Normal"],
		},
	}


def pbrmaterial_node_LinearInterpolate(uscene, exp, node_tree):
	node = node_tree.nodes.new("ShaderNodeMixRGB")
	return {
		"node": node,
		"inputs": {
			"0": node.inputs["Color1"],
			"1": node.inputs["Color2"],
			"2": node.inputs["Fac"],
		},
	}


def pbrmaterial_node_OneMinus(uscene, exp, node_tree):
	node = node_tree.nodes.new("ShaderNodeInvert")
	return {
		"node": node,
		"inputs": {
			"0": node.inputs["Color"],
		},
	}


def pbrmaterial_node_AppendVector(uscene, exp, node_tree):
	print("found appendvector:", exp)
	node = node_tree.nodes.new("NodeReroute")
	return {
		"node": node,
	}


def pbrmaterial_node_FunctionCall(uscene, exp, node_tree):
	print("found functioncall:", exp)
	function = exp[1]["Function"]

	node = None
	inputs = None
	if function == "/DatasmithBlenderContent/MaterialFunctions/RGB_To_BW":
		node = node_tree.nodes.new("ShaderNodeRGBToBW")
	elif function == "/DatasmithBlenderContent/MaterialFunctions/NormalStrength":
		node = node_tree.nodes.new("ShaderNodeNormalMap")
		inputs = {
			"0": node.inputs["Strength"],
			"1": node.inputs["Color"],
		}
	else:
		node = node_tree.nodes.new("NodeReroute")

	if inputs is None:
		inputs = {"0": node.inputs[0]}

	return {"node": node, "inputs": inputs}


def pbrmaterial_node_ComponentMask(uscene, exp, node_tree):
	print("found componentmask:", exp)
	node = node_tree.nodes.new("NodeReroute")
	return {
		"node": node,
	}


def pbrmaterial_node_Fresnel(uscene, exp, node_tree):
	node = node_tree.nodes.new("ShaderNodeFresnel")
	# in UE4 inputs are:
	# 0: ExponentIn
	# 0: BaseReflectFractionIn
	# 0: Normal

	return {
		"node": node,
		"inputs": {
			"0": node.inputs["IOR"],
			"2": node.inputs["Normal"],
		},
	}


def pbrmaterial_node_TextureCoordinate(uscene, exp, node_tree):
	node = node_tree.nodes.new("ShaderNodeUVMap")
	return {"node": node}


pbrmaterial_node_functions = {
	"Texture": pbrmaterial_node_Texture,
	"Color": pbrmaterial_node_Color,
	"Desaturation": pbrmaterial_node_Desaturation,
	"Scalar": pbrmaterial_node_Scalar,
	"Add": pbrmaterial_node_Add,
	"Multiply": pbrmaterial_node_Multiply,
	"Power": pbrmaterial_node_Power,
	"VertexNormalWS": pbrmaterial_node_VertexNormalWS,
	"LinearInterpolate": pbrmaterial_node_LinearInterpolate,
	"OneMinus": pbrmaterial_node_OneMinus,
	"Fresnel": pbrmaterial_node_Fresnel,
	"TextureCoordinate": pbrmaterial_node_TextureCoordinate,
	"AppendVector": pbrmaterial_node_AppendVector,
	"ComponentMask": pbrmaterial_node_ComponentMask,
	"FunctionCall": pbrmaterial_node_FunctionCall,
}


def link_pbr_material(uscene, material):
	log.info("processing pbr material %s" % material["name"])

	expressions = material["expressions"]
	bf_nodes = material["bf_nodes"] = []
	inputs = material["inputs"]
	log.info("  expressions: %s", expressions)
	log.info("  inputs: %s", inputs)
	bl_mat = material["bl_mat"]
	bl_mat.use_nodes = True
	node_tree = bl_mat.node_tree

	for exp in expressions:
		exp_type, exp_attrs, exp_inputs, exp_props = exp
		node = None
		log.debug("  creating node for expression '%s'", exp)

		handler = pbrmaterial_node_functions.get(exp_type)
		bf_node = None
		if handler:
			data = handler(uscene, exp, node_tree)
			bf_node = (data["node"], data.get("inputs"), data.get("outputs"))
		else:
			log.error("  exp_type not supported: %s" % exp_type)
			# leave bf_node as None

		bf_nodes.append(bf_node)

		name = exp_attrs.get("Name", None)
		if name and bf_node:
			node = bf_node[0]
			node.name = name
			node.label = name

	log.info("linking expressions pbr material %s" % material["name"])

	for exp_idx, exp in enumerate(expressions):
		# everything prefixed with "exp" is what comes from datasmith file
		exp_type, exp_attrs, exp_inputs, exp_props = exp

		target_node = bf_nodes[exp_idx]
		# only create links if the exp_type was valid, otherwise skip
		# this assumes that expressions are ordered and later expressions
		# expect previous ones to be correctly processed already
		if target_node:
			node, node_input_map, _ = target_node
			if node_input_map:
				log.debug("  linking expression '%s' node: %s", exp_type, target_node)

				for exp_input_id, exp_from_socket in exp_inputs.items():
					log.debug("    input %s expr %s", exp_input_id, exp_from_socket)
					node_idx, socket_idx = exp_from_socket
					origin_node = bf_nodes[node_idx]
					incoming_socket = None
					if origin_node:
						incoming_node, _, incoming_out_sockets = origin_node
						log.debug("    idx %d data %s" % (socket_idx, incoming_node))
						if incoming_out_sockets:
							incoming_socket = incoming_out_sockets.get(socket_idx, None)
						if incoming_socket is None:
							incoming_socket = incoming_node.outputs[socket_idx]

					if incoming_socket:
						input_socket = node_input_map.get(exp_input_id)
						# not guaranteed to exist:
						# example: xml expression has 3 inputs but the node we spawned only has one
						# common if a node isn't implemented, we use reroute
						if input_socket:
							node_tree.links.new(incoming_socket, input_socket)

	log.info("linking outputs pbr material %s" % material["name"])

	shading_model = material.get("ShadingModel")
	if shading_model:
		if shading_model == "ThinTranslucent":
			bl_mat.blend_method = "BLEND"
		else:
			log.error("unrecognized ShadingModel: %s" % shading_model)

	# after dealing with expressions, set inputs to master node
	principled = node_tree.nodes["Principled BSDF"]
	material_inputs = material["inputs"]
	for input_id, input_nodepath in material_inputs.items():
		input_id_map = {
			"BaseColor": "Base Color",
			"Roughness": "Roughness",
			"Specular": "Specular",
			"Metallic": "Metallic",
			"Normal": "Normal",
		}
		target_input_name = input_id_map.get(input_id, None)
		if target_input_name:
			node_idx, socket_idx = input_nodepath
			input_socket = principled.inputs[target_input_name]

			if True:
				origin_node = bf_nodes[node_idx]
				incoming_socket = None
				if origin_node:
					incoming_node, _, incoming_out_sockets = origin_node
					log.info("idx %d data %s" % (socket_idx, incoming_node))
					if incoming_out_sockets:
						incoming_socket = incoming_out_sockets.get(socket_idx, None)
					if incoming_socket is None:
						incoming_socket = incoming_node.outputs[socket_idx]

				if incoming_socket:
					# input_socket = node_input_map.get(exp_input_id)
					node_tree.links.new(incoming_socket, input_socket)

			# from_socket = from_node.outputs[from_socket_idx]
			# node_tree.links.new(from_socket, input_socket)


def link_material(uscene, material):
	material_name = material["name"]
	log.info("linking material: %s" % material_name)
	bl_mat = bpy.data.materials.new(material_name)
	material["bl_mat"] = bl_mat

	if material["type"] == "UEPbrMaterial":
		link_pbr_material(uscene, material)
	elif material["type"] == "MasterMaterial":
		# Color and opacity setup from the material props
		color = (1, 1, 1, 1)
		color_prop = material.get("Color")
		if color_prop:
			color = color_from_string(color_prop)

		blend_method = "OPAQUE"
		opacity_prop = material.get("Opacity")
		if opacity_prop:
			color = color[0:3] + (float(opacity_prop),)
			blend_method = "BLEND"

		bl_mat.diffuse_color = color
		bl_mat.blend_method = blend_method

		# use nodes material if it has a texture property
		texture_prop = material.get("Texture")
		if texture_prop:
			texture = uscene["textures_by_filename"][texture_prop]
			log.error(repr(texture))
			image = texture["image"]
			bl_mat.use_nodes = True
			node_tree = bl_mat.node_tree
			nodes = node_tree.nodes
			principled = nodes["Principled BSDF"]
			image_node = nodes.new("ShaderNodeTexImage")
			node_tree.links.new(image_node.outputs["Color"], principled.inputs["Base Color"])
			image_node.image = image


def link_mesh(uscene, mesh):
	mesh_name = mesh["name"]
	log.info("linking mesh:%s" % mesh_name)
	bl_mesh = mesh["bl_mesh"]
	mesh_mats = bl_mesh.materials
	material_ids = mesh["materials"]
	scene_mats = uscene["materials"]
	for idx, mat_data in enumerate(material_ids):
		if mat_data:
			mat_id, mat_name = mat_data
			log.debug("mesh %s mat %s" % (mesh_name, mat_name))
			mat_data2 = scene_mats.get(mat_name)
			if mat_data2:
				material = mat_data2["bl_mat"]
				mesh_mats[idx] = material


datasmith_transform_matrix = Matrix.Scale(0.01, 4)
datasmith_transform_matrix[1][1] *= -1.0

ue_transform_mat = datasmith_transform_matrix
ue_transform_mat_inv = ue_transform_mat.inverted()

# used for lights and cameras, whose forward is (0, 0, -1) and its right is (1, 0, 0)
matrix_forward = Matrix(
	(
		(0, 1, 0, 0),
		(0, 0, -1, 0),
		(-1, 0, 0, 0),
		(0, 0, 0, 1),
	)
)

matrix_forward_inv = matrix_forward.inverted()


def link_actor(uscene, actor, in_parent=None):
	actor_name = actor["name"]
	log.debug("linking actor %s" % actor_name)
	data = None
	actor_type = actor["type"]
	if actor_type == "ActorMesh":
		mesh_name = actor["mesh"]
		data = uscene["meshes"][mesh_name]["bl_mesh"]
	elif actor_type == "Light":
		light_type_map = {
			"PointLight": "POINT",
			"AreaLight": "AREA",
			"DirectionalLight": "SUN",
			"SpotLight": "SPOT",
		}
		light_type = light_type_map[actor["light_type"]]
		data = bpy.data.lights.new(actor_name, light_type)

		data.color = actor["color"]
		data.energy = 12.5 * float(actor["Intensity"])

	elif actor_type == "Camera":
		data = bpy.data.cameras.new(actor_name)

	bl_obj = bpy.data.objects.new(actor_name, data)
	bl_obj.parent = in_parent

	# import pdb; pdb.set_trace()

	loc, rot, scale = actor["transform"]
	# log.debug(f"postprocessing {actor_name} {transform}")
	mat_loc = Matrix.Translation(np.array(loc))
	mat_rot = Quaternion(rot).to_matrix()
	mat_sca = Matrix.Diagonal(scale)
	mat_out = mat_loc.to_4x4() @ mat_rot.to_4x4() @ mat_sca.to_4x4()

	# TODO: be able to mirror Y-axis from the mesh, so we don't end up with
	# a bunch of -1s in scale and a 180 rotation
	# mat_out = datasmith_transform_matrix @ mat_out
	# mat_out = mat_out @ matrix_datasmith.inverted()
	mat_out = ue_transform_mat @ mat_out @ ue_transform_mat_inv

	if actor_type == "Camera" or actor_type == "Light":
		mat_out = mat_out @ matrix_forward_inv

	bl_obj.matrix_world = mat_out
	master_collection = bpy.data.collections[0]
	master_collection.objects.link(bl_obj)

	children = actor["children"]
	for child in children:
		link_actor(uscene, child, bl_obj)

	overrides = actor.get("material_overrides", None)
	if overrides:
		for slot_idx, mat_name in overrides.items():
			slot = bl_obj.material_slots[slot_idx]
			slot.link = "OBJECT"
			mat = uscene["materials"][mat_name]
			slot.material = mat["bl_mat"]


import_ctx = {}


def load(context, kwargs, file_path):
	start_time = time.monotonic()
	log.info(f"loading file: {file_path}")
	log.info(f"args: {kwargs}")
	dir_path = path.dirname(file_path)
	import_ctx["dir_path"] = dir_path
	indent = ""
	with open(file_path, encoding="utf-8") as f:
		iter = ET.iterparse(f, events=("start", "end"))
		handle_scene(iter, dir_path)

	end_time = time.monotonic()
	total_time = end_time - start_time

	log.info(f"import finished in {total_time} seconds")


def load_wrapper(*, context, filepath, **kwargs):
	handler = None
	use_logging = bool(kwargs["use_logging"])

	if use_logging:
		log_path = filepath + ".log"
		handler = logging.FileHandler(log_path, mode="w")

		formatter = logging.Formatter(fmt="%(asctime)s.%(msecs)03d %(levelname)-8s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
		handler.setFormatter(formatter)
		log.addHandler(handler)

		logging_level = {
			"NEVER": logging.CRITICAL,
			"ERROR": logging.ERROR,
			"WARN": logging.WARNING,
			"INFO": logging.INFO,
			"DEBUG": logging.DEBUG,
		}[kwargs["log_level"]]

		# logging_level = logging.DEBUG
		log.setLevel(logging_level)
		handler.setLevel(logging_level)
		logging.basicConfig(level=logging_level)
	try:
		from os import path

		basepath, ext = path.splitext(filepath)

		log.info("Starting Datasmith import")
		load(context, kwargs, filepath)
		log.info("Finished Datasmith import")

	except Exception as error:
		log.error("Datasmith export error:")
		log.error(error)
		raise

	finally:
		if use_logging:
			log.info("Finished logging to path:" + log_path)
			handler.close()
			log.removeHandler(handler)

	return {"FINISHED"}
