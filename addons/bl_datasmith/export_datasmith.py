# Datasmith exporter for Blender
# Copyright 2018-2022 Andrés Botero

import logging
import math
import numpy as np
import os
import shutil
import struct
import time
from hashlib import sha1
from os import path

import bpy
import bmesh
from mathutils import Matrix

from .data_types import Node, sanitize_name
from .export_material import collect_all_materials, get_texture_name


log = logging.getLogger("bl_datasmith")


def calc_hash(image_path):
	result = sha1()
	with open(image_path, "rb") as f:
		buf = f.read(524288)  # read 512KB
		while len(buf) > 0:
			result.update(buf)
			buf = f.read(524288)
	return result.hexdigest()


matrix_datasmith = Matrix.Scale(100, 4)
matrix_datasmith[1][1] *= -1.0


# used for lights and cameras, whose forward is (0, 0, -1) and its right is (1, 0, 0)
matrix_forward = Matrix(
	(
		(0, 1, 0, 0),
		(0, 0, -1, 0),
		(-1, 0, 0, 0),
		(0, 0, 0, 1),
	)
)


log = logging.getLogger("bl_datasmith")


def write_array_data(io, data):
	assert isinstance(data, np.ndarray)
	io.write(struct.pack("<I", len(data)))
	data.tofile(io)


def write_data(io, data_struct, *args):
	data_struct = "<" + data_struct
	packed = struct.pack(data_struct, *args)
	io.write(packed)


def write_null(io, num_bytes):
	io.write(b"\0" * num_bytes)


def write_string(io, string):
	string_bytes = string.encode("utf-8") + b"\0"
	length = len(string_bytes)
	io.write(struct.pack("<I", length))
	io.write(string_bytes)


def mesh_save(mesh, basedir, folder_name):
	mesh_name, materials, data = mesh
	log.debug("saving mesh:" + mesh_name)

	relative_path = path.join(folder_name, mesh_name + ".udsmesh")
	abs_path = path.join(basedir, relative_path)
	with open(abs_path, "wb") as file:
		write_to_path(mesh_name, data, file)
	mesh_hash = calc_hash(abs_path)

	n = Node("StaticMesh")
	name, materials, _ = mesh

	n["label"] = name
	n["name"] = name

	for idx, m in enumerate(materials):
		n.push(Node("Material", {"id": idx, "name": m}))
	fixed_path = relative_path.replace("\\", "/")
	n.push(Node("file", {"path": fixed_path}))
	n.push(Node("LightmapUV", {"value": "-1"}))
	n.push(Node("Hash", {"value": mesh_hash}))
	return n


# check UE Engine/Source/Developer/Rawmesh for data structure
def write_to_path(name, data, file):
	file.write(b"\x01\x00\x00\x00\xfd\x04\x00\x00")

	file_start = file.tell()
	write_string(file, name)
	file.write(b"\x00\x01\x00\x00\x00")
	write_string(file, "SourceModels")
	write_string(file, "StructProperty")
	write_null(file, 8)

	write_string(file, "DatasmithMeshSourceModel")

	write_null(file, 25)

	size_loc = file.tell()  # here we have to write the rawmesh size two times
	write_data(file, "II", 0, 0)  # just some placeholder data, to rewrite at the end

	file.write(b"\x7d\x00\x00\x00\x00\x00\x00\x00")  # 125 and zero

	# here starts rawmesh
	mesh_start = file.tell()
	file.write(b"\x01\x00\x00\x00")  # raw mesh version
	file.write(b"\x00\x00\x00\x00")  # raw mesh lic  version

	material_slots, smoothing_groups, positions, indices, out_normals, uvs, out_vertex_colors = data

	# these loops are per triangle
	write_array_data(file, material_slots)
	write_array_data(file, smoothing_groups)

	# per vertex
	write_array_data(file, positions)  # VertexPositions

	# per vertexloop
	write_array_data(file, indices)  # WedgeIndices

	write_null(file, 4)  # WedgeTangentX
	write_null(file, 4)  # WedgeTangentY
	write_array_data(file, out_normals)  # WedgeTangentZ

	num_uvs = len(uvs)
	for idx in range(num_uvs):
		write_array_data(file, uvs[idx])  # WedgeTexCoords[0]

	num_empty_uvs = 8 - num_uvs
	write_null(file, 4 * num_empty_uvs)  # WedgeTexCoords[n..7]
	write_array_data(file, out_vertex_colors)  # WedgeColors

	write_null(file, 4)  # MaterialIndexToImportIndex

	# here ends rawmesh
	mesh_end = file.tell()

	write_null(file, 16)
	write_null(file, 4)
	file_end = file.tell()

	mesh_size = mesh_end - mesh_start
	file.seek(size_loc)
	write_data(file, "II", mesh_size, mesh_size)

	file.seek(0)
	write_data(file, "II", 1, file_end - file_start)


def collect_mesh(name, bl_mesh):
	materials = None
	if len(bl_mesh.materials) == 0:
		materials = ["DefaultMaterial"]
	else:
		materials = [sanitize_name(mat.name) if mat else "DefaultMaterial" for mat in bl_mesh.materials]

	mesh_data = make_mesh_data(bl_mesh)

	meshes = datasmith_context["meshes"]
	meshes[name] = (name, materials, mesh_data)


def make_mesh_data(bl_mesh):
	# create copy to triangulate
	m = bl_mesh.copy()

	# triangulate with bmesh api
	bm = bmesh.new()
	bm.from_mesh(m)
	bmesh.ops.triangulate(bm, faces=bm.faces[:])

	bm.loops.layers.uv.verify()  # this ensures that an UV layer exists

	bm.to_mesh(m)
	bm.free()

	m.transform(matrix_datasmith)

	vertices = m.vertices
	num_vertices = len(vertices)

	vertices_array = np.empty(num_vertices * 3, np.float32)
	vertices.foreach_get("co", vertices_array)

	positions = vertices_array.reshape(-1, 3)

	# not sure if this is the best way to read normals
	m.calc_loop_triangles()
	loop_triangles = m.loop_triangles
	num_triangles = len(loop_triangles)
	num_loops = num_triangles * 3

	indices = np.empty(num_loops, np.uint32)
	loop_triangles.foreach_get("vertices", indices)

	material_slots = np.empty(num_triangles, np.uint32)
	loop_triangles.foreach_get("material_index", material_slots)

	normals = np.empty(num_loops * 3, np.float32)
	loop_triangles.foreach_get("split_normals", normals)
	normals = normals.reshape((-1, 3))
	normals *= -1

	# in case vert has invalid normals, put some dummy data so UE doesn't try to recalculate
	normals_drift = np.linalg.norm(normals, axis=1) - 1
	normals_faulty = np.abs(normals_drift) > 0.008
	normals[normals_faulty] = (0, 0, 1)
	out_normals = np.ascontiguousarray(normals, "<f4")

	# finish inline mesh_copy_triangulate
	# smoothing_groups = m.calc_smooth_groups()[0]
	# smoothing_groups = np.array(smoothing_groups, np.uint32)
	smoothing_groups = np.zeros(num_triangles, np.uint32)

	uvs = []
	num_uvs = min(8, len(m.uv_layers))
	active_uv = 0
	for idx in range(num_uvs):
		if m.uv_layers[idx].active_render:
			active_uv = idx
	for idx in range(num_uvs):
		uv_idx = idx  # swap active_render UV with channel 0
		if uv_idx == 0:
			uv_idx = active_uv
		elif uv_idx == active_uv:
			uv_idx = 0

		uv_data = m.uv_layers[uv_idx].data
		uv_loops = np.empty(len(uv_data) * 2, np.float32)
		uv_data.foreach_get("uv", uv_loops)
		uv_loops = uv_loops.reshape((-1, 2))

		uv_channel = uv_loops
		uv_channel[:, 1] = 1 - uv_channel[:, 1]
		uvs.append(uv_channel)

	out_vertex_colors = None
	if m.vertex_colors:
		vertex_colors = np.empty(num_loops * 4)
		m.vertex_colors[0].data.foreach_get("color", vertex_colors)
		vertex_colors *= 255
		vertex_colors = vertex_colors.reshape((-1, 4))
		vertex_colors[:, [0, 2]] = vertex_colors[:, [2, 0]]
		out_vertex_colors = vertex_colors.astype(np.uint8)
	else:
		out_vertex_colors = np.zeros(0)
	bpy.data.meshes.remove(m)

	return (material_slots, smoothing_groups, positions, indices, out_normals, uvs, out_vertex_colors)


def collect_object_transform(bl_obj, instance_matrix=None):
	mat_basis = instance_matrix or bl_obj.matrix_world
	obj_mat = matrix_datasmith @ mat_basis @ matrix_datasmith.inverted()

	if bl_obj.type in "CAMERA" or bl_obj.type == "LIGHT":
		obj_mat = obj_mat @ matrix_forward
	elif bl_obj.type == "LIGHT_PROBE":
		bl_probe = bl_obj.data
		if bl_probe.type == "PLANAR":
			obj_mat = obj_mat @ Matrix.Scale(0.05, 4)
		elif bl_probe.type == "CUBEMAP":
			if bl_probe.influence_type == "BOX":
				size = bl_probe.influence_distance * 100
				obj_mat = obj_mat @ Matrix.Scale(size, 4)

	obj_mat.freeze()  # TODO: check if this is needed
	return obj_mat


def collect_environment(world, tex_dict):
	if not world:
		return
	if not world.use_nodes:
		return

	log.info("Collecting environment")
	nodes = world.node_tree
	output = nodes.get_output_node("EEVEE") or nodes.get_output_node("ALL") or nodes.get_output_node("CYCLES")
	background_node = output.inputs["Surface"].links[0].from_node
	while background_node.type == "REROUTE":
		background_node = background_node.inputs[0].links[0].from_node

	if "Color" not in background_node.inputs:
		return
	if not background_node.inputs["Color"].links:
		return
	source_node = background_node.inputs["Color"].links[0].from_node
	if source_node.type != "TEX_ENVIRONMENT":
		log.info("Background texture is " + source_node.type)
		return

	log.info("found environment, collecting...")
	image = source_node.image

	tex_name = get_texture_name(tex_dict, image)

	tex_node = Node("Texture", {"tex": tex_name})

	n2 = Node(
		"Environment",
		{
			"name": "world_environment_lighting",
			"label": "world_environment_lighting",
		},
	)
	n2.push(tex_node)
	n2.push(Node("Illuminate", {"enabled": "1"}))
	n = Node(
		"Environment",
		{
			"name": "world_environment_background",
			"label": "world_environment_background",
		},
	)
	n.push(tex_node)
	n.push(Node("Illuminate", {"enabled": "0"}))

	return [n, n2]


def get_file_header():
	n = Node("DatasmithUnrealScene")

	from . import bl_info

	plugin_version = bl_info["version"]
	plugin_version_string = "%s.%s.%s" % plugin_version
	n.push(Node("Version", children=[plugin_version_string]))
	n.push(Node("SDKVersion", children=["4.24E0"]))
	n.push(Node("Host", children=["Blender"]))

	blender_version = bpy.app.version_string
	n.push(
		Node(
			"Application",
			{
				"Vendor": "Blender Foundation",
				"ProductName": "Blender",
				"ProductVersion": blender_version,
			},
		)
	)

	import os
	import platform

	os_name = "%s %s" % (platform.system(), platform.release())
	user_name = os.getlogin()

	n.push(Node("User", {"ID": user_name, "OS": os_name}))
	return n


TEXTURE_MODE_DIFFUSE = "0"
TEXTURE_MODE_SPECULAR = "1"
TEXTURE_MODE_NORMAL = "2"
TEXTURE_MODE_NORMAL_GREEN_INV = "3"
TEXTURE_MODE_DISPLACE = "4"
TEXTURE_MODE_OTHER = "5"
TEXTURE_MODE_BUMP = "6"  # this converts textures to normal maps automatically


# saves image, and generates node with image description to add to export
def save_texture(texture, basedir, folder_name, skip_textures):
	name, image, img_type = texture

	log.info("writing texture:" + name)

	ext = ".png"
	if image.file_format == "JPEG":
		ext = ".jpg"
	elif image.file_format == "HDR":
		ext = ".hdr"
	elif image.file_format == "OPEN_EXR":
		ext = ".exr"
	elif image.file_format == "TARGA" or image.file_format == "TARGA_RAW":
		ext = ".tga"

	safe_name = sanitize_name(name) + ext
	image_path = path.join(basedir, folder_name, safe_name)
	skip_image = skip_textures and not path.exists(image_path)

	# fix for invalid images, like one in mr_elephant sample.
	valid_image = image.channels != 0
	if valid_image and not skip_image:
		source_path = image.filepath_from_user()

		if image.packed_file:
			with open(image_path, "wb") as f:
				f.write(image.packed_file.data)
		elif source_path and source_path != image_path:
			shutil.copyfile(source_path, image_path)
		else:
			image.filepath_raw = image_path
			image.save()
			if source_path:
				image.filepath_raw = source_path

	n = Node("Texture")
	n["name"] = name
	n["file"] = path.join(folder_name, safe_name)  # .replace("\\", "/")
	n["rgbcurve"] = 0.0
	n["srgb"] = "1"  # this parameter is only read on 4.25 onwards

	n["texturemode"] = TEXTURE_MODE_DIFFUSE
	if image.file_format == "HDR":
		n["texturemode"] = TEXTURE_MODE_OTHER
		n["rgbcurve"] = "1.000000"
	elif img_type == "NORMAL":
		n["texturemode"] = TEXTURE_MODE_NORMAL_GREEN_INV
		n["srgb"] = "2"  # only read on 4.25 onwards, but we can still write it
	elif image.colorspace_settings.is_data:
		n["texturemode"] = TEXTURE_MODE_SPECULAR
		n["srgb"] = "2"  # only read on 4.25 onwards, but we can still write it

	n["texturefilter"] = "3"
	if valid_image:
		img_hash = calc_hash(image_path)
		n.push(Node("Hash", {"value": img_hash}))
	return n


# send instance.original to this function
# if this returns none, it didn't convert to geometry
def get_mesh_name(bl_obj_inst):
	bl_obj = bl_obj_inst.original

	bl_mesh_name = bl_obj.data.name
	if bl_obj.modifiers:
		bl_mesh_name = "%s_%s" % (bl_obj.name, bl_mesh_name)

	library = bl_obj.data.library
	if library:
		libraries_dict = datasmith_context["libraries"]
		prefix = libraries_dict.get(library)

		if prefix is None:
			lib_filename = bpy.path.basename(library.filepath)
			lib_clean_name = bpy.path.clean_name(lib_filename)
			base_prefix = lib_clean_name.strip("_")
			if base_prefix.endswith("_blend"):
				base_prefix = base_prefix[:-5]  # leave the underscore

			prefix = base_prefix
			try_count = 0

			# just to reaaally make sure there are no collisions
			libraries_prefixes = libraries_dict.values()
			while prefix in libraries_prefixes:
				try_count += 1
				prefix = "%s%d_" % (base_prefix, try_count)

			libraries_dict[library] = prefix

		bl_mesh_name = prefix + bl_mesh_name

	bl_mesh_name = sanitize_name(bl_mesh_name)

	# if the mesh has been processed already, return the name
	# when we return none, the outer scope will just not make it a MeshActor
	meshes_per_original = datasmith_context["meshes_per_original"]
	MESH_STATUS_CREATED = 1
	MESH_STATUS_DOESNT_EXIST = 2
	match meshes_per_original.get(bl_mesh_name):
		case 1:
			return bl_mesh_name
		case 2:
			return None

	bl_mesh = bl_obj_inst.to_mesh()
	if not bl_mesh or len(bl_mesh.polygons) == 0:
		meshes_per_original[bl_mesh_name] = MESH_STATUS_DOESNT_EXIST
		bl_obj_inst.to_mesh_clear()
		return None

	meshes_per_original[bl_mesh_name] = MESH_STATUS_CREATED
	log.info("creating mesh:%s" % bl_mesh_name)

	collect_mesh(bl_mesh_name, bl_mesh)

	material_list = datasmith_context["materials"]
	if len(bl_obj.material_slots) == 0:
		material_list.append((None, bl_obj))
	else:
		for slot in bl_obj.material_slots:
			material_list.append((slot.material, bl_obj))
	bl_obj_inst.to_mesh_clear()

	return bl_mesh_name


def fill_obj_mesh(obj_dict, bl_obj):
	mesh_name = get_mesh_name(bl_obj)
	# mesh_name can be none, in that case we won't ever convert to actormesh
	if mesh_name:
		obj_dict["type"] = "ActorMesh"
		fields = obj_dict["fields"]

		fields.append('\t<mesh name="%s"/>\n' % mesh_name)

		for idx, slot in enumerate(bl_obj.material_slots):
			if slot.link == "OBJECT":
				safe_name = sanitize_name(slot.material.name)
				material_list = datasmith_context["materials"]
				material_list.append((slot.material, bl_obj))
				fields.append('\t<material id="%i" name="%s"/>\n' % (idx, safe_name))


def fill_obj_light(obj_dict, target):
	obj_dict["type"] = "Light"

	fields = obj_dict["fields"]
	attribs = obj_dict["attrib"]

	bl_light = target.data
	light_intensity = bl_light.energy
	light_attenuation_radius = 100 * math.sqrt(bl_light.energy)
	light_color = bl_light.color
	light_intensity_units = "Lumens"  # can also be 'Candelas' or 'Unitless'
	light_use_custom_distance = bl_light.use_custom_distance

	light_type = "PointLight"
	if bl_light.type == "SUN":
		light_type = "DirectionalLight"
		light_use_custom_distance = False
		# light_intensity = bl_light.energy # suns are in lux

	elif bl_light.type == "SPOT":
		light_type = "SpotLight"
		outer_cone_angle = bl_light.spot_size * 180 / (2 * math.pi)
		inner_cone_angle = outer_cone_angle * (1 - bl_light.spot_blend)
		if inner_cone_angle < 0.0001:
			inner_cone_angle = 0.0001
		fields.append('\t<InnerConeAngle value="%f"/>\n' % inner_cone_angle)
		fields.append('\t<OuterConeAngle value="%f"/>\n' % outer_cone_angle)

		spot_use_candelas = False  # TODO: test this thoroughly
		if spot_use_candelas:
			light_intensity_units = "Candelas"
			light_intensity = bl_light.energy * 0.08  # came up with this constant by brute force
			# blender watts unit match ue4 lumens unit, but in spot lights the brightness
			# changes with the spot angle when using lumens while candelas do not.

	elif bl_light.type == "AREA":
		light_type = "AreaLight"

		size_w = size_h = bl_light.size
		if bl_light.shape == "RECTANGLE" or bl_light.shape == "ELLIPSE":
			size_h = bl_light.size_y

		size_w *= 100
		size_h *= 100
		shape_size = (size_w, size_h)
		fields.append('\t<Shape type="None" width="%f" length="%f" LightType="Rect" />\n' % shape_size)

	attribs.append(' type="%s"' % light_type)
	attribs.append(' enabled="1"')

	if light_use_custom_distance:
		light_attenuation_radius = 100 * bl_light.cutoff_distance
	# TODO: check how lights work when using a node tree
	# if bl_light.use_nodes and bl_light.node_tree:

	# 	node = bl_light.node_tree.nodes['Emission']
	# 	light_color = node.inputs['Color'].default_value
	# 	light_intensity = node.inputs['Strength'].default_value # have to check how to relate to candelas
	# 	log.error("unsupported: using nodetree for light " + bl_obj.name)
	shadow_soft_size = bl_light.shadow_soft_size * 100
	fields.append('\t<SourceSize value="%f"/>\n' % shadow_soft_size)

	fields.append('\t<Intensity value="%f"/>\n' % light_intensity)
	fields.append('\t<AttenuationRadius value="%f"/>\n' % light_attenuation_radius)
	fields.append('\t<IntensityUnits value="%s"/>\n' % light_intensity_units)
	# we could set usetemp=1 and write temperature attribute
	fields.append('\t<Color usetemp="0" R="%f" G="%f" B="%f"/>\n' % light_color[:])


def fill_obj_camera(obj_dict, target):
	obj_dict["type"] = "Camera"

	fields = obj_dict["fields"]
	bl_cam = target.data

	use_dof = "1" if bl_cam.dof.use_dof else "0"
	fields.append('\t<DepthOfField enabled="%s"/>\n' % use_dof)
	dof_target = bl_cam.dof.focus_object
	if dof_target:
		# BAD CODE: dof target is not the same thing as lookat target.
		# lookat target should be determined from a lookat modifier if it exists
		# and focus target maybe corresponds to a different property in the camera field
		# fields.append('\t<LookAt Actor="%s"/>\n' % sanitize_name(dof_target.name))
		pass

	fields.append('\t<SensorWidth value="%f"/>\n' % bl_cam.sensor_width)

	# blender doesn't have per-camera aspect ratio
	sensor_aspect_ratio = 1.777778
	fields.append('\t<SensorAspectRatio value="%f"/>\n' % sensor_aspect_ratio)

	focus_distance_cm = bl_cam.dof.focus_distance * 100
	fields.append('\t<FocusDistance value="%f"/>\n' % focus_distance_cm)  # to centimeters
	fields.append('\t<FStop value="%f"/>\n' % bl_cam.dof.aperture_fstop)
	fields.append('\t<FocalLength value="%f"/>\n' % bl_cam.lens)


def fill_obj_lightprobe(obj_dict, target):
	# TODO: LIGHT PROBE
	obj_dict["type"] = "CustomActor"
	bl_probe = target.data

	fields = obj_dict["fields"]
	attribs = obj_dict["attrib"]

	probe_type = bl_probe.type
	if probe_type == "PLANAR":
		attribs.append(' PathName="/DatasmithBlenderContent/Blueprints/BP_BlenderPlanarReflection"')

	elif probe_type == "CUBEMAP":
		## we could also try using min/max if it makes a difference
		_, _, obj_scale = target.matrix_world.decompose()  # NOCHECKIN fix this
		avg_scale = (obj_scale.x + obj_scale.y + obj_scale.z) * 0.333333

		if bl_probe.influence_type == "BOX":
			attribs.append(' PathName="/DatasmithBlenderContent/Blueprints/BP_BlenderBoxReflection"')

			falloff = bl_probe.falloff  # this value is 0..1
			transition_distance = falloff * avg_scale
			fields.append('\t<KeyValueProperty name="TransitionDistance" type="Float" val="%f"/>\n' % transition_distance)

		elif bl_probe.influence_type == "ELIPSOID":
			attribs.append(' PathName="/DatasmithBlenderContent/Blueprints/BP_BlenderSphereReflection"')

			probe_radius = bl_probe.influence_distance * 100 * avg_scale
			fields.append('\t<KeyValueProperty name="Radius" type="Float" val="%f"/>\n' % probe_radius)

		else:
			log.error("invalid light_probe.influence_type")

	elif probe_type == "GRID":
		# for now we just export to custom object, but it doesn't affect the render on
		# the unreal side. would be cool if it made a difference by setting volumetric importance volume
		attribs.append(' PathName="/DatasmithBlenderContent/Blueprints/BP_BlenderGridProbe"')

		# blender influence_distance is outwards, maybe we should grow the object to match?
		# outward_influence would be 1.0 + influence_distance / size maybe?
		# obj_mat = obj_mat @ Matrix.Scale(outward_influence, 4)

	else:
		log.error("unhandled light probe type %s" % bl_probe.type)


def fill_obj_empty(obj_dict, target):
	pass


def fill_obj_unknown(obj_dict, target):
	log.error("Invalid object type: %s" % target.type)


def fill_obj_unsupported(obj_dict, target):
	log.warn("Unsupported object type: %s" % target.type)


obj_fill_funcs = {
	"EMPTY": fill_obj_empty,
	"CAMERA": fill_obj_camera,
	"MESH": fill_obj_mesh,
	"CURVE": fill_obj_mesh,
	"FONT": fill_obj_mesh,
	"LIGHT": fill_obj_light,
	"LIGHT_PROBE": fill_obj_lightprobe,
	"ARMATURE": fill_obj_unsupported,
	"LATTICE": fill_obj_unsupported,
	"GPENCIL": fill_obj_unsupported,
}


def collect_object_transform2(bl_obj, instance_mat=None):
	mat_basis = bl_obj.matrix_world
	if instance_mat:
		mat_basis = instance_mat
	obj_mat = matrix_datasmith @ mat_basis @ matrix_datasmith.inverted()

	if bl_obj.type in "CAMERA" or bl_obj.type == "LIGHT":
		obj_mat = obj_mat @ matrix_forward
	elif bl_obj.type == "LIGHT_PROBE":
		bl_probe = bl_obj.data
		if bl_probe.type == "PLANAR":
			obj_mat = obj_mat @ Matrix.Scale(0.05, 4)
		elif bl_probe.type == "CUBEMAP":
			if bl_probe.influence_type == "BOX":
				size = bl_probe.influence_distance * 100
				obj_mat = obj_mat @ Matrix.Scale(size, 4)

	loc, rot, scale = obj_mat.decompose()
	return '\t<Transform tx="%f" ty="%f" tz="%f" qw="%f" qx="%f" qy="%f" qz="%f" sx="%f" sy="%f" sz="%f"/>\n' % (loc.x, loc.y, loc.z, rot.w, rot.x, rot.y, rot.z, scale.x, scale.y, scale.z)


# ensures that `objects` has an entry for `_object` and ensures that
# the parent is also already there, and has `_object` as a children
# returns the base actor structure, as added in the `objects` list
def get_object_data(objects, _object, top_level_objs, object_name=None, instance_parent=None):
	assert _object
	unique = False
	if object_name:
		unique = True
	if not object_name:
		object_name = _object.name

	object_name = sanitize_name(object_name)
	log.info("getting obj %s" % object_name)
	object_data = None
	if not unique:
		object_data = objects.get(object_name)
	if not object_data:
		object_data = create_object(_object)
		object_data["name"] = object_name

		if not unique:
			objects[object_name] = object_data

		parent = instance_parent or _object.parent
		if parent:
			parent_data = get_object_data(objects, parent, top_level_objs)
			parent_data["children"].append(object_data)
		else:  # is top level object
			log.info("TOP LEVEL OBJ:%s" % object_data["name"])
			top_level_objs.append(object_data)
	return object_data


def create_object(obj):
	assert obj

	visible = not obj.hide_render and obj.show_instancer_for_render
	object_data = {
		"fields": [],
		"attrib": [' visible="%s"' % visible],
		"children": [],
		"instances": {},
	}
	original = obj.original
	if original:
		if original.users_collection:
			object_data["layer"] = original.users_collection[0].name_full

	object_data["transform"] = collect_object_transform2(obj)
	return object_data


CONVERTIBLE_TO_MESH = ("MESH", "CURVE", "FONT")


# for now let's try writing the xml directly
def collect_depsgraph(output, use_instanced_meshes, selected_only):
	d = bpy.context.evaluated_depsgraph_get()
	top_level_objs = []
	instance_groups = {}

	# last_parent = None
	# last_parent_data = None
	for instance in d.object_instances:
		if selected_only and not instance.object.original.select_get():
			continue

		transform = collect_object_transform2(instance.object, instance.matrix_world)
		was_instanced = False
		if use_instanced_meshes and instance.is_instance:
			original = instance.instance_object.original

			if original.type in CONVERTIBLE_TO_MESH:
				mesh_name = get_mesh_name(instance.instance_object)  # ensure that mesh data has been collected
				if mesh_name:
					was_instanced = True
					# original_name = original.name
					""" # maybe optimization to avoid calling get_object_data that much
				if instance.parent == last_parent:
					parent_data = last_parent_data
				else:
					parent_data = get_object_data(instance_groups, instance.parent, top_level_objs)
					last_parent_data = parent_data
					last_parent = instance.parent
					"""
					parent_data = get_object_data(instance_groups, instance.parent, top_level_objs)
					instance_lists = parent_data["instances"]
					instance_list = instance_lists.get(mesh_name)
					instance_material_slots = None
					if not instance_list:
						instance_list = instance_lists[mesh_name] = []
						instance_material_slots = []
						bl_obj = instance.instance_object
						for idx, slot in enumerate(bl_obj.material_slots):
							if slot.link == "OBJECT":
								material_list = datasmith_context["materials"]
								material_list.append((slot.material, bl_obj))
								safe_name = sanitize_name(slot.material.name)
								instance_material_slots.append('\t\t\t<material id="%i" name="%s"/>\n' % (idx, safe_name))

					parent_matrix = instance.parent.matrix_world
					# instance_matrix = instance.matrix_world @ parent_matrix.inverted()
					instance_matrix = parent_matrix.inverted() @ instance.matrix_world
					instance_transform = collect_object_transform2(instance.object, instance_matrix)
					instance_world_transform = collect_object_transform2(instance.object, instance.matrix_world)

					instance_list.append((instance_transform, instance_world_transform, instance_material_slots))

		if not was_instanced:
			obj = instance.object
			assert obj
			name = None

			inst_parent = None
			if instance.is_instance:
				inst_parent = instance.parent
				name = make_instance_name(instance)

			object_data = get_object_data(instance_groups, obj, top_level_objs, object_name=name, instance_parent=inst_parent)

			if instance.is_instance:
				object_data["transform"] = transform

			filler = obj_fill_funcs.get(obj.type, fill_obj_unknown)
			filler(object_data, obj)

	output = []
	for parent_obj in top_level_objs:
		render_tree(parent_obj, output, indent="\t")

	result = "".join(output)
	return result


def make_instance_name(instance):
	id_list = []
	for id in instance.persistent_id:
		if id != 0x7FFFFFFF:
			id_list.append("_%i" % id)
		else:
			id_list.append("_")

	instance_id = "".join("_%i" % id for id in instance.persistent_id if id != 0x7FFFFFFF)
	instance_id = "".join(id_list)
	inst = instance.instance_object
	parent_chain = []
	parent = instance.parent
	while parent:
		parent_chain.append(parent.name)
		parent = parent.parent
	parents_name = "_".join(parent_chain)
	name = "%s_%s_%s" % (parents_name, inst.name, instance_id)
	return name


def render_tree(obj_dict, output, indent):
	output.append(indent)
	output.append("<")
	obj_type = obj_dict.get("type", "Actor")
	output.append(obj_type)
	output.append(' name="')
	obj_name = obj_dict["name"]
	output.append(obj_name)

	layer = obj_dict.get("layer")
	if layer:
		output.append('" layer="')
		obj_layer = obj_dict["layer"]
		output.append(obj_layer)

	output.append('"')

	attribs = obj_dict["attrib"]
	if attribs:
		for attr in attribs:
			output.append(attr)

	output.append(">\n")

	fields = obj_dict["fields"]
	for field in fields:
		output.append(indent)
		output.append(field)

	output.append(indent)
	output.append(obj_dict["transform"])

	children = obj_dict["children"]
	parent_instances = obj_dict["instances"]

	if children or parent_instances:
		output.append(indent)
		output.append("\t<children>\n")
		# output.append('\t<children visible="')
		# output.append(str(obj_dict['visible']))
		# output.append('">\n')

		for child in children:
			next_indent = "%s\t\t" % indent
			render_tree(child, output, next_indent)

		for original, instances in parent_instances.items():
			num_instances = len(instances)
			if num_instances == 1:
				output.append(indent)
				output.append('\t\t<ActorMesh name="')
				output.append(obj_name)
				output.append("_")
				output.append(original)
				output.append('">\n')
				output.append(indent)
				output.append('\t\t\t<mesh name="')
				output.append(original)
				output.append('"/>\n')
				output.append(indent)
				output.append("\t\t")

				transform = instances[0][1]
				output.append(transform)

				instance_materials = instances[0][2]
				if instance_materials:
					for mat in instance_materials:
						output.append(indent)
						output.append(mat)

				output.append(indent)
				output.append("\t\t</ActorMesh>\n")

			else:
				output.append(indent)
				output.append('\t\t<ActorHierarchicalInstancedStaticMesh name="')
				output.append(obj_name)
				output.append("_")
				output.append(original)
				output.append('">\n')
				output.append(indent)
				output.append('\t\t\t<mesh name="')
				output.append(original)
				output.append('"/>\n')
				output.append(indent)
				output.append("\t\t\t")
				output.append(obj_dict["transform"])
				output.append(indent)
				output.append('\t\t\t<Instances count="')
				output.append(str(len(instances)))
				output.append('">\n')
				for instance in instances:
					output.append(indent)
					output.append(instance[0])

				output.append(indent)
				output.append("\t\t\t</Instances>\n")
				output.append(indent)
				output.append("\t\t</ActorHierarchicalInstancedStaticMesh>\n")

		output.append(indent)
		output.append("\t</children>\n")

	output.append(indent)
	output.append("</")
	output.append(obj_type)
	output.append(">\n")


def get_instance_local_matrix(instance):
	instance_matrix = instance.matrix_world

	# first try for instanced objects parent (instancer object)
	parent = instance.parent

	# if not found, try for hierarchy parent
	if not parent:
		parent = instance.object.parent

	if parent:
		parent_matrix = parent.matrix_world
		instance_matrix = parent_matrix.inverted() @ instance_matrix

	instance_matrix = matrix_datasmith @ instance_matrix @ matrix_datasmith.inverted()

	object_type = instance.object.type
	if object_type in ["CAMERA", "LIGHT"]:
		instance_matrix = instance_matrix @ matrix_forward

	return instance_matrix


def collect_anims(context, new_iterator: bool, use_instanced_meshes: bool):
	anims = []
	anims_strings = []
	if new_iterator:
		log.info("collecting animations new iterator")
		anim_objs = {}
		d = bpy.context.evaluated_depsgraph_get()
		for instance in d.object_instances:
			base_name = instance.object.name
			if instance.is_instance:
				if use_instanced_meshes:
					# instanced meshes can't be animated
					continue
				base_name = make_instance_name(instance)
			object_name = sanitize_name(base_name)
			object_matrix = get_instance_local_matrix(instance)
			anim_data = {
				"name": object_name,
				"animates": False,
				"matrix": object_matrix,
			}
			anim_objs[object_name] = anim_data

		frame_at_export_time = context.scene.frame_current
		frame_start = context.scene.frame_start
		frame_end = context.scene.frame_end

		# TODO: found a bit late about this: we need to test and profile
		# https://docs.blender.org/api/current/bpy_extras.anim_utils.html

		num_frames = frame_end - frame_start + 1

		for frame_idx in range(frame_start, frame_end + 1):
			log.info("collecting frame %d" % frame_idx)
			context.scene.frame_set(frame_idx)
			d = bpy.context.evaluated_depsgraph_get()
			for instance in d.object_instances:
				base_name = instance.object.name
				if instance.is_instance:
					if use_instanced_meshes:
						# instanced meshes can't be animated
						continue
					base_name = make_instance_name(instance)
				object_name = sanitize_name(base_name)
				anim_data = anim_objs[object_name]
				animates = anim_data["animates"]

				instance_matrix = get_instance_local_matrix(instance)

				if not animates:
					# TODO: maybe don't use != here, instead use some kind of threshold to avoid
					# a false positive from float jitter
					if anim_data["matrix"] != instance_matrix:
						animates = anim_data["animates"] = True
						anim_data["frames"] = []

				if animates:
					frames = anim_data["frames"]
					frames.append(instance_matrix.copy())

		# write phase:
		to_deg = 360 / math.tau
		rot_fix = np.array((-to_deg, -to_deg, to_deg))
		for obj_name, obj_data in anim_objs.items():
			if not obj_data["animates"]:
				continue
			log.info(f"writing animation for obj:{obj_name}")

			timeline_repr = [
				'''{
				"actor": "''',
				obj_name,
				'",',
			]

			translations = np.empty((num_frames, 4), dtype=np.float32)
			rotations = np.empty((num_frames, 4), dtype=np.float32)
			scales = np.empty((num_frames, 4), dtype=np.float32)
			translations[:, 0] = np.arange(frame_start, frame_end + 1)
			rotations[:, 0] = np.arange(frame_start, frame_end + 1)
			scales[:, 0] = np.arange(frame_start, frame_end + 1)

			timeline = obj_data["frames"]
			for frame_idx, frame_mat in enumerate(timeline):
				loc, rot, scale = frame_mat.decompose()
				# tx_slice = (frame_idx, slice(1, 4))
				translations[frame_idx, 1:4] = loc
				rotations[frame_idx, 1:4] = rot_fix * rot.to_euler("XYZ")
				scales[frame_idx, 1:4] = scale

			translations[np.isnan(translations)] = 0
			trans_expression = ",".join('{"id":%d,"x":%f,"y":%f,"z":%f}' % tuple(v) for v in translations)
			timeline_repr.extend(('"trans":[', trans_expression, "],"))

			rotations[np.isnan(rotations)] = 0
			rot_expression = ",".join('{"id":%d,"x":%f,"y":%f,"z":%f}' % tuple(v) for v in rotations)
			timeline_repr.extend(('"rot":[', rot_expression, "],"))

			scales[np.isnan(scales)] = 0
			scale_expression = ",".join('{"id":%d,"x":%f,"y":%f,"z":%f}' % tuple(v) for v in scales)
			timeline_repr.extend(('"scl":[', scale_expression, "],"))

			timeline_repr.append('"type":"transform"}')
			result = "".join(timeline_repr)
			anims_strings.append(result)

	else:  # if not new_iterator
		frame_at_export_time = context.scene.frame_current
		frame_start = context.scene.frame_start
		frame_end = context.scene.frame_end

		# TODO: found a bit late about this: we need to test and profile
		# https://docs.blender.org/api/current/bpy_extras.anim_utils.html

		anim_objs = datasmith_context["anim_objects"]

		num_frames = frame_end - frame_start + 1
		num_objects = len(anim_objs)
		object_timelines = [[Matrix() for frame in range(num_frames)] for obj in range(num_objects)]
		object_animates = [False for num in range(num_objects)]
		# collect phase?

		for arr_idx, frame_idx in enumerate(range(frame_start, frame_end + 1)):
			context.scene.frame_set(frame_idx)

			for obj_idx, obj in enumerate(anim_objs):
				obj_mat = collect_object_transform(obj[0])
				object_timelines[obj_idx][arr_idx] = obj_mat

				if arr_idx == 0:
					continue

				if not object_animates[obj_idx]:
					changed = obj_mat != object_timelines[obj_idx][arr_idx - 1]
					if changed:
						object_animates[obj_idx] = True

		anims_strings = []
		# write phase:
		to_deg = 360 / math.tau
		rot_fix = np.array((-to_deg, -to_deg, to_deg))
		for idx, timeline in enumerate(object_timelines):
			if not object_animates[idx]:
				continue
			log.error(f"writing obj:{idx}")

			timeline_repr = [
				'''{
				"actor": "''',
				anim_objs[idx][1],
				'",',
			]

			translations = np.empty((num_frames, 4), dtype=np.float32)
			rotations = np.empty((num_frames, 4), dtype=np.float32)
			scales = np.empty((num_frames, 4), dtype=np.float32)
			translations[:, 0] = np.arange(frame_start, frame_end + 1)
			rotations[:, 0] = np.arange(frame_start, frame_end + 1)
			scales[:, 0] = np.arange(frame_start, frame_end + 1)

			for frame_idx, frame_mat in enumerate(timeline):
				loc, rot, scale = frame_mat.decompose()
				# tx_slice = (frame_idx, slice(1, 4))
				translations[frame_idx, 1:4] = loc
				rotations[frame_idx, 1:4] = rot_fix * rot.to_euler("XYZ")
				scales[frame_idx, 1:4] = scale

			trans_expression = ",".join('{"id":%d,"x":%f,"y":%f,"z":%f}' % tuple(v) for v in translations)
			timeline_repr.extend(('"trans":[', trans_expression, "],"))

			rot_expression = ",".join('{"id":%d,"x":%f,"y":%f,"z":%f}' % tuple(v) for v in rotations)
			timeline_repr.extend(('"rot":[', rot_expression, "],"))

			scale_expression = ",".join('{"id":%d,"x":%f,"y":%f,"z":%f}' % tuple(v) for v in scales)
			timeline_repr.extend(('"scl":[', scale_expression, "],"))

			timeline_repr.append('"type":"transform"}')
			result = "".join(timeline_repr)
			anims_strings.append(result)

	if anims_strings:
		output = [
			"""\
{
	"version": "0.1",
	"fps": """,
			str(context.scene.render.fps),
			""",\n\t\t"animations": [""",
			",".join(anims_strings),
			"\n\t]\n}",
		]

		output_text = "".join(output)
		anims.append(output_text)

		# cleanup
	context.scene.frame_set(frame_at_export_time)

	return anims


datasmith_context = None


def collect_and_save(context, args, save_path):
	start_time = time.monotonic()
	summary = {}

	global datasmith_context
	datasmith_context = {
		"objects": [],
		"anim_objects": [],
		"textures": [],
		"meshes": {},
		"meshes_per_original": {},
		"materials": [],
		"material_curves": None,
		"metadata": [],
		"compatibility_mode": args["compatibility_mode"],
		"libraries": {},
	}

	log.info("collecting objects")

	selected_only = args["export_selected"]
	skip_textures = args["skip_textures"]
	export_animations = args["export_animations"]
	use_old_iterator = args["use_old_iterator"]
	use_instanced_meshes = args["use_instanced_meshes"]
	config_always_twosided = args["always_twosided"]

	objects = []
	log.info("USE NEW OBJECT ITERATOR")
	obj_output = collect_depsgraph(objects, use_instanced_meshes, selected_only)

	anims = []
	if export_animations:
		anims = collect_anims(context, not use_old_iterator, use_instanced_meshes)

	all_textures = {}
	environment = collect_environment(context.scene.world, all_textures)

	log.info("Collecting materials")
	materials = datasmith_context["materials"]
	unique_materials = []
	for material in materials:
		found = False
		for mat in unique_materials:
			if material[0] is mat[0]:  # materials here are tuple (material, owner)
				found = True
				break
		if not found:
			unique_materials.append(material)

	material_nodes = collect_all_materials(unique_materials, all_textures, config_always_twosided)

	log.info("finished collecting, now saving")

	basedir, file_name = path.split(save_path)
	folder_name = file_name + "_Assets"
	# make sure basepath_Assets directory exists
	try:
		os.makedirs(path.join(basedir, folder_name))
	except FileExistsError:
		pass

	log.info("writing anims")
	anim_nodes = []

	assert len(anims) < 2
	if anims:
		anim = anims[0]
		filename = path.join(basedir, folder_name, "anim_new.json")
		log.info("writing to file:%s" % filename)
		with open(filename, "w") as f:
			f.write(anim)

		anim = Node("LevelSequence", {"name": "anim_new"})
		anim.push(Node("File", {"path": f"{folder_name}/anim_new.json"}))
		anim_nodes.append(anim)

	log.info("writing meshes")
	meshes = datasmith_context["meshes"].values()
	mesh_nodes = [mesh_save(mesh, basedir, folder_name) for mesh in meshes]

	log.info("writing textures")

	tex_nodes = [save_texture(tex, basedir, folder_name, skip_textures) for tex in all_textures.values()]

	log.info("building XML tree")

	n = get_file_header()
	n.push("\n")

	for anim in anim_nodes:
		n.push(anim)

	for obj in objects:
		n.push(obj)

	if obj_output:
		n.push(obj_output)

	if environment:
		for env in environment:
			n.push(env)

	for mesh_node in mesh_nodes:
		n.push(mesh_node)
	for mat in material_nodes:
		n.push(mat)

	for tex in tex_nodes:
		n.push(tex)

	for metadata in datasmith_context["metadata"]:
		n.push(metadata)

	end_time = time.monotonic()
	total_time = end_time - start_time

	log.info("generating datasmith data took:%f" % total_time)
	# n.push(Node("Export", {"Duration": total_time}))

	log.info("generating xml")
	result = n.string_rep(first=True)

	filename = path.join(basedir, file_name + ".udatasmith")
	log.info("writing to file: %s" % filename)

	with open(filename, "w") as f:
		f.write(result)
	log.info("export finished")

	summary["Time"] = total_time
	summary["Size"] = len(result)

	return summary


def save(context, kwargs):
	handler = None
	use_logging = bool(kwargs["use_logging"])
	use_profiling = bool(kwargs["use_profiling"])
	use_telemetry = bool(kwargs["use_telemetry"])
	filepath = kwargs["filepath"]

	summary = {}

	if use_logging:
		log_path = filepath + ".log"
		handler = logging.FileHandler(log_path, mode="w")

		formatter = logging.Formatter(fmt="%(asctime)s.%(msecs)03d %(levelname)-8s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
		handler.setFormatter(formatter)
		log.addHandler(handler)
		log.setLevel(logging.DEBUG)
		handler.setLevel(logging.DEBUG)
	try:
		from os import path

		basepath, ext = path.splitext(filepath)

		log.info("Starting Datasmith Export")

		if use_profiling:
			import cProfile

			pr = cProfile.Profile()
			pr.enable()

		summary = collect_and_save(context, kwargs, basepath)

		if use_profiling:
			pr.disable()
			prof_path = "%s.prof" % basepath
			log.warn("writing profile to path: %s" % prof_path)
			pr.dump_stats(prof_path)

		log.info("Finished Datasmith Export")

	except Exception as error:
		log.error("Datasmith export error:")
		log.error(error)
		raise

	finally:
		if use_logging:
			log.info("Finished logging to path:" + log_path)
			handler.close()
			log.removeHandler(handler)

	if use_telemetry:
		print("sending telemetry data")

		summary_arr = []

		for key in summary:
			summary_arr.append("%s: %s\n" % (key, summary[key]))
		summary_txt = "".join(summary_arr)
		import time

		time_ms = time.time_ns() // 1000

		from . import bl_info

		version_string = "%s.%s.%s" % bl_info["version"]
		print("version string: " + version_string)

		telemetry_data = {
			"summary": summary_txt,
			"export_time": str(time_ms),
			"status": "SUCCESS",
			"log": "placeholder log",
			"version": version_string,
			"export_selected": kwargs["export_selected"],
			"use_instanced_meshes": kwargs["use_instanced_meshes"],
			"apply_modifiers": kwargs["apply_modifiers"],
			"export_animations": kwargs["export_animations"],
			"export_metadata": kwargs["export_metadata"],
			"skip_textures": kwargs["skip_textures"],
			"compatibility_mode": kwargs["compatibility_mode"],
			"use_gamma_hack": kwargs["use_gamma_hack"],
			"use_old_iterator": kwargs["use_old_iterator"],
			"use_logging": kwargs["use_logging"],
			"use_profiling": kwargs["use_profiling"],
		}

		import requests

		BF_TELEMETRY_HOST = "http://telemetry.botero.tech:8080/bf_telemetry.lua"
		try:
			requests.post(BF_TELEMETRY_HOST, data=telemetry_data, timeout=1)
		except Exception:
			log.warn("unable to reach telemetry server")
	return {"FINISHED"}
