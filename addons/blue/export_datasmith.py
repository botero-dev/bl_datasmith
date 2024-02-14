# Datasmith exporter for Blender
# Copyright 2018-2022 Andrés Botero

import math
import os
import time
import hashlib
import shutil
from os import path
import numpy as np

import bpy
import idprop
import bmesh
from mathutils import Matrix, Vector, Euler

from .data_types import UDMesh, Node, sanitize_name, calc_hash

import logging
log = logging.getLogger("bl_datasmith")

# these are to track the messages, printing to the console a full message, but not leaking 
# user info when generating telemetry reports

reported_warns = set()
reported_errors = set()

def report_warn(message, user_info = None, once=False):
	if once:
		if message in reported_warns:
			return
		reported_warns.add(message)

	if user_info:
		log.warn(message % user_info)
	else:
		log.warn(message)

def report_error(message, user_info = None, once=False):
	if once:
		if message in reported_errors:
			return
		reported_errors.add(message)

	if user_info:
		log.error(message % user_info)
	else:
		log.error(message)

matrix_datasmith = Matrix.Scale(100, 4)
matrix_datasmith[1][1] *= -1.0

# optimize: maybe set this as a numpy array directly?
matrix_normals = [
	[1, 0, 0],
	[0, -1, 0],
	[0, 0, 1],
]

# used for lights and cameras, whose forward is (0, 0, -1) and its right is (1, 0, 0)
matrix_forward = Matrix((
	(0, 1, 0, 0),
	(0, 0, -1, 0),
	(-1, 0, 0, 0),
	(0, 0, 0, 1)
))

def exp_vector(value, exp_list):
	# n = Node("Color", {
	# nocheckin: may not work
	n = Node("Color", {
		# "Name": name,
		"constant": "(R=%.6f,G=%.6f,B=%.6f,A=1.0)"%tuple(value)
		})
	return exp_list.push(n)

def exp_color(value, exp_list, name=None):
	n = Node("Color", {
		"constant": "(R=%.6f,G=%.6f,B=%.6f,A=%.6f)"%tuple(value)
		})
	if name:
		n["Name"] = name
	return exp_list.push(n)

def exp_scalar(value, exp_list):
	n = Node("Scalar", {
		# "Name": "",
		"constant": "%f"%value
		})
	return exp_list.push(n)

# if we flip the Y axis of the UVs when first querying them, and then flip it
# back right before we are going to use it in a sampler node, we match more
# accurately what blender does under the hood
USE_TEXCOORD_FLIP_Y = True
# This has a cost, so we should definitely make it a tunable in the plugin

MAT_FUNC_FLIPY = "/DatasmithBlenderContent/MaterialFunctions/FlipY"

def exp_texcoord(exp_list, index=0, u_tiling=1.0, v_tiling=1.0):
	uv = Node("TextureCoordinate")
	uv["Index"] = index
	uv["UTiling"] = u_tiling
	uv["VTiling"] = v_tiling

	exp_uv = exp_list.push(uv)

	if USE_TEXCOORD_FLIP_Y:
		flip = Node("FunctionCall", { "Function": MAT_FUNC_FLIPY })
		push_exp_input(flip, "0", exp_uv)
		exp_uv = exp_list.push(flip)

	pad = Node("AppendVector")
	push_exp_input(pad, "0", exp_uv)
	push_exp_input(pad, "1", exp_scalar(0, exp_list) )
	return {"expression": exp_list.push(pad) }


MAT_FUNC_TEXCOORD_GENERATED = "/DatasmithBlenderContent/MaterialFunctions/TexCoord_Generated"
def exp_texcoord_generated(exp_list):
	# this function is used as a generator for default inputs in some tex nodes
	n = Node("FunctionCall", { "Function": MAT_FUNC_TEXCOORD_GENERATED })
	return { "expression": exp_list.push(n) }

def exp_texcoord_node(socket, exp_list):
	socket_name = socket.name
	if socket_name == "Generated":
		output = Node("FunctionCall", { "Function": MAT_FUNC_TEXCOORD_GENERATED })
		return { "expression": exp_list.push(output) }
	if socket_name == "Normal":
		output = Node("VertexNormalWS")
		return { "expression": exp_list.push(output) }
	if socket_name == "UV":
		return exp_texcoord(exp_list)
	if socket_name == "Object":
		output = Node("FunctionCall", { "Function": op_custom_functions["LOCAL_POSITION"]})
		return { "expression": exp_list.push(output) }
	if socket_name == "Camera":
		output = Node("FunctionCall", { "Function": "/DatasmithBlenderContent/MaterialFunctions/TexCoord_Camera" })
		return { "expression": exp_list.push(output) }
	if socket_name == "Window":
		output = Node("FunctionCall", { "Function": "/DatasmithBlenderContent/MaterialFunctions/TexCoord_Window" })
		return { "expression": exp_list.push(output) }
	if socket_name == "Reflection":
		output = Node("ReflectionVectorWS")
		return { "expression": exp_list.push(output) }


tex_gradient_node_map = {
	'LINEAR':           "/DatasmithBlenderContent/MaterialFunctions/TexGradient_Linear",
	'QUADRATIC':        "/DatasmithBlenderContent/MaterialFunctions/TexGradient_Quadratic",
	'EASING':           "/DatasmithBlenderContent/MaterialFunctions/TexGradient_Easing",
	'DIAGONAL':         "/DatasmithBlenderContent/MaterialFunctions/TexGradient_Diagonal",
	'SPHERICAL':        "/DatasmithBlenderContent/MaterialFunctions/TexGradient_Spherical",
	'QUADRATIC_SPHERE': "/DatasmithBlenderContent/MaterialFunctions/TexGradient_QuadraticSphere",
	'RADIAL':           "/DatasmithBlenderContent/MaterialFunctions/TexGradient_Radial",
}

NODE_TEX_GRADIENT_OUTPUTS = ("Color", "Fac")
def exp_tex_gradient(socket, exp_list):
	node = socket.node
	gradient_type = node.gradient_type

	function_path = tex_gradient_node_map[gradient_type]
	n = Node("FunctionCall", { "Function": function_path})

	vector_exp = get_expression_mapped(node.inputs['Vector'], exp_list, exp_texcoord_generated)
	push_exp_input(n, "0", vector_exp)

	exp_idx = exp_list.push(n)
	cached_node = (exp_idx, NODE_TEX_GRADIENT_OUTPUTS)
	cached_nodes[node] = cached_node
	return exp_from_cache(cached_node, socket.name)

VEC_ZERO = Vector()
ROT_ZERO = Euler()
VEC_ONE = Vector((1,1,1))


NODE_TEX_IMAGE_OUTPUTS = ("Color", 0, 0, 0, "Alpha")
def exp_tex_image(socket, exp_list):
	node = socket.node

	image = node.image
	if not image:
		return { "expression": exp_scalar(0, exp_list) }

	name = sanitize_name(image.name) # name_full?
	should_whitelist = False
	# we use this to know if this texture is behind a normalmap node, so
	# we mark it as non-sRGB+invert green channel
	texture_type = get_context() or 'SRGB' 
	if texture_type == MAT_CTX_BUMP:
		should_whitelist = True
		texture_type = 'SRGB'
	# ensure that texture is exported
	get_or_create_texture(name, image, texture_type)

	texture_exp = exp_texture(name)

	tex_coord = get_expression_mapped(node.inputs['Vector'], exp_list, exp_texcoord)

	tex_coord_exp = None
	if tex_coord:
		proj = None
		if node.projection == 'FLAT':
			proj = Node("ComponentMask")
		elif node.projection == 'BOX':
			proj = Node("FunctionCall", { "Function": "/DatasmithBlenderContent/MaterialFunctions/TexImage_ProjBox"})
		elif node.projection == 'SPHERE':
			proj = Node("FunctionCall", { "Function": "/DatasmithBlenderContent/MaterialFunctions/TexImage_ProjSphere"})
		elif node.projection == 'TUBE':
			proj = Node("FunctionCall", { "Function": "/DatasmithBlenderContent/MaterialFunctions/TexImage_ProjTube"})
		else:
			log.error("node TEX_IMAGE has unhandled projection: %s" % node.projection)

		push_exp_input(proj, "0", tex_coord)
		tex_coord_exp = { "expression": exp_list.push(proj) }

	if tex_coord_exp:

		if USE_TEXCOORD_FLIP_Y:
			flip = Node("FunctionCall", { "Function": MAT_FUNC_FLIPY })
			push_exp_input(flip, "0", tex_coord_exp)
			tex_coord_exp = {"expression": exp_list.push(flip)}


		texture_exp.push(Node("Coordinates", tex_coord_exp))

	exp_idx = exp_list.push(texture_exp)
	cached_node = (exp_idx, NODE_TEX_IMAGE_OUTPUTS)
	cached_nodes[node] = cached_node

	if should_whitelist:
		whitelisted_textures.append({ "expression": cached_node[0] })

	return exp_from_cache(cached_node, socket.name)
	


# the generator param is a function that receives the exp_list and returns
# the expression for the default value, for example `exp_texcoord`
def get_expression_mapped(socket, exp_list, generator, force_exp=False):
	# there is this secret menu to the right in TEX_IMAGE nodes that
	# consists in a mapping node + axis reprojection
	# we don't want to create mapping node if not needed
	result_exp = None
	if len(socket.links) != 0:
		result_exp = get_expression(socket, exp_list)

	if result_exp == None and force_exp:
		result_exp = generator(exp_list)
	node = socket.node
	mapping = node.texture_mapping
	mapping_axes = (mapping.mapping_x, mapping.mapping_y, mapping.mapping_z)
	base_axes = ('X', 'Y', 'Z')
	if mapping_axes != base_axes:
		if not result_exp:
			result_exp = generator(exp_list)
		
		node_break = Node("FunctionCall", { "Function": MAT_FUNC_BREAK_FLOAT3 } )
		push_exp_input(node_break, "0", result_exp)
		node_break_exp = exp_list.push(node_break)
		
		node_make = Node("FunctionCall", { "Function": MAT_FUNC_MAKE_FLOAT3 } )
		for idx in range(3):
			if mapping_axes[idx] in base_axes:
				target_idx = base_axes.index(mapping_axes[idx])
				push_exp_input(node_make, idx, (node_break_exp, target_idx))

		result_exp = {"expression": exp_list.push(node_make)}
	
	tx_loc, tx_rot, tx_scale = (mapping.translation, mapping.rotation, mapping.scale)
	if tx_loc != VEC_ZERO or tx_rot != ROT_ZERO or tx_scale != VEC_ONE:

		if not result_exp:
			result_exp = generator(exp_list)

		mapping_func = MAT_FUNC_MAPPINGS[mapping.vector_type]

		n = Node("FunctionCall", { "Function": mapping_func })

		push_exp_input(n, "0", result_exp)
		push_exp_input(n, "1", exp_vector(tx_loc, exp_list))
		push_exp_input(n, "2", exp_vector(tx_rot, exp_list))
		push_exp_input(n, "3", exp_vector(tx_scale, exp_list))

		result_exp = {"expression": exp_list.push(n)}

	return result_exp

def exp_wireframe(socket, exp_list):
	report_warn("Unsupported node 'Wireframe'. Writing value 0.", once=True)
	return {"expression": exp_scalar(0, exp_list)}


NODE_TEX_BRICK_OUTPUTS = ("Color", "Fac")

def exp_tex_brick(socket, exp_list):

	node = socket.node

	function_path = "/DatasmithBlenderContent/MaterialFunctions/TexBrick"
	n = Node("FunctionCall", { "Function": function_path})

	inputs = node.inputs
	vector_exp = get_expression_mapped(inputs['Vector'], exp_list, exp_texcoord_generated)
	push_exp_input(n, "0", vector_exp)
	push_exp_input(n, "1", get_expression(inputs["Color1"], exp_list))
	push_exp_input(n, "2", get_expression(inputs["Color2"], exp_list))
	push_exp_input(n, "3", get_expression(inputs["Mortar"], exp_list))
	push_exp_input(n, "4", get_expression(inputs["Scale"], exp_list))
	push_exp_input(n, "5", get_expression(inputs["Mortar Size"], exp_list))
	push_exp_input(n, "6", get_expression(inputs["Mortar Smooth"], exp_list))
	push_exp_input(n, "7", get_expression(inputs["Bias"], exp_list))
	push_exp_input(n, "8", get_expression(inputs["Brick Width"], exp_list))
	push_exp_input(n, "9", get_expression(inputs["Row Height"], exp_list))
	push_exp_input(n, "10", exp_scalar(node.offset, exp_list))
	push_exp_input(n, "11", exp_scalar(node.offset_frequency, exp_list))
	push_exp_input(n, "12", exp_scalar(node.squash, exp_list))
	push_exp_input(n, "13", exp_scalar(node.squash_frequency, exp_list))
		
	exp_idx = exp_list.push(n)
	cached_node = (exp_idx, NODE_TEX_BRICK_OUTPUTS)
	cached_nodes[node] = cached_node
	return exp_from_cache(cached_node, socket.name)



NODE_TEX_MAGIC_OUTPUTS = ("Color", "Fac")
def exp_tex_magic(socket, exp_list):

	node = socket.node
	
	function_path = "/DatasmithBlenderContent/MaterialFunctions/TexMagic"
	n = Node("FunctionCall", { "Function": function_path})

	inputs = node.inputs
	vector_exp = get_expression_mapped(inputs['Vector'], exp_list, exp_texcoord_generated)
	push_exp_input(n, "0", vector_exp)
	push_exp_input(n, "1", get_expression(inputs["Scale"], exp_list))
	push_exp_input(n, "2", get_expression(inputs["Distortion"], exp_list))
	push_exp_input(n, "3", exp_scalar(node.turbulence_depth, exp_list))

	exp_idx = exp_list.push(n)
	cached_node = (exp_idx, NODE_TEX_MAGIC_OUTPUTS)
	cached_nodes[node] = cached_node
	return exp_from_cache(cached_node, socket.name)


tex_dimensions_map = {
	'1D': '1d',
	'2D': '2d',
	'3D': '3d',
	'4D': '4d',
}

tex_musgrave_type_map = {
	'MULTIFRACTAL':        'multi_fractal',
	'RIDGED_MULTIFRACTAL': 'ridged_multi_fractal',
	'HYBRID_MULTIFRACTAL': 'hybrid_multi_fractal',
	'FBM':                 'fBm',
	'HETERO_TERRAIN':      'hetero_terrain',
}

def exp_tex_musgrave(socket, exp_list):
	node = socket.node

	musgrave_type = tex_musgrave_type_map[node.musgrave_type]
	dimensions = tex_dimensions_map[node.musgrave_dimensions]
	function_name = "node_tex_musgrave_%s_%s" % (musgrave_type, dimensions)

	n = Node("Custom", {
		"Description": function_name,
		"OutputType": "1" # output is scalar,
	})
	
	# n.push(Node("Define", {"value": "HELLO=2"}))
	n.push(Node("Include", {"path": "/Plugin/DatasmithBlenderContent/BlenderMaterialTexMusgrave.ush"}))

	# by the end, the arguments array should have the 8 params, even if unused
	arguments = []
	arguments2 = []

	inputs = node.inputs
	def add_param(param_name, cond=True):
		if cond:
			arguments.append(param_name)
			param_exp = get_expression(inputs[param_name], exp_list)
			assert param_exp
			arguments2.append((param_name, param_exp))
		else:
			arguments.append("0")

	use_vector = (dimensions!='1d')
	if use_vector:
		vector_exp = get_expression_mapped(inputs['Vector'], exp_list, exp_texcoord_generated, force_exp=True)
		push_exp_input(n, "0", vector_exp)
		arguments.append("Vector")
		arguments2.append(("Vector", vector_exp))
	else:
		arguments.append("0")

	use_w = (dimensions == '1d' or dimensions == '4d')
	add_param("W", cond=use_w)

	add_param("Scale")
	add_param("Detail")
	add_param("Dimension")
	add_param("Lacunarity")

	use_offset = musgrave_type in ("ridged_multi_fractal", "hybrid_multi_fractal", "hetero_terrain")
	add_param("Offset", cond=use_offset)
		
	use_gain = musgrave_type in ("ridged_multi_fractal", "hybrid_multi_fractal")
	add_param("Gain", cond=use_gain)

	for idx, arg in enumerate(arguments2):
		n.push(Node("Arg", {"index": idx, "name": arg[0]}))
	
	for idx, arg in enumerate(arguments2):
		n.push(exp_input(idx, arg[1]))

	assert len(arguments) == 8
	func_params = ", ".join(arguments)

	code = "float r; %s(%s, r); return r;" % (function_name, func_params)

	n.push(Node("Code", children=[code]))

	return { "expression": exp_list.push(n) }

NODE_TEX_NOISE_OUTPUTS = ("Fac", "Color")
def exp_tex_noise(socket, exp_list):

	node = socket.node
	dimensions = tex_dimensions_map[node.noise_dimensions]

	function_path = "/DatasmithBlenderContent/MaterialFunctions/TexNoise_%s" % dimensions
	n = Node("FunctionCall", { "Function": function_path})

	input_idx = 0
	inputs = node.inputs
	def push_input(name):
		nonlocal input_idx
		exp = get_expression(inputs[name], exp_list, skip_default_warn=True)
		assert exp
		push_exp_input(n, input_idx, exp)
		input_idx += 1

	if dimensions!='1d':
		vector_exp = get_expression_mapped(inputs['Vector'], exp_list, exp_texcoord_generated, force_exp=True)
		push_exp_input(n, input_idx, vector_exp)
		input_idx += 1
	if dimensions == '1d' or dimensions == '4d':
		push_input("W")

	push_input("Scale")
	push_input("Detail")
	push_input("Roughness")
	push_input("Distortion")


	exp_idx = exp_list.push(n)
	cached_node = (exp_idx, NODE_TEX_NOISE_OUTPUTS)
	cached_nodes[node] = cached_node
	return exp_from_cache(cached_node, socket.name)


NODE_TEX_WHITE_NOISE_OUTPUTS = ("Value", "Color")
def exp_tex_white_noise(socket, exp_list):

	node = socket.node
	dimensions = tex_dimensions_map[node.noise_dimensions]

	function_path = "/DatasmithBlenderContent/MaterialFunctions/TexWhiteNoise_%s" % dimensions
	n = Node("FunctionCall", { "Function": function_path})

	input_idx = 0
	inputs = node.inputs

	if dimensions!='1d':
		exp = get_expression(inputs['Vector'], exp_list, skip_default_warn=True)
		push_exp_input(n, input_idx, exp)
		input_idx += 1
	if dimensions == '1d' or dimensions == '4d':
		exp = get_expression(inputs['W'], exp_list, skip_default_warn=True)
		push_exp_input(n, input_idx, exp)


	exp_idx = exp_list.push(n)
	cached_node = (exp_idx, NODE_TEX_WHITE_NOISE_OUTPUTS)
	cached_nodes[node] = cached_node
	return exp_from_cache(cached_node, socket.name)


# these are encoded as float values when sent to the shader code
tex_voronoi_metric_map = {
	'EUCLIDEAN': 0,
	'MANHATTAN': 1,
	'CHEBYCHEV': 2,
	'MINKOWSKI': 3,
}

tex_voronoi_type_map = {
	'F1':                'f1',
	'F2':                'f2',
	'SMOOTH_F1':         'smooth_f1',
	'DISTANCE_TO_EDGE':  'distance_to_edge',
	'N_SPHERE_RADIUS':   'n_sphere_radius',
}

def exp_tex_sky(socket, exp_list):
	report_warn("Unsupported node 'Sky Texture', Writing value 0.", once=True)
	return {"expression": exp_scalar(0, exp_list)}


def exp_tex_voronoi(socket, exp_list):

	node = socket.node
	dimensions = tex_dimensions_map[node.voronoi_dimensions]
	voronoi_type = node.feature
	voronoi_type_fn = tex_voronoi_type_map[voronoi_type]

	function_path = "/DatasmithBlenderContent/MaterialFunctions/TexVoronoi_%s_%s" % (voronoi_type_fn, dimensions)
	n = Node("FunctionCall", { "Function": function_path})

	input_idx = 0
	inputs = node.inputs
	def push_input(name):
		nonlocal input_idx
		exp = get_expression(inputs[name], exp_list, skip_default_warn=True)
		assert exp
		push_exp_input(n, input_idx, exp)
		input_idx += 1

	if dimensions!='1d':
		vector_exp = get_expression_mapped(inputs['Vector'], exp_list, exp_texcoord_generated, force_exp=True)
		push_exp_input(n, "0", vector_exp)
		input_idx += 1
	if dimensions == '1d' or dimensions == '4d':
		push_input("W")

	push_input("Scale")

	if voronoi_type == "SMOOTH_F1":
		push_input("Smoothness")

	use_metric = (dimensions != "1d") and (voronoi_type not in ('DISTANCE_TO_EDGE', 'N_SPHERE_RADIUS'))
	metric = node.distance
	if use_metric:
		if metric == 'MINKOWSKI':
			push_input("Exponent")
		else:
			input_idx += 1

	push_input("Randomness")

	if use_metric:
		metric_float = tex_voronoi_metric_map[metric]
		n.push(exp_input(input_idx, exp_scalar(metric_float, exp_list)))

	NODE_TEX_VORONOI_OUTPUTS = None
	if voronoi_type == 'DISTANCE_TO_EDGE':
		NODE_TEX_VORONOI_OUTPUTS = ("Distance", )
	elif voronoi_type == 'N_SPHERE_RADIUS':
		NODE_TEX_VORONOI_OUTPUTS = ("Radius", )
	else:
		if dimensions == "1d":
			NODE_TEX_VORONOI_OUTPUTS = ("Distance", "Color", "W")
		else:
			if dimensions != "4d":
				NODE_TEX_VORONOI_OUTPUTS = ("Distance", "Color", "Position")
			else:
				NODE_TEX_VORONOI_OUTPUTS = ("Distance", "Color", "Position", "W")

	exp_idx = exp_list.push(n)
	cached_node = (exp_idx, NODE_TEX_VORONOI_OUTPUTS)
	cached_nodes[node] = cached_node
	return exp_from_cache(cached_node, socket.name)

NODE_TEX_WAVE_OUTPUTS = ("Color", "Fac")
def exp_tex_wave(socket, exp_list):

	node = socket.node
	wave_type = node.wave_type
	wave_type_val = 0
	direction_val = 0
	if wave_type == 'BANDS':
		wave_type_val = 0
		direction_val = ('X', 'Y', 'Z', 'DIAGONAL').index(node.bands_direction)
	elif wave_type == 'RINGS':
		wave_type_val = 1
		direction_val = ('X', 'Y', 'Z', 'SPHERICAL').index(node.rings_direction)

	profile_val = ('SIN', 'SAW', 'TRI').index(node.wave_profile)

	function_path = "/DatasmithBlenderContent/MaterialFunctions/TexWave"
	n = Node("FunctionCall", { "Function": function_path})

	inputs = node.inputs
	vector_exp = get_expression_mapped(inputs['Vector'], exp_list, exp_texcoord_generated)
	push_exp_input(n, "0", vector_exp)
	push_exp_input(n, "1", get_expression(inputs["Scale"], exp_list))
	push_exp_input(n, "2", get_expression(inputs["Distortion"], exp_list))
	push_exp_input(n, "3", get_expression(inputs["Detail"], exp_list))
	push_exp_input(n, "4", get_expression(inputs["Detail Scale"], exp_list))
	push_exp_input(n, "5", get_expression(inputs["Detail Roughness"], exp_list))
	push_exp_input(n, "6", get_expression(inputs["Phase Offset"], exp_list))
	push_exp_input(n, "7", exp_scalar(wave_type_val, exp_list))
	push_exp_input(n, "8", exp_scalar(direction_val, exp_list))
	push_exp_input(n, "9", exp_scalar(profile_val, exp_list))
	
	exp_idx = exp_list.push(n)
	cached_node = (exp_idx, NODE_TEX_WAVE_OUTPUTS)
	cached_nodes[node] = cached_node
	return exp_from_cache(cached_node, socket.name)




NODE_TEX_CHECKER_OUTPUTS = ("Color", "Fac")

def exp_tex_checker(socket, exp_list):
	node = socket.node

	inputs = node.inputs
	n = Node("FunctionCall", {"Function": "/DatasmithBlenderContent/MaterialFunctions/TexChecker"})
	vector_exp = get_expression_mapped(inputs['Vector'], exp_list, exp_texcoord_generated)
	push_exp_input(n, "0", vector_exp)
	push_exp_input(n, "1", get_expression(inputs["Color1"], exp_list))
	push_exp_input(n, "2", get_expression(inputs["Color2"], exp_list))
	push_exp_input(n, "3", get_expression(inputs["Scale"], exp_list))
	
	exp_idx = exp_list.push(n)
	cached_node = (exp_idx, NODE_TEX_CHECKER_OUTPUTS)
	cached_nodes[node] = cached_node

	return exp_from_cache(cached_node, socket.name)


def exp_uvmap(node, exp_list):
	channel_name = node.uv_map
	owner = datasmith_context["material_owner"]
	uv_index = 0
	m = owner.data
	if type(m) is bpy.types.Mesh:
		for idx, uv in enumerate(m.uv_layers):
			if uv.name == id:
				uv_index = idx
	return exp_texcoord(exp_list, uv_index)

def exp_value(socket, exp_list):
	node_value = socket.default_value
	n = Node("Scalar", {
		"constant": "%f" % node_value,
	})
	if socket.node.label:
		n["Name"] = socket.node.label
	return {"expression": exp_list.push(n) }

def exp_rgb(socket, exp_list):
	node_value = socket.default_value
	n = Node("Color", {
		"constant": "(R=%.6f,G=%.6f,B=%.6f,A=%.6f)"%tuple(node_value)
		})
	
	if socket.node.label:
		n["Name"] = socket.node.label
	return {"expression": exp_list.push(n) }

# instead of setting coordinates here, use coordinates when creating
# the texture expression instead
def exp_texture(path, name=None): # , tex_coord_exp):
	n = Node("Texture")
	if name:
		n["Name"] = name
	n["PathName"] = path
	#n.push(Node("Coordinates", tex_coord_exp))
	return n

MAT_FUNC_RGB_TO_BW = "/DatasmithBlenderContent/MaterialFunctions/RGB_To_BW"
def exp_rgb_to_bw(socket, exp_list):
	input_exp = get_expression(socket.node.inputs[0], exp_list)
	n = Node("FunctionCall", { "Function": MAT_FUNC_RGB_TO_BW })
	push_exp_input(n, "0", input_exp)
	n_exp = exp_list.push(n)
	return { "expression": n_exp }

MAT_FUNC_MAKE_FLOAT3 = "/Engine/Functions/Engine_MaterialFunctions02/Utility/MakeFloat3"
def exp_make_vec3(socket, exp_list):
	node = socket.node
	output = Node("FunctionCall", { "Function": MAT_FUNC_MAKE_FLOAT3 })
	output.push(exp_input("0", get_expression(node.inputs[0], exp_list)))
	output.push(exp_input("1", get_expression(node.inputs[1], exp_list)))
	output.push(exp_input("2", get_expression(node.inputs[2], exp_list)))
	return { "expression": exp_list.push(output) }

MAT_FUNC_HSV_TO_RGB = "/DatasmithBlenderContent/MaterialFunctions/HSV_To_RGB"
def exp_make_hsv(socket, exp_list):
	inputs = socket.node.inputs
	output = Node("FunctionCall",  { "Function": MAT_FUNC_HSV_TO_RGB })
	push_exp_input(output, "0", get_expression(inputs[0], exp_list))
	push_exp_input(output, "1", get_expression(inputs[1], exp_list))
	push_exp_input(output, "2", get_expression(inputs[2], exp_list))
	return { "expression": exp_list.push(output) }

NODE_COMBINE_COLOR_MAP = {
	"RGB": MAT_FUNC_MAKE_FLOAT3,
	"HSV": MAT_FUNC_HSV_TO_RGB,
	#TODO: implement HSL
}

def exp_combine_color(socket, exp_list):
	node = socket.node
	func_path = NODE_COMBINE_COLOR_MAP[node.mode]
	output = Node("FunctionCall",  { "Function": func_path })
	inputs = node.inputs
	push_exp_input(output, "0", get_expression(inputs[0], exp_list))
	push_exp_input(output, "1", get_expression(inputs[1], exp_list))
	push_exp_input(output, "2", get_expression(inputs[2], exp_list))
	return { "expression": exp_list.push(output) }

NODE_BREAK_RGB_OUTPUTS = ('R', 'G', 'B')
NODE_BREAK_XYZ_OUTPUTS = ('X', 'Y', 'Z')
MAT_FUNC_BREAK_FLOAT3 = "/Engine/Functions/Engine_MaterialFunctions02/Utility/BreakOutFloat3Components"
def exp_break_vec3(socket, exp_list):
	node = socket.node
	output = Node("FunctionCall",  { "Function": MAT_FUNC_BREAK_FLOAT3 })
	output.push(exp_input("0", get_expression(node.inputs[0], exp_list)))
	expression_idx = exp_list.push(output)

	reverse_map = NODE_BREAK_RGB_OUTPUTS if node.type == 'SEPRGB' else NODE_BREAK_XYZ_OUTPUTS
	cached_node = (expression_idx, reverse_map) 
	cached_nodes[node] = cached_node
	return exp_from_cache(cached_node, socket.name)


MAT_FUNC_RGB_TO_HSV = "/DatasmithBlenderContent/MaterialFunctions/RGB_To_HSV"
NODE_BREAK_HSV_OUTPUTS = ("H", "S", "V")
def exp_break_hsv(socket, exp_list):

	output = Node("FunctionCall",  { "Function": MAT_FUNC_RGB_TO_HSV })
	push_exp_input(output, "0", get_expression(socket.node.inputs[0], exp_list))
	expression_idx = exp_list.push(output)

	cached_node = (expression_idx, NODE_BREAK_HSV_OUTPUTS)
	cached_nodes[socket.node] = cached_node
	return exp_from_cache(cached_node, socket.name)


# outputs are always called Red, Green, Blue even if mode is HSV
NODE_SEPARATE_COLOR_OUTPUTS = ("Red", "Green", "Blue")
NODE_SEPARATE_COLOR_MAP = {
	"RGB": MAT_FUNC_BREAK_FLOAT3,
	"HSV": MAT_FUNC_RGB_TO_HSV,
	#TODO: implement HSL
}

def exp_separate_color(socket, exp_list):
	node = socket.node

	func_path = NODE_SEPARATE_COLOR_MAP[node.mode]

	output = Node("FunctionCall",  { "Function": func_path })
	push_exp_input(output, "0", get_expression(node.inputs[0], exp_list))
	expression_idx = exp_list.push(output)

	cached_node = (expression_idx, NODE_SEPARATE_COLOR_OUTPUTS)
	cached_nodes[node] = cached_node
	return exp_from_cache(cached_node, socket.name)


MATH_CUSTOM_FUNCTIONS = {
	'INVERSE_SQRT': (1, "/DatasmithBlenderContent/MaterialFunctions/MathInvSqrt"),
	'EXPONENT':     (1, "/DatasmithBlenderContent/MaterialFunctions/MathExp"),
	'SINH':         (1, "/DatasmithBlenderContent/MaterialFunctions/MathSinH"),
	'COSH':         (1, "/DatasmithBlenderContent/MaterialFunctions/MathCosH"),
	'TANH':         (1, "/DatasmithBlenderContent/MaterialFunctions/MathTanH"),
	'MULTIPLY_ADD': (3, "/DatasmithBlenderContent/MaterialFunctions/MathMultiplyAdd"),
	'COMPARE':      (3, "/DatasmithBlenderContent/MaterialFunctions/MathCompare"),
	'SMOOTH_MIN':   (3, "/DatasmithBlenderContent/MaterialFunctions/MathSmoothMin"),
	'SMOOTH_MAX':   (3, "/DatasmithBlenderContent/MaterialFunctions/MathSmoothMax"),
	'WRAP':         (3, "/DatasmithBlenderContent/MaterialFunctions/MathWrap"),
	'SNAP':         (2, "/DatasmithBlenderContent/MaterialFunctions/MathSnap"),
	'PINGPONG':     (2, "/DatasmithBlenderContent/MaterialFunctions/MathPingPong"),
}

# these map 1:1 with UE4 nodes:
MATH_TWO_INPUTS = {
	'ADD': "Add",
	'SUBTRACT': "Subtract",
	'MULTIPLY': "Multiply",
	'DIVIDE': "Divide",
	'POWER': "Power",
	'MINIMUM': "Min",
	'MAXIMUM': "Max",
	'MODULO': "Fmod",
	'ARCTAN2': "Arctangent2",
}

# these use only one input in UE4
MATH_ONE_INPUT = {
	'SQRT': "SquareRoot",
	'ABSOLUTE': "Abs",
	'ROUND': "Round",
	'FLOOR': "Floor",
	'CEIL': "Ceil",
	'FRACT': "Frac",
	'SINE': "Sine",
	'COSINE': "Cosine",
	'TANGENT': "Tangent",
	'ARCSINE': "Arcsine",
	'ARCCOSINE': "Arccosine",
	'ARCTANGENT': "Arctangent",
	'SIGN': "Sign",
	'TRUNC': "Truncate",
}

# these require specific implementations:
MATH_CUSTOM_IMPL = {
	'LOGARITHM', # ue4 only has log2 and log10
	'LESS_THAN', # use UE4 If node
	'GREATER_THAN', # use UE4 If node
	'RADIANS',
	'DEGREES',
}

def exp_generic(name, inputs, exp_list, force_default=False):
	n = Node(name)
	for idx, input in enumerate(inputs):
		input_exp = get_expression(input, exp_list, force_default)
		n.push(exp_input(idx, input_exp))
	return { "expression": exp_list.push(n) }

def exp_function_call(path, inputs, exp_list, force_default=False):
	n = Node("FunctionCall", {"Function": path})
	if inputs:
		for idx, input in enumerate(inputs):
			input_exp = get_expression(input, exp_list, force_default)
			n.push(exp_input(idx, input_exp))
	return { "expression": exp_list.push(n) }



MAT_FUNC_MAPRANGE_LINEAR          = "/DatasmithBlenderContent/MaterialFunctions/MapRange_Linear"
MAT_FUNC_MAPRANGE_LINEAR_CLAMPED  = "/DatasmithBlenderContent/MaterialFunctions/MapRange_Linear_Clamped"
MAT_FUNC_MAPRANGE_STEPPED         = "/DatasmithBlenderContent/MaterialFunctions/MapRange_Stepped"
MAT_FUNC_MAPRANGE_STEPPED_CLAMPED = "/DatasmithBlenderContent/MaterialFunctions/MapRange_Stepped_Clamped"
MAT_FUNC_MAPRANGE_SMOOTHSTEP      = "/DatasmithBlenderContent/MaterialFunctions/MapRange_SmoothStep"
MAT_FUNC_MAPRANGE_SMOOTHERSTEP    = "/DatasmithBlenderContent/MaterialFunctions/MapRange_SmootherStep"

def exp_map_range(socket, exp_list):
	node = socket.node
	interpolation_type = node.interpolation_type
	func_path = None
	if interpolation_type == 'LINEAR':
		if node.clamp:
			func_path = MAT_FUNC_MAPRANGE_LINEAR_CLAMPED
		else:
			func_path = MAT_FUNC_MAPRANGE_LINEAR
	elif interpolation_type == 'STEPPED':
		if node.clamp:
			func_path = MAT_FUNC_MAPRANGE_STEPPED_CLAMPED
		else:
			func_path = MAT_FUNC_MAPRANGE_STEPPED
	elif interpolation_type == 'SMOOTHSTEP':
		func_path = MAT_FUNC_MAPRANGE_SMOOTHSTEP
	elif interpolation_type == 'SMOOTHERSTEP':
		func_path = MAT_FUNC_MAPRANGE_SMOOTHERSTEP

	assert func_path


	value =    get_expression(node.inputs['Value'], exp_list)
	from_min = get_expression(node.inputs['From Min'], exp_list)
	from_max = get_expression(node.inputs['From Max'], exp_list)
	to_min =   get_expression(node.inputs['To Min'], exp_list)
	to_max =   get_expression(node.inputs['To Max'], exp_list)

	n = Node("FunctionCall", {"Function": func_path})
	n.push(exp_input("0", value))
	n.push(exp_input("1", from_min))
	n.push(exp_input("2", from_max))
	n.push(exp_input("3", to_min))
	n.push(exp_input("4", to_max))

	if interpolation_type == 'STEPPED':
		steps = get_expression(node.inputs['Steps'], exp_list)
		n.push(exp_input("5", steps))


	return {"expression": exp_list.push(n)}

def exp_math(node, exp_list):
	op = node.operation
	exp = None
	if op in MATH_TWO_INPUTS:
		exp = exp_generic(
			name= MATH_TWO_INPUTS[op],
			inputs= node.inputs[:2],
			exp_list=exp_list,
			force_default=True,
		)
	elif op in MATH_ONE_INPUT:
		exp = exp_generic(
			name= MATH_ONE_INPUT[op],
			inputs= node.inputs[:1],
			exp_list=exp_list,
			force_default=True,
		)
	elif op in MATH_CUSTOM_FUNCTIONS:
		size, path = MATH_CUSTOM_FUNCTIONS[op]
		exp = exp_function_call(
			path,
			inputs= node.inputs[:size],
			exp_list=exp_list,
		)
	elif op in MATH_CUSTOM_IMPL:
		in_0 = get_expression(node.inputs[0], exp_list)
		n = None
		if op == 'RADIANS':
			n = Node("Multiply")
			n.push(exp_input("0", in_0))
			n.push(exp_input("1", { "expression": exp_scalar(math.tau / 360, exp_list)}))
		elif op == 'DEGREES':
			n = Node("Multiply")
			n.push(exp_input("0", in_0))
			n.push(exp_input("1", { "expression": exp_scalar(360 / math.tau, exp_list)}))
		else:
			# these use two inputs
			in_1 = get_expression(node.inputs[1], exp_list)
			if op == 'LOGARITHM': # take two logarithms and divide
				log0 = Node("Logarithm2")
				log0.push(exp_input("0", in_0))
				exp_0 = exp_list.push(log0)
				log1 = Node("Logarithm2")
				log1.push(exp_input("0", in_1))
				exp_1 = exp_list.push(log1)
				n = Node("Divide")
				n.push(exp_input("0", {"expression": exp_0}))
				n.push(exp_input("1", {"expression": exp_1}))
			elif op == 'LESS_THAN':
				n = Node("If")
				one = {"expression": exp_scalar(1.0, exp_list)}
				zero = {"expression": exp_scalar(0.0, exp_list)}
				n.push(exp_input("0", in_0)) # A
				n.push(exp_input("1", in_1)) # B
				n.push(exp_input("2", zero)) # A > B
				n.push(exp_input("3", one)) # A == B
				n.push(exp_input("4", one)) # A < B
			elif op == 'GREATER_THAN':
				n = Node("If")
				one = {"expression": exp_scalar(1.0, exp_list)}
				zero = {"expression": exp_scalar(0.0, exp_list)}
				n.push(exp_input("0", in_0)) # A
				n.push(exp_input("1", in_1)) # B
				n.push(exp_input("2", one)) # A > B
				n.push(exp_input("3", zero)) # A == B
				n.push(exp_input("4", zero)) # A < B
		assert n
		exp = { "expression": exp_list.push(n) }


	assert exp, "unrecognized math operation: %s" % op

	if getattr(node, "use_clamp", False):
		clamp = Node("Saturate")
		clamp.push(exp_input("0", exp))
		exp = { "expression": exp_list.push(clamp) }
	return exp

# these nodes should only be built-ins (green nodes)
VECT_MATH_SAME_AS_SCALAR = {
	'ADD',
	'SUBTRACT',
	'MULTIPLY',
	'DIVIDE',

	'ABSOLUTE',
	'MINIMUM',
	'MAXIMUM',
	'FLOOR',
	'CEIL',
	'MODULO',
	'SINE',
	'COSINE',
	'TANGENT',
}


VECT_MATH_NODES = {
	'CROSS_PRODUCT': (2, "CrossProduct"),
	'DOT_PRODUCT':   (2, "DotProduct"),
	'DISTANCE':      (2, "Distance"),
	'NORMALIZE':     (1, "Normalize"),
	'FRACTION':      (1, "Frac"),
}
VECT_MATH_FUNCTIONS = { # tuples are (input_count, path)

	'WRAP': (3, "/DatasmithBlenderContent/MaterialFunctions/VectWrap"),
	'SNAP': (2, "/DatasmithBlenderContent/MaterialFunctions/VectSnap"),
	'PROJECT': (2, "/DatasmithBlenderContent/MaterialFunctions/VectProject"),
	'REFLECT': (2, "/DatasmithBlenderContent/MaterialFunctions/VectReflect"),
}

def exp_vect_math(node, exp_list):
	node_op = node.operation
	if node_op in VECT_MATH_SAME_AS_SCALAR:
		return exp_math(node, exp_list)
	elif node_op in VECT_MATH_NODES:
		size, name = VECT_MATH_NODES[node_op]
		return exp_generic(
			name=name,
			inputs=node.inputs[:size],
			exp_list=exp_list,
			force_default=True,
		)
	elif node_op in VECT_MATH_FUNCTIONS:
		size, path = VECT_MATH_FUNCTIONS[node_op]
		return exp_function_call(
			path,
			inputs= node.inputs[:size],
			exp_list=exp_list,
			force_default=True,
		)
	elif node_op == 'SCALE':
		return exp_generic(
			name= "Multiply",
			inputs= (node.inputs[0], node.inputs[3]),
			exp_list=exp_list,
			force_default=True,
		)
	elif node_op == 'LENGTH':
		n = Node("Distance")
		n.push(exp_input("0", get_expression(node.inputs[0], exp_list) ))
		n.push(exp_input("1", exp_vector((0,0,0), exp_list) ))
		return { "expression": exp_list.push(n) }

	log.error("VECT_MATH node operation:%s not found" % node_op)

# TODO: make test cases for all math nodes

def exp_gamma(node, exp_list):
	n = Node(MATH_TWO_INPUTS['POWER'])
	exp_0 = get_expression(node.inputs["Color"], exp_list)
	n.push(exp_input("0", exp_0))
	exp_1 = get_expression(node.inputs["Gamma"], exp_list)
	n.push(exp_input("1", exp_1))
	return {"expression": exp_list.push(n)}


op_map_blend = {
	'MIX':          "/DatasmithBlenderContent/MaterialFunctions/Blend_Mix",
	'DARKEN':       "/DatasmithBlenderContent/MaterialFunctions/Blend_Darken",
	'MULTIPLY':     "/DatasmithBlenderContent/MaterialFunctions/Blend_Multiply",
	'BURN':         "/DatasmithBlenderContent/MaterialFunctions/Blend_ColorBurn",
	'LIGHTEN':      "/DatasmithBlenderContent/MaterialFunctions/Blend_Lighten",
	'SCREEN':       "/DatasmithBlenderContent/MaterialFunctions/Blend_Screen",
	'DODGE':        "/DatasmithBlenderContent/MaterialFunctions/Blend_Dodge",
	'ADD':          "/DatasmithBlenderContent/MaterialFunctions/Blend_Add",
	'OVERLAY':      "/DatasmithBlenderContent/MaterialFunctions/Blend_Overlay",
	'SOFT_LIGHT':   "/DatasmithBlenderContent/MaterialFunctions/Blend_SoftLight",
	'LINEAR_LIGHT': "/DatasmithBlenderContent/MaterialFunctions/Blend_LinearLight",
	'DIFFERENCE':   "/DatasmithBlenderContent/MaterialFunctions/Blend_Difference",
	'EXCLUSION':    "/DatasmithBlenderContent/MaterialFunctions/Blend_Exclusion",
	'SUBTRACT':     "/DatasmithBlenderContent/MaterialFunctions/Blend_Subtract",
	'DIVIDE':       "/DatasmithBlenderContent/MaterialFunctions/Blend_Divide",
	'HUE':          "/DatasmithBlenderContent/MaterialFunctions/Blend_Hue",
	'SATURATION':   "/DatasmithBlenderContent/MaterialFunctions/Blend_Saturation",
	'COLOR':        "/DatasmithBlenderContent/MaterialFunctions/Blend_Color",
	'VALUE':        "/DatasmithBlenderContent/MaterialFunctions/Blend_Value",
}



def exp_mixrgb(node, exp_list):
	inputs = node.inputs
	exp_t = get_expression(inputs['Fac'], exp_list)
	# blender did always clamp factor input for color blends
	# doesn't do it forcefully in new mix node because it is optional
	t_clamped = Node("Saturate")
	push_exp_input(t_clamped, 0, exp_t)
	exp_t2 = exp_list.push(t_clamped)

	exp_a = get_expression(inputs['Color1'], exp_list)
	exp_b = get_expression(inputs['Color2'], exp_list)

	blend = Node("FunctionCall", { "Function": op_map_blend[node.blend_type] })
	push_exp_input(blend, 0, exp_t2)
	push_exp_input(blend, 1, exp_a)
	push_exp_input(blend, 2, exp_b)
	exp_blend = exp_list.push(blend)

	if node.use_clamp:
		clamp = Node("Saturate")
		push_exp_input(clamp, "0", exp_blend)
		exp_blend = exp_list.push(clamp)

	return exp_blend


EXP_MIX_FACTOR_SCALAR = 0
EXP_MIX_FACTOR_VECTOR = 1
EXP_MIX_A_SCALAR = 2
EXP_MIX_B_SCALAR = 3
EXP_MIX_A_VECTOR = 4
EXP_MIX_B_VECTOR = 5
EXP_MIX_A_RGBA = 6
EXP_MIX_B_RGBA = 7

def exp_mix(socket, exp_list):
	node = socket.node
	inputs = node.inputs
	data_type = node.data_type

	factor_slot = EXP_MIX_FACTOR_SCALAR
	if data_type == "VECTOR" and node.factor_mode == "NON_UNIFORM":
		factor_slot = EXP_MIX_FACTOR_VECTOR
	in_factor = get_expression(inputs[factor_slot], exp_list)

	if node.clamp_factor:
		# possible optimization:
		# if in_factor is constant, do static check?
		clamp = Node("Saturate")
		push_exp_input(clamp, "0", in_factor)
		in_factor = exp_list.push(clamp)


	if data_type == "FLOAT":
		in_a = get_expression(inputs[EXP_MIX_A_SCALAR], exp_list)
		in_b = get_expression(inputs[EXP_MIX_B_SCALAR], exp_list)

	elif data_type == "VECTOR":
		in_a = get_expression(inputs[EXP_MIX_A_VECTOR], exp_list, force_default=True)
		in_b = get_expression(inputs[EXP_MIX_B_VECTOR], exp_list, force_default=True)

	elif data_type == "RGBA":
		# RGBA blend modes have their own nodes
		in_a = get_expression(inputs[EXP_MIX_A_RGBA], exp_list)
		in_b = get_expression(inputs[EXP_MIX_B_RGBA], exp_list)

	else:
		assert(False)
		print("ERROR! unknown data type")

	if data_type == "FLOAT" or data_type == "VECTOR":
		result = Node("LinearInterpolate")
		push_exp_input(result, 0, in_a)
		push_exp_input(result, 1, in_b)
		push_exp_input(result, 2, in_factor)
	else:
		assert(data_type == "RGBA")
		result = Node("FunctionCall", { "Function": op_map_blend[node.blend_type] })
		push_exp_input(result, 0, in_factor)
		push_exp_input(result, 1, in_a)
		push_exp_input(result, 2, in_b)
	
	result_exp = exp_list.push(result)

	if data_type == "RGBA":
		if node.clamp_result:
			clamp = Node("Saturate")
			push_exp_input(clamp, "0", result_exp)
			result_exp = exp_list.push(clamp)

	return result_exp



op_custom_functions = {
	"BRIGHTCONTRAST":     "/DatasmithBlenderContent/MaterialFunctions/BrightContrast",
	"COLOR_RAMP":         "/DatasmithBlenderContent/MaterialFunctions/ColorRamp",
	"CURVE_RGB":          "/DatasmithBlenderContent/MaterialFunctions/RGBCurveLookup2",
	"FRESNEL":            "/DatasmithBlenderContent/MaterialFunctions/BlenderFresnel",
	"HUE_SAT":            "/DatasmithBlenderContent/MaterialFunctions/AdjustHSV",
	"LAYER_WEIGHT":       "/DatasmithBlenderContent/MaterialFunctions/LayerWeight",
	"LOCAL_POSITION":     "/DatasmithBlenderContent/MaterialFunctions/BlenderLocalPosition",
	"NORMAL_FROM_HEIGHT": "/Engine/Functions/Engine_MaterialFunctions03/Procedurals/NormalFromHeightmap",
}


def exp_generic_function(node, exp_list, node_type, socket_names):
	n = Node("FunctionCall", { "Function": op_custom_functions[node_type]})
	for idx, socket_name in enumerate(socket_names):
		input_expression = get_expression(node.inputs[socket_name], exp_list)
		n.push(exp_input(idx, input_expression))
	return {"expression": exp_list.push(n) }

def exp_bright_contrast(node, exp_list):
	return exp_generic_function(node, exp_list, 'BRIGHTCONTRAST', ('Color', 'Bright', 'Contrast'))

def exp_hsv(node, exp_list):
	n = Node("FunctionCall", { "Function": op_custom_functions["HUE_SAT"]})
	exp_hue = get_expression(node.inputs['Hue'], exp_list)
	n.push(exp_input("0", exp_hue))
	exp_sat = get_expression(node.inputs['Saturation'], exp_list)
	n.push(exp_input("1", exp_sat))
	exp_value = get_expression(node.inputs['Value'], exp_list)
	n.push(exp_input("2", exp_value))
	exp_fac = get_expression(node.inputs['Fac'], exp_list)
	n.push(exp_input("3", exp_fac))
	exp_color = get_expression(node.inputs['Color'], exp_list)
	n.push(exp_input("4", exp_color))
	return exp_list.push(n)


# convenience function to skip adding an input if the input is None
def push_exp_input(node, input_idx, expression, output_idx = 0):
	if expression != None:
		node.push(exp_input(input_idx, expression, output_idx))


def exp_input(input_idx, expression, output_idx = 0):
	expression_idx = -1
	if type(expression) is dict:
		if "expression" not in expression:
			log.error(expression)
		expression_idx = expression["expression"]
		output_idx = expression.get("OutputIndex", 0)
	elif type(expression) is tuple:
		expression_idx, output_idx = expression
	elif expression != None:
		assert type(expression) == int
		expression_idx = expression
		# output_idx = 0 # already set as default value

	# TODO: find loose ends by enabling this error
	# or change this function to receive the parent node as parameter
	# and early exit if expression is None
	#if expression_idx == -1:
	#	report_error("trying to use expression=None for input for another expression")

	return '\n\t\t\t\t<Input Name="%s" expression="%s" OutputIndex="%s"/>' % (input_idx, expression_idx, output_idx)

def exp_output(output_id, expression):
	expression_idx = -1
	output_idx = 0
	if type(expression) is dict:
		if "expression" not in expression:
			log.error(expression)
		expression_idx = expression["expression"]
		output_idx = expression.get("OutputIndex", 0)
	elif type(expression) is tuple:
		expression_idx, output_idx = expression
	elif expression != None:
		assert type(expression) == int
		expression_idx = expression

	if output_idx == 0:
		return '\n\t\t<%s expression="%s"/>' % (output_id, expression_idx)

	else:
		return '\n\t\t<%s expression="%s" OutputIndex="%s"/>' % (output_id, expression_idx, output_idx)


def exp_invert(node, exp_list):
	n = Node("OneMinus")
	exp_color = get_expression(node.inputs['Color'], exp_list)
	n.push(exp_input("0", exp_color))
	invert_exp = exp_list.push(n)

	blend = Node("LinearInterpolate")
	exp_fac = get_expression(node.inputs['Fac'], exp_list)
	blend.push(exp_input("0", exp_color))
	blend.push(exp_input("1", {"expression": invert_exp}))
	blend.push(exp_input("2", exp_fac))

	return exp_list.push(blend)

def exp_light_falloff(socket, exp_list):
	report_warn("Unsupported node 'Light Falloff', returning unmodified light strength", once=True)
	return get_expression(socket.node.inputs["Strength"], exp_list)

MAT_FUNC_MAPPINGS = {
	'NORMAL':  "/DatasmithBlenderContent/MaterialFunctions/MappingNormal",
	'POINT':   "/DatasmithBlenderContent/MaterialFunctions/MappingPoint3D",
	'TEXTURE': "/DatasmithBlenderContent/MaterialFunctions/MappingTexture3D",
	'VECTOR':  "/DatasmithBlenderContent/MaterialFunctions/MappingVector",
}

def exp_mapping(node, exp_list):

	mapping_func = MAT_FUNC_MAPPINGS[node.vector_type]
	
	n = Node("FunctionCall", { "Function": mapping_func })

	input_vector = get_expression(node.inputs['Vector'], exp_list)
	input_rotation = get_expression(node.inputs['Rotation'], exp_list)
	input_scale = get_expression(node.inputs['Scale'], exp_list)

	n.push(exp_input("0", input_vector))
	if not node.vector_type in ('NORMAL', 'VECTOR'):
		input_location = get_expression(node.inputs['Location'], exp_list)
		n.push(exp_input("1", input_location))

	n.push(exp_input("2", input_rotation))
	n.push(exp_input("3", input_scale))

	return {"expression": exp_list.push(n)}

NODE_NORMAL_OUTPUTS = ("Normal", "Dot")
def exp_normal(socket, exp_list):
	node = socket.node
	n = Node("FunctionCall", { "Function": "/DatasmithBlenderContent/MaterialFunctions/Normal" })
	push_exp_input(n, "0", exp_vector(node.outputs[0].default_value, exp_list))
	push_exp_input(n, "1", get_expression(node.inputs[0], exp_list))
	exp = exp_list.push(n)
	
	cached_node = (exp, NODE_NORMAL_OUTPUTS)
	cached_nodes[node] = cached_node
	return exp_from_cache(cached_node, socket.name)


MAT_CTX_NORMAL = "NORMAL"
def exp_normal_map(socket, exp_list):
	node_input = socket.node.inputs['Color']
	# hack: is it safe to assume that everything under here is normal?
	# maybe not, because it could be masks to mix normals
	# most certainly, these wouldn't be colors (so should be non-srgb)
	push_context(MAT_CTX_NORMAL)
	return_exp = get_expression(node_input, exp_list)
	pop_context()


	strength_input = socket.node.inputs["Strength"]
	if strength_input.links or strength_input.default_value != 1.0:
		node_strength = Node("FunctionCall", {"Function": "/DatasmithBlenderContent/MaterialFunctions/NormalStrength"})
		node_strength.push(exp_input("0", return_exp))
		node_strength.push(exp_input("1", get_expression(strength_input, exp_list)))
		return_exp = { "expression": exp_list.push(node_strength) }
	return return_exp


VECT_TRANSFORM_TYPE = ('POINT', 'VECTOR', 'NORMAL')

VECT_TRANSFORM_RENAME_MAP = {
	'WORLD':  "World",
	'CAMERA': "Camera",
	'OBJECT': "Object",
}

def exp_vect_transform(socket, exp_list):
	node = socket.node

	input_exp = get_expression(node.inputs[0], exp_list)
	if node.convert_from == node.convert_to:
		return input_exp

	name_from = VECT_TRANSFORM_RENAME_MAP[node.convert_from]
	name_to =   VECT_TRANSFORM_RENAME_MAP[node.convert_to]
	func_path = "/DatasmithBlenderContent/MaterialFunctions/VectorTransform%sTo%s" % (name_from, name_to)
	output = Node("FunctionCall", {"Function": func_path})
	push_exp_input(output, "0", input_exp)


	output_index = VECT_TRANSFORM_TYPE.index(node.vector_type)
	if node.vector_type == 'NORMAL':
		report_warn("Unsupported vector type:Normal in Vector Transform node. FIXME", once=True)
	return {"expression": exp_list.push(output), "OutputIndex": output_index}

MAT_FUNC_VECTOR_ROTATE_ANGLEAXIS = "/DatasmithBlenderContent/MaterialFunctions/VectorRotateAngleAxis"
MAT_FUNC_VECTOR_ROTATE_EULERANGLES = "/DatasmithBlenderContent/MaterialFunctions/VectorRotateEulerAngles"

def exp_vector_rotate(socket, exp_list):
	node = socket.node
	inputs = node.inputs

	rotation_type = node.rotation_type
	node_fn = MAT_FUNC_VECTOR_ROTATE_ANGLEAXIS
	if rotation_type == 'EULER_XYZ':
		node_fn= MAT_FUNC_VECTOR_ROTATE_EULERANGLES

	node_rotate = Node("FunctionCall", {"Function": node_fn})
	push_exp_input(node_rotate, "0", exp_scalar(-1 if node.invert else 1, exp_list)) # Sign
	push_exp_input(node_rotate, "1", get_expression(inputs["Vector"], exp_list)) # Vector
	push_exp_input(node_rotate, "2", get_expression(inputs["Center"], exp_list, force_default=True)) # Center

	if rotation_type == 'EULER_XYZ':
		push_exp_input(node_rotate, "3", get_expression(inputs["Rotation"], exp_list))
	else:
		axis = None
		if rotation_type == 'X_AXIS':
			axis = exp_vector((1, 0, 0), exp_list)
		elif rotation_type == 'Y_AXIS':
			axis = exp_vector((0, 1, 0), exp_list)
		elif rotation_type == 'Z_AXIS':
			axis = exp_vector((0, 0, 1), exp_list)
		else:
			axis = get_expression(inputs["Axis"], exp_list, force_default=True)
		push_exp_input(node_rotate, "3", axis)
		push_exp_input(node_rotate, "4", get_expression(inputs["Angle"], exp_list))

	return {"expression": exp_list.push(node_rotate)}


def exp_new_geometry(socket, exp_list):
	socket_name = socket.name
	if socket_name == "Position":
		output = Node("FunctionCall", {"Function": "/DatasmithBlenderContent/MaterialFunctions/BlenderWorldPosition"})
		return { "expression": exp_list.push(output) }
	if socket_name == "Normal":
		output = Node("VertexNormalWS")
		return { "expression": exp_list.push(output) }
	if socket_name == "Tangent":
		output = Node("VertexTangentWS")
		return { "expression": exp_list.push(output) }
	if socket_name == "True Normal":
		output = Node("VertexNormalWS")
		return { "expression": exp_list.push(output) }
	if socket_name == "Incoming":
		output = Node("FunctionCall", {"Function": "/DatasmithBlenderContent/MaterialFunctions/Incoming"})
		return { "expression": exp_list.push(output) }
	if socket_name == "Backfacing":
		global material_hint_twosided
		material_hint_twosided = True
		output = Node("FunctionCall", {"Function": "/DatasmithBlenderContent/MaterialFunctions/Backfacing"})
		return { "expression": exp_list.push(output) }

	if socket_name == "Parametric":
		report_warn("Unsupported node 'Geometry:Parametric'.", once=True)
		return {"expression": exp_scalar(0.5, exp_list)}
	if socket_name == "Pointiness":
		report_warn("Unsupported node 'Geometry:Pointiness'.", once=True)
		return {"expression": exp_scalar(0.5, exp_list)}
	if socket_name == "Random Per Island":
		report_warn("Unsupported node 'Geometry:Random Per Island'.", once=True)
		return {"expression": exp_scalar(0, exp_list)}


def exp_layer_weight(socket, exp_list):
	expr = None
	if socket.node in reverse_expressions:
		expr = reverse_expressions[socket.node]
	else:
		exp_blend = get_expression(socket.node.inputs['Blend'], exp_list)
		n = Node("FunctionCall", { "Function": op_custom_functions['LAYER_WEIGHT']})
		n.push(exp_input("0", exp_blend))

		normal_exp = get_expression(socket.node.inputs["Normal"], exp_list, skip_default_warn=True)
		if normal_exp:
			n.push(exp_input("1", normal_exp))

		expr = exp_list.push(n)
		reverse_expressions[socket.node] = expr

	out_index = 0
	if socket.name == "Fresnel":
		out_index = 0
	elif socket.name == "Facing":
		out_index = 1
	else:
		report_error("LAYER_WEIGHT node from unknown socket")
	return {"expression": expr, "OutputIndex": out_index}

def exp_light_path(socket, exp_list):
	report_warn("Unsupported node 'Light Path:%s'. Writing 1.0 value." % socket.name, once=True)
	n = exp_scalar(1, exp_list)
	return {"expression": n}


def exp_object_info(socket, exp_list):
	field = socket.name
	if field == "Location":
		report_warn("Node 'Object Info:Location' Will get inverted Y coordinates, matching UE4 coordinate system.", once=True)
		n = Node("FunctionCall", {"Function": "/DatasmithBlenderContent/MaterialFunctions/Object_Location"})
		exp = exp_list.push(n)
	elif field == "Color":
		report_warn("Node 'Object Info:Color' is not supported by Unreal, writing white color.", once=True)
		exp = exp_vector((1,1,1), exp_list)
	elif field == "Alpha":
		report_warn("Node 'Object Info:Alpha' is not supported by Unreal, writing 1.0 value instead.", once=True)
		exp = exp_scalar(1, exp_list)
	elif field == "Object Index":
		report_warn("Node 'Object Info:Object Index' is not supported by Unreal, writing PerInstanceRandom instead.", once=True)
		exp = exp_list.push(Node("PerInstanceRandom"))
	elif field == "Material Index":
		report_warn("Node 'Object Info:Material Index' is not supported by Unreal, writing 0 instead.", once=True)
		exp = exp_scalar(0, exp_list)
	elif field == "Random":
		report_warn("Node 'Object Info:Random' only works for instanced meshes.", once=True)
		exp = exp_list.push(Node("PerInstanceRandom"))
	else:
		report_error("Invalid output for node 'Object Info': '%s'" % field, once=True)
		exp = -1

	return {"expression": exp, "OutputIndex": 0}

def exp_particle_info(socket, exp_list):
	field = socket.name
	report_warn("Unsupported node 'Particle Info:%s'. Writing value 0." % field, once=True)
	exp = exp_scalar(0, exp_list)

	return {"expression": exp, "OutputIndex": 0}



DATASMITH_TEXTURE_SIZE = 1024

def add_material_curve2(curve):

	# do some material curves initialization
	material_curves = datasmith_context["material_curves"]
	if material_curves is None:
		material_curves = np.zeros((DATASMITH_TEXTURE_SIZE, DATASMITH_TEXTURE_SIZE, 4))
		datasmith_context["material_curves"] = material_curves
		datasmith_context["material_curves_count"] = 0

	mat_curve_idx = datasmith_context["material_curves_count"]
	datasmith_context["material_curves_count"] = mat_curve_idx + 1
	log.info("writing curve:%s" % mat_curve_idx)

	# write texture from top
	row_idx = DATASMITH_TEXTURE_SIZE - mat_curve_idx - 1
	values = material_curves[row_idx]
	factor = DATASMITH_TEXTURE_SIZE - 1

	# check for curve type, do sampling
	curve_type = type(curve)
	if curve_type == bpy.types.ColorRamp:
		for idx in range(DATASMITH_TEXTURE_SIZE):
			values[idx] = curve.evaluate(idx/factor)

	elif curve_type == bpy.types.CurveMapping:
		curves = curve.curves

		position = 0
		for idx in range(DATASMITH_TEXTURE_SIZE):
			position = idx/factor
			values[idx, 0] = curve.evaluate(curves[0], position)
			values[idx, 1] = curve.evaluate(curves[1], position)
			values[idx, 2] = curve.evaluate(curves[2], position)
			values[idx, 3] = curve.evaluate(curves[3], position)

	return mat_curve_idx

def exp_blackbody(from_node, exp_list):
	n = Node("BlackBody")
	exp_0 = get_expression(from_node.inputs[0], exp_list)
	n.push(exp_input("0", exp_0))
	exp = exp_list.push(n)
	return {"expression": exp}

def exp_shader_to_rgb(socket, exp_list):
	report_warn("Unsupported material node 'Shader To RGB', lighting effects will be lost.", once=True)
	shader_exp = get_expression(socket.node.inputs[0], exp_list)
	basecolor = shader_exp.get("BaseColor")
	emissive = shader_exp.get("EmissiveColor")
	if basecolor and emissive:
		n = Node("Add")
		n.push(exp_input("0", basecolor))
		n.push(exp_input("1", emissive))
		return_exp = exp_list.push(n)
		return {"expression": return_exp}
	elif basecolor:
		return basecolor
	elif emissive:
		return emissive

def exp_clamp(socket, exp_list):
	node = socket.node
	clamp_type = node.clamp_type

	value = get_expression(node.inputs['Value'], exp_list)
	clamp_min = get_expression(node.inputs['Min'], exp_list)
	clamp_max = get_expression(node.inputs['Max'], exp_list)
	
	n = Node("Clamp")
	
	if clamp_type == 'MINMAX':
		n.push(exp_input("0", value))
		n.push(exp_input("1", clamp_min))
		n.push(exp_input("2", clamp_max))
	
	elif clamp_type == 'RANGE':
		# logic for allowing min > max
		# in the end it ends up being using min as min(in_min, in_max) and the same for max
		checked_min = Node("Min")
		checked_min.push(exp_input("0", clamp_min))
		checked_min.push(exp_input("1", clamp_max))
	
		checked_max = Node("Max")
		checked_max.push(exp_input("0", clamp_min))
		checked_max.push(exp_input("1", clamp_max))
	
		n.push(exp_input("0", value))
		n.push(exp_input("1", exp_list.push(checked_min)))
		n.push(exp_input("2", exp_list.push(checked_max)))
	
	else:
		log.error("unsupported clamp type %s" % clamp_type)

	return {"expression": exp_list.push(n)}

def exp_color_ramp(from_node, exp_list):
	ramp = from_node.color_ramp

	idx = add_material_curve2(ramp)

	level = get_expression(from_node.inputs['Fac'], exp_list)

	curve_idx = exp_scalar(idx, exp_list)
	compatibility_mode = datasmith_context["compatibility_mode"]
	if compatibility_mode:
		pixel_offset = exp_scalar(0.5, exp_list)
		vertical_res = exp_scalar(1/DATASMITH_TEXTURE_SIZE, exp_list) # curves texture size
		n = Node("Add")
		n.push(exp_input("0", curve_idx))
		n.push(exp_input("1", pixel_offset))
		curve_y = exp_list.push(n)
		n2 = Node("Multiply")
		n2.push(exp_input("0", curve_y))
		n2.push(exp_input("1", vertical_res))
		curve_v = exp_list.push(n2)

		n3 = Node("AppendVector")
		n3.push(exp_input("0", level))
		n3.push(exp_input("1", curve_v))
		tex_coord = exp_list.push(n3)

		texture_exp = exp_texture("datasmith_curves", "datasmith_curves")
		texture_exp.push(Node("Coordinates", {"expression":tex_coord}))

		return exp_list.push(texture_exp)

	else:
		vertical_res = exp_scalar(DATASMITH_TEXTURE_SIZE, exp_list) # curves texture size
		texture = exp_texture_object("datasmith_curves", exp_list)

		lookup = Node("FunctionCall", { "Function": op_custom_functions["COLOR_RAMP"]})
		lookup.push(exp_input("0", level))
		lookup.push(exp_input("1", curve_idx))
		lookup.push(exp_input("2", vertical_res))
		lookup.push(exp_input("3", texture))
		result = exp_list.push(lookup)

		return result

def exp_curvergb(from_node, exp_list):
	mapping = from_node.mapping
	mapping.initialize()

	idx = add_material_curve2(mapping)

	factor = get_expression(from_node.inputs['Fac'], exp_list)
	color = get_expression(from_node.inputs['Color'], exp_list)

	curve_idx = exp_scalar(idx, exp_list)
	vertical_res = exp_scalar(DATASMITH_TEXTURE_SIZE, exp_list) # curves texture size

	texture = exp_texture_object("datasmith_curves", exp_list)

	lookup = Node("FunctionCall", { "Function": op_custom_functions["CURVE_RGB"]})
	lookup.push(exp_input("0", color))
	lookup.push(exp_input("1", curve_idx))
	lookup.push(exp_input("2", vertical_res))
	lookup.push(exp_input("3", texture))
	blend_exp = exp_list.push(lookup)


	blend = Node("LinearInterpolate")
	blend.push(exp_input("0", color))
	blend.push(exp_input("1", blend_exp))
	blend.push(exp_input("2", factor))
	result = exp_list.push(blend)

	return result

def exp_texture_object(name, exp_list):
	n = Node("TextureObject")
	n.push(Node("Input", {
		"name": "Texture",
		"type": "Texture",
		"val": name,
	}))
	return exp_list.push(n)

MAT_FUNC_BUMP = "/DatasmithBlenderContent/MaterialFunctions/Bump"

def exp_bump(node, exp_list):
	bump_node = Node("FunctionCall", { "Function": MAT_FUNC_BUMP })

	exp_invert = exp_scalar(-1 if node.invert else 1, exp_list)
	push_exp_input(bump_node, "0", exp_invert)

	push_context(MAT_CTX_BUMP)
	inputs = node.inputs
	push_exp_input(bump_node, "1", get_expression(inputs["Strength"], exp_list))
	push_exp_input(bump_node, "2", get_expression(inputs["Distance"], exp_list))
	push_exp_input(bump_node, "3", get_expression(inputs["Height"], exp_list))
	pop_context()

	push_exp_input(bump_node, "4", get_expression(inputs["Normal"], exp_list, skip_default_warn=True))
	return {"expression": exp_list.push(bump_node)}


group_context = {}
def exp_group(socket, exp_list):
	node = socket.node
	node_tree = node.node_tree

	global group_context
	global reverse_expressions
	global cached_nodes

	# store previous global state
	previous_reverse = reverse_expressions
	previous_context = group_context
	previous_cached_nodes = cached_nodes

	# capture group inputs to serve them to the group nodes
	new_context = {}
	for idx, input in enumerate(node.inputs): # use input.identifier
		value_has_links = len(input.links) > 0
		value_exp = get_expression(input, exp_list, force_default=True)
		new_context[input.identifier] = (value_exp, value_has_links)

	group_context = new_context
	reverse_expressions = {}
	cached_nodes = {}

	# search for active output node inside the group node_tree:
	output_node = None
	for node in node_tree.nodes:
		if type(node) == bpy.types.NodeGroupOutput:
			if node.is_active_output or output_node is None:
				output_node = node

	if not output_node:
		report_error("group does not have output node!")

	# now traverse the inner graph
	inner_socket = None
	for input in output_node.inputs:
		if input.identifier == socket.identifier:
			inner_socket = input
	assert(inner_socket)
	inner_exp = get_expression(inner_socket, exp_list)

	group_context = previous_context
	cached_nodes = previous_cached_nodes
	reverse_expressions = previous_reverse
	return inner_exp


def exp_group_input(socket, exp_list, target_socket):
	outer_expression_data = group_context[socket.identifier]
	# if the node inside the group is something like a TEX_IMAGE, and it is
	# connected to a group input that is disconnected in the outside, don't
	# use the group default values, matching what Blender does in this case.
	if type(target_socket) == bpy.types.NodeSocketVector:
		if type(target_socket.default_value) == bpy.types.bpy_prop_array:
			value_has_links = outer_expression_data[1]
			if not value_has_links:
				return None
	outer_expression = outer_expression_data[0]
	return outer_expression

def exp_ambient_occlusion(socket, exp_list):
	socket_name = socket.name
	if socket_name == "Color":
		report_warn("Unsupported material node: AMBIENT_OCCLUSION, exporting plain color instead")
		ao_node = socket.node
		color_input = ao_node.inputs["Color"]
		return get_expression(color_input, exp_list)
	elif socket_name == "AO":
		report_warn("Unsupported material node: AMBIENT_OCCLUSION, exporting 1.0 value instead")
		exp = exp_scalar(1.0, exp_list)
		return { "expression": exp }
	else:
		report_error("Unsupported AMBIENT_OCCLUSION output: %s" % socket_name)


def exp_attribute(socket, exp_list):
	exp = exp_list.push(Node("VertexColor"))
	ret = {"expression": exp, "OutputIndex": 0}
	# average channels if socket is Fac
	if socket.name == "Fac":
		#TODO: check if we should do some colorimetric aware convertion to grayscale
		n = Node("DotProduct")
		n.push(exp_input("0", ret))
		exp_1 = exp_vector((0.333333, 0.333333, 0.333333), exp_list)
		n.push(exp_input("1", exp_1))
		dot_exp = exp_list.push(n)
		ret = {"expression": dot_exp}
	return ret

def exp_vertex_color(socket, exp_list):
	exp = exp_list.push(Node("VertexColor"))
	if socket.name == "Color":
		return {"expression": exp, "OutputIndex": 0}
	elif socket.name == "Alpha":
		return {"expression": exp, "OutputIndex": 4}

def exp_bevel(socket, exp_list):
	report_warn("Unsupported node 'Bevel', writing unmodified normal", once=True)
	exp = get_expression(socket.node.inputs["Normal"], exp_list)
	if not exp:
		exp = {"expression": exp_vector((0, 0, 1), exp_list)}
	return exp

def exp_fresnel(node, exp_list):
	n = Node("FunctionCall", { "Function": op_custom_functions["FRESNEL"]})
	exp_ior = get_expression(node.inputs['IOR'], exp_list)
	n.push(exp_input("0", exp_ior))
	return exp_list.push(n)


MAT_CTX_BUMP = 'BUMP'
context_stack = []
def push_context(context):
	context_stack.append(context)

def pop_context():
	context_stack.pop()

def get_context():
	if context_stack:
		return context_stack[-1]


expression_log_prefix = ""
def get_expression(field, exp_list, force_default=False, skip_default_warn=False):
	# this may return none for fields without default value
	# most of the time blender doesn't have default value for vector
	# node inputs, but it does for scalars and colors
	# TODO: check which cases we should be careful
	global expression_log_prefix
	node = field.node
	log.debug("%s%s:%s/%s:%s" % (
		expression_log_prefix,
		node.type, node.name,
		field.type, field.name,
	))

	if not field.links or not field.links[0].from_socket.enabled:
		if field.type == 'VALUE':
			exp = exp_scalar(field.default_value, exp_list)
			return {"expression": exp, "OutputIndex": 0}
		elif field.type == 'RGBA':
			color_value = field.default_value

			if get_context() == MAT_CTX_NORMAL:
				color_value = (
					color_value[0] * 2.0 - 1.0,
					color_value[1] * 2.0 - 1.0,
					color_value[2] * 2.0 - 1.0,
					color_value[3]
				)
			exp = exp_color(color_value, exp_list)
			return {"expression": exp, "OutputIndex": 0}
		elif field.type == 'VECTOR':
			use_vector_default = force_default or type(field.default_value) in {Vector, Euler}
			# here, we're specifically disarding when the field type is
			# bpy.types.bpy_prop_array. we do that because when that happens,
			# most of the time it is because this socket default value is a
			# custom expression, an example is TEX_IMAGE nodes that by
			# default use the main UV channel if not connected, while
			# TEX_NOISE use TEXCOORD_GENERATED values by default.
			if use_vector_default:
				exp = exp_vector(field.default_value, exp_list)
				return {"expression": exp, "OutputIndex": 0}
		elif field.type == 'SHADER':
			# same as holdout shader
			bsdf = {
				"BaseColor": {"expression": exp_scalar(0.0, exp_list)},
				"Roughness": {"expression": exp_scalar(1.0, exp_list)},
			}
			return bsdf

		if not skip_default_warn:
			log.warn("Node %s (%s) field %s (%s) has no links, and no default value." % (node.name, node.type, field.name, field.type))
		return None

	prev_prefix = expression_log_prefix
	expression_log_prefix += "|   "

	socket = field.links[0].from_socket
	return_exp = get_expression_inner(socket, exp_list, field)
	expression_log_prefix = prev_prefix

	reverse_expressions[socket] = return_exp

	# if a color output is connected to a scalar input, average by using dot product
	if field.type == 'VALUE':
		other_output = field.links[0].from_socket
		if other_output.type == 'RGBA':
			n = Node("FunctionCall", { "Function": MAT_FUNC_RGB_TO_BW })
			push_exp_input(n, "0", return_exp)
			dot_exp = exp_list.push(n)
			return_exp = {"expression": dot_exp}

		elif other_output.type == 'VECTOR':
			n = Node("DotProduct")
			exp_0 = return_exp
			n.push(exp_input("0", exp_0))
			exp_1 = exp_vector((0.333333, 0.333333, 0.333333), exp_list)
			n.push(exp_input("1", {"expression": exp_1}))
			dot_exp = exp_list.push(n)
			return_exp = {"expression": dot_exp}

	elif field.type == 'SHADER':
		other_output = field.links[0].from_socket
		if other_output.type != 'SHADER':
			# maybe a color or a value was connected to a shader socket
			# so we convert whatever value came to a basic emissive shader
			value_exp = return_exp
			exp_base_color = exp_color((0, 0, 0, 1), exp_list)
			return_exp = {
				"BaseColor": exp_base_color,
				"EmissiveColor": value_exp,
			}



	# return_exp can be null, we may need some clearer behavior on corner cases
	return return_exp


def exp_from_cache(cached_node, socket_name):
	output_index = cached_node[1].index(socket_name)
	return {"expression": cached_node[0], "OutputIndex": output_index}

def get_expression_inner(socket, exp_list, target_socket):

	# if this node is already exported, connect to that instead
	# I am considering in
	if socket in reverse_expressions:
		return reverse_expressions[socket]

	node = socket.node
	cached_node = cached_nodes.get(node)
	if cached_node:
		return exp_from_cache(cached_node, socket.name)

	# The cases are ordered like in blender Add menu, others first, shaders second, then the rest

	# these are handled first as these can refer bsdfs
	if node.type == 'GROUP':
		# exp = exp_group(node, exp_list)
		# as exp_group can output shaders (dicts with basecolor/roughness)
		# or other types of values (dicts with expression:)
		# it may be better to return as is and handle internally
		return exp_group(socket, exp_list)# TODO node trees can have multiple outputs

	if node.type == 'GROUP_INPUT':
		return exp_group_input(socket, exp_list, target_socket)

	if node.type == 'REROUTE':
		return get_expression(node.inputs['Input'], exp_list)

	# Shader nodes return a dictionary
	bsdf = None
	if node.type == 'BSDF_PRINCIPLED':
		bsdf = {
			"BaseColor": get_expression(node.inputs['Base Color'], exp_list),
			"Metallic": get_expression(node.inputs['Metallic'], exp_list),
			"Roughness": get_expression(node.inputs['Roughness'], exp_list),
		}
		specular = node.inputs.get("Specular IOR Level")
		if not specular:
			specular = node.inputs["Specular"]
		bsdf["Specular"] = get_expression(specular, exp_list)


		# only add opacity if alpha != 1
		opacity_field = node.inputs['Alpha']
		add_opacity = False
		if len(opacity_field.links) != 0:
			add_opacity = True
		elif opacity_field.default_value != 1:
			add_opacity = True
		if add_opacity:
			bsdf['Opacity'] = get_expression(opacity_field, exp_list)


		emission_field = node.inputs.get('Emission Color')
		if not emission_field:
			emission_field = node.inputs['Emission']
		emission_strength_field = node.inputs['Emission Strength']
		multiply_emission = False
		if len(emission_strength_field.links) != 0:
			multiply_emission = True
		elif emission_strength_field.default_value != 1:
			multiply_emission = True
		if multiply_emission:
			mult = Node("Multiply")
			mult.push(exp_input("0", get_expression(emission_field, exp_list)))
			mult.push(exp_input("1", get_expression(emission_strength_field, exp_list)))
			bsdf["EmissiveColor"] = {"expression": exp_list.push(mult)}
		else:
			bsdf["EmissiveColor"] = get_expression(emission_field, exp_list)

		use_clear_coat = False

		clear_coat_field = node.inputs.get("Coat Weight")
		if not clear_coat_field:
			clear_coat_field = node.inputs["Clearcoat"]
		if len(clear_coat_field.links) != 0:
			use_clear_coat = True
		elif clear_coat_field.default_value != 0:
			use_clear_coat = True
		if use_clear_coat:
			clear_coat_exp = get_expression(clear_coat_field, exp_list)
			clear_coat_roughness_field = node.inputs.get("Coat Roughness")
			if not clear_coat_roughness_field:
				clear_coat_roughness_field = node.inputs["Clearcoat Roughness"]
			clear_coat_roughness_exp = get_expression(clear_coat_roughness_field, exp_list)
			bsdf["ClearCoat"] = clear_coat_exp
			bsdf["ClearCoatRoughness"] = clear_coat_roughness_exp

	if node.type == 'EEVEE_SPECULAR':
		report_warn("EEVEE_SPECULAR incomplete implementation", once=True)
		bsdf = {
			"BaseColor": get_expression(node.inputs['Base Color'], exp_list),
			"Roughness": get_expression(node.inputs['Roughness'], exp_list),
		}

	elif node.type == 'BSDF_DIFFUSE':
		bsdf = {
			"BaseColor": get_expression(node.inputs['Color'], exp_list),
			"Roughness": {"expression": exp_scalar(1.0, exp_list)},
			"Metallic": {"expression": exp_scalar(0.0, exp_list)},
		}
	elif node.type == 'BSDF_TOON':
		report_warn("BSDF_TOON incomplete implementation", once=True)
		bsdf = {
			"BaseColor": get_expression(node.inputs['Color'], exp_list),
			"Roughness": {"expression": exp_scalar(1.0, exp_list)},
			"Metallic": {"expression": exp_scalar(0.0, exp_list)},
		}
	elif node.type == 'BSDF_GLOSSY':
		bsdf = {
			"BaseColor": get_expression(node.inputs['Color'], exp_list),
			"Roughness": get_expression(node.inputs['Roughness'], exp_list),
			"Metallic": {"expression": exp_scalar(1.0, exp_list)},
		}
	elif node.type == 'BSDF_VELVET':
		report_warn("BSDF_VELVET incomplete implementation", once=True)
		bsdf = {
			"BaseColor": get_expression(node.inputs['Color'], exp_list),
			"Roughness": {"expression": exp_scalar(1.0, exp_list)},
		}
	elif node.type == 'BSDF_TRANSPARENT':
		report_warn("BSDF_TRANSPARENT incomplete implementation", once=True)
		bsdf = {
			"BaseColor": get_expression(node.inputs['Color'], exp_list),
			"Refraction": {"expression": exp_scalar(1.0, exp_list)},
			"Opacity": {"expression": exp_scalar(0.0, exp_list)},
		}
	elif node.type == 'BSDF_TRANSLUCENT':
		report_warn("BSDF_TRANSLUCENT incomplete implementation", once=True)
		bsdf = {
			"BaseColor": get_expression(node.inputs['Color'], exp_list),
		}
	elif node.type == 'BSDF_GLASS':
		report_warn("BSDF_GLASS incomplete implementation", once=True)
		bsdf = {
			"BaseColor": get_expression(node.inputs['Color'], exp_list),
			"Metallic": { "expression": exp_scalar(1, exp_list) },
			"Roughness": get_expression(node.inputs['Roughness'], exp_list),
			"Refraction": get_expression(node.inputs['IOR'], exp_list),
			"Opacity": {"expression": exp_scalar(0.5, exp_list)},
		}
	elif node.type == 'BSDF_HAIR':
		report_warn("BSDF_HAIR incomplete implementation", once=True)
		bsdf = {
			"BaseColor": get_expression(node.inputs['Color'], exp_list),
			"Roughness": {"expression": exp_scalar(0.5, exp_list)},
		}
	elif node.type == 'SUBSURFACE_SCATTERING':
		report_warn("SUBSURFACE_SCATTERING incomplete implementation", once=True)
		bsdf = {
			"BaseColor": get_expression(node.inputs['Color'], exp_list)
		}
	elif node.type == 'BSDF_REFRACTION':
		report_warn("BSDF_REFRACTION incomplete implementation", once=True)
		bsdf = {
			"BaseColor": get_expression(node.inputs['Color'], exp_list),
			"Roughness": get_expression(node.inputs['Roughness'], exp_list),
			"Refraction": get_expression(node.inputs['IOR'], exp_list),
			"Opacity": {"expression": exp_scalar(0.5, exp_list)},
		}
	elif node.type == 'BSDF_ANISOTROPIC':
		report_warn("BSDF_ANISOTROPIC incomplete implementation", once=True)
		bsdf = {
			"BaseColor": get_expression(node.inputs['Color'], exp_list),
			"Roughness": get_expression(node.inputs['Roughness'], exp_list),
			# TODO: read inputs 'Anisotropy' and 'Rotation' and 'Tangent'
		}

	elif node.type == 'EMISSION':
		mult = Node("Multiply")
		mult.push(exp_input("0", get_expression(node.inputs['Color'], exp_list)))
		mult.push(exp_input("1", get_expression(node.inputs['Strength'], exp_list)))
		mult_exp = exp_list.push(mult)
		bsdf = {
			"EmissiveColor": {"expression": mult_exp}
		}

	elif node.type == 'HOLDOUT':
		bsdf = {
			"BaseColor": {"expression": exp_vector((0,0,0), exp_list)},
			"Roughness": {"expression": exp_scalar(1.0, exp_list)},
		}

	if bsdf:
		
		assert socket.type == 'SHADER'
		if socket.type == 'SHADER':
			if "Normal" in node.inputs:
				normal_input = node.inputs["Normal"]
				if normal_input.links:
					bsdf["Normal"] = get_expression(normal_input, exp_list)

		"""
		if not "BaseColor" in bsdf:
			bsdf["BaseColor"] = {"expression": exp_vector((0,0,0), exp_list)}
		if not "Roughness" in bsdf:
			bsdf["Roughness"] = {"expression": exp_scalar(1, exp_list)}
		if not "Metallic" in bsdf:
			bsdf["Metallic"] =  {"expression": exp_scalar(0.5, exp_list)}
		if not "Specular" in bsdf:
			bsdf["Specular"] =  {"expression": exp_scalar(0.5, exp_list)}
		if not "EmissiveColor" in bsdf:
			bsdf["EmissiveColor"] = {"expression": exp_vector((0,0,0), exp_list)}

		# we don't want to add opacity if not needed, because that will make the unreal
		# importer set this material's blend mode as translucent
		# if not "Opacity" in bsdf:
			# bsdf["Opacity"] =   {"expression": exp_scalar(1, exp_list)}
		"""
		return bsdf


	if node.type == 'ADD_SHADER':
		report_warn("'Add Shader' is only an approximation, as Unreal's deferred rendering doesn't support this workflow.", once=True)
		expressions = get_expression(node.inputs[0], exp_list)
		assert expressions

		expressions1 = get_expression(node.inputs[1], exp_list)
		assert expressions1

		add_expression = {}

		def make_default_for_field(field_name, exp_list):
			if field_name == "Opacity":
				return {"expression": exp_scalar(1, exp_list)}
			else:
				return {"expression": exp_scalar(0, exp_list)}


		all_keys = {*expressions.keys(), *expressions1.keys()}
		all_keys = list(all_keys)
		all_keys.sort() # we do this to have deterministic outputs

		for name in all_keys:


			exp_a = expressions.get(name)
			exp_b = expressions1.get(name)
			if exp_a and exp_b:

				use_add = name in ["BaseColor", "EmissiveColor"]
				n = Node("Add" if use_add else "LinearInterpolate")
				n.push(exp_input("0", exp_a))
				n.push(exp_input("1", exp_b))
				if not use_add:
					n.push(exp_input("2", {"expression": exp_scalar(0.5, exp_list)}))

				add_expression[name] = {"expression":exp_list.push(n)}
			else:
				exp = exp_a or exp_b
				# for opacity expressions, mix with zero (workaround for transparent nodes added to glossy nodes)
				# for the rest, use the property of the node that has it
				if name == "Opacity":
					n = Node("LinearInterpolate")
					n.push(exp_input("0", exp))
					n.push(exp_input("1", (exp_scalar(1, exp_list), 0)))
					n.push(exp_input("2", (exp_scalar(0.5, exp_list), 0)))
					add_expression[name] = {"expression": exp_list.push(n)}
				else:
					add_expression[name] = exp

			if name != "Normal":
				# Normal expressions can be left disconnected, so we don't enforce them
				assert add_expression[name]

		return add_expression
	if node.type == 'MIX_SHADER':
		report_warn("'Mix Shader' is only an approximation, as Unreal's deferred rendering doesn't support this workflow.", once=True)
		expressions = get_expression(node.inputs[1], exp_list)
		assert expressions

		expressions1 = get_expression(node.inputs[2], exp_list)
		assert expressions1

		if ("Opacity" in expressions) or ("Opacity" in expressions1):
			# if there is opacity in any, both should have opacity
			if "Opacity" not in expressions:
				expressions["Opacity"] = {"expression": exp_scalar(1, exp_list)}
			if "Opacity" not in expressions1:
				expressions1["Opacity"] = {"expression": exp_scalar(1, exp_list)}
		fac_expression = get_expression(node.inputs['Fac'], exp_list)
		for name, exp in expressions1.items():
			if name in expressions:
				n = Node("LinearInterpolate")
				n.push(exp_input("0", expressions[name]))
				n.push(exp_input("1", exp))
				n.push(exp_input("2", fac_expression))
				expressions[name] = {"expression":exp_list.push(n)}
			else:
				expressions[name] = exp
		return expressions


	# from here the return type should be {expression:node_idx, OutputIndex: socket_idx}
	# Add > Input

	if node.type == 'AMBIENT_OCCLUSION':
		return exp_ambient_occlusion(socket, exp_list)
	if node.type == 'ATTRIBUTE':
		return exp_attribute(socket, exp_list)
	if node.type == 'VERTEX_COLOR':
		return exp_vertex_color(socket, exp_list)

	if node.type == 'BEVEL':
		return exp_bevel(socket, exp_list)
	# if node.type == 'CAMERA':
	if node.type == 'FRESNEL':
		exp = exp_fresnel(node, exp_list)
		return {"expression": exp}
	if node.type == 'NEW_GEOMETRY':
		result = exp_new_geometry(socket, exp_list)
		if result:
			return result
	# if node.type == 'HAIR_INFO':
	if node.type == 'LAYER_WEIGHT': # fresnel and facing, with "blend" (power?) and normal param
		return exp_layer_weight(socket, exp_list)
	if node.type == 'LIGHT_PATH':
		return exp_light_path(socket, exp_list)
	if node.type == 'OBJECT_INFO':
		return exp_object_info(socket, exp_list)
	if node.type == 'PARTICLE_INFO':
		return exp_particle_info(socket, exp_list)

	if node.type == 'RGB':
		return exp_rgb(socket, exp_list)
		

	# if node.type == 'TANGENT':
	if node.type == 'TEX_COORD':
		exp = exp_texcoord_node(socket, exp_list)
		if exp:
			return exp

	if node.type == 'UVMAP':
		return exp_uvmap(node, exp_list)
	if node.type == 'VALUE':
		return exp_value(socket, exp_list)
		
	if node.type == 'WIREFRAME':
		return exp_wireframe(socket, exp_list)


	# Add > Texture
	if node.type == 'TEX_BRICK':
		return exp_tex_brick(socket, exp_list)
	if node.type == 'TEX_CHECKER':
		return exp_tex_checker(socket, exp_list)
	# if node.type == 'TEX_ENVIRONMENT':
	if node.type == 'TEX_GRADIENT':
		return exp_tex_gradient(socket, exp_list)
	# if node.type == 'TEX_IES':



	if node.type == 'TEX_IMAGE':
		return exp_tex_image(socket, exp_list)
		
	if node.type == 'TEX_MAGIC':
		return exp_tex_magic(socket, exp_list)
	if node.type == 'TEX_MUSGRAVE':
		return exp_tex_musgrave(socket, exp_list)
	if node.type == 'TEX_NOISE':
		return exp_tex_noise(socket, exp_list)
	if node.type == 'TEX_SKY':
		return exp_tex_sky(socket, exp_list)
	if node.type == 'TEX_VORONOI':
		return exp_tex_voronoi(socket, exp_list)
	if node.type == 'TEX_WAVE':
		return exp_tex_wave(socket, exp_list)
	if node.type == "TEX_WHITE_NOISE":
		return exp_tex_white_noise(socket, exp_list)

	# Add > Color
	if node.type == 'BRIGHTCONTRAST':
		return exp_bright_contrast(node, exp_list)
	if node.type == 'GAMMA':
		return exp_gamma(node, exp_list)
	if node.type == 'HUE_SAT':
		exp = exp_hsv(node, exp_list)
		return {"expression": exp, "OutputIndex": 0}

	if node.type == 'INVERT':
		exp = exp_invert(node, exp_list)
		return {"expression": exp}
	
	if node.type == 'LIGHT_FALLOFF':
		exp = exp_light_falloff(socket, exp_list)
		return {"expression": exp}

	if node.type == 'MIX_RGB':
		exp = exp_mixrgb(node, exp_list)
		return {"expression": exp, "OutputIndex": 0}

	if node.type == 'CURVE_RGB':
		exp = exp_curvergb(node, exp_list)
		return {"expression": exp, "OutputIndex": 0}

	# Add > Vector

	if node.type == 'BUMP':
		return exp_bump(node, exp_list)
	# if node.type == 'DISPLACEMENT':
	if node.type == 'MAPPING':
		return exp_mapping(node, exp_list)
	if node.type == 'NORMAL':
		return exp_normal(socket, exp_list)
	if node.type == 'NORMAL_MAP':
		return exp_normal_map(socket, exp_list)
	# if node.type == 'CURVE_VEC':
	# if node.type == 'VECTOR_DISPLACEMENT':
	if node.type == 'VECT_TRANSFORM':
		return exp_vect_transform(socket, exp_list)
	if node.type == 'VECTOR_ROTATE':
		return exp_vector_rotate(socket, exp_list)

	# Add > Converter

	# if node.type == 'WAVELENGTH':
	if node.type == 'BLACKBODY':
		return exp_blackbody(node, exp_list)

	if node.type == 'CLAMP':
		return exp_clamp(socket, exp_list)

	if node.type == 'VALTORGB':
		exp = exp_color_ramp(node, exp_list)
		return {"expression": exp, "OutputIndex": 0}


	if node.type == 'COMBRGB':
		return exp_make_vec3(socket, exp_list)
	if node.type == 'COMBXYZ':
		return exp_make_vec3(socket, exp_list)
	if node.type == 'COMBHSV':
		return exp_make_hsv(socket, exp_list)
	if node.type == 'COMBINE_COLOR':
		return exp_combine_color(socket, exp_list)

	if node.type == 'SEPRGB':
		return exp_break_vec3(socket, exp_list)
	if node.type == 'SEPXYZ':
		return exp_break_vec3(socket, exp_list)
	if node.type == 'SEPHSV':
		return exp_break_hsv(socket, exp_list)
	if node.type == 'SEPARATE_COLOR':
		return exp_separate_color(socket, exp_list)

	if node.type == 'RGBTOBW':
		return exp_rgb_to_bw(socket, exp_list)
	if node.type == 'MAP_RANGE':
		return exp_map_range(socket, exp_list)
	if node.type == 'MATH':
		return exp_math(node, exp_list)
	if node.type == 'VECT_MATH':
		return exp_vect_math(node, exp_list)

	if node.type == 'SHADERTORGB':
		return exp_shader_to_rgb(socket, exp_list)
	# Others:
	if node.type == 'MIX':
		return exp_mix(socket, exp_list)

	# if node.type == 'SCRIPT':


	report_error("Node %s:%s not handled" % (node.type, socket.name))
	exp = exp_scalar(0, exp_list)
	return {"expression": exp}


config_always_twosided = False
material_hint_twosided = False
# if we try to use textures that end up being connected to the normal input of
# a material in UE, UE tries to be smart and flag them as normal maps, but
# sometimes these aren't normal maps. for example when we use a texture to
# blend between other two. in those cases we want to tell unreal to NOT flag
# these as normal maps, and the only way to do this is to connect them to a
# basecolor or specular socket too
whitelisted_textures = []

MAT_FUNC_PASSTHROUGH = "/DatasmithBlenderContent/MaterialFunctions/Passthrough"

def pbr_nodetree_material(material):

	log.info("Collecting material: "+material.name)
	n = Node("UEPbrMaterial")
	n['name'] = sanitize_name(material.name)

	output_node = (
		material.node_tree.get_output_node('EEVEE')
		or material.node_tree.get_output_node('ALL')
		or material.node_tree.get_output_node('CYCLES')
	)

	if not output_node:
		report_warn("Material %s with use_nodes does not have nodes", material.name, once=True)
		return n

	exp_list = Node("Expressions")
	n.push(exp_list)
	global material_hint_twosided
	material_hint_twosided = False

	surface_field = output_node.inputs['Surface']
	volume_field = output_node.inputs['Volume']
	# TODO: also check for output_node.inputs['Displacement']

	expressions = None
	if volume_field.links and not surface_field.links:
		report_warn("Material %s has volume nodes, which are unsupported. Writing transparent material.", material.name, once=True)
		expressions = {
			"BaseColor":  {"expression": exp_vector((0,0,0), exp_list)},
			"Refraction": {"expression": exp_scalar(1.0, exp_list)},
			"Opacity":    {"expression": exp_scalar(0.0, exp_list)},
		}


	global whitelisted_textures
	whitelisted_textures = []
	
	if not expressions:
		# here we decided using surface nodes, if there is nothing connected, the fallback behaviour is
		# using the blackout node (already happens in get_expression)

		# reverse_expressions is used to find expressions with socket outputs that were connected
		# to another node previously, so we reuse them. We reset it when processing a new material
		# and have some kind of "stack" when we are processing node groups
		global reverse_expressions
		reverse_expressions = dict()
		
		# the result of this call is expected to be a dictionary, as it is a shader socket, and should have
		# fields like "BaseColor", "Roughness", etc...
		expressions = get_expression(surface_field, exp_list)

	# we want to do some post-process on the actual outputs, so we link the
	# whitelisted materials to a socket other than the normal, so they don't
	# get marked as normal maps


	first_passthrough_exp = None
	# last_passthrough should be a whole node, because we will add things to
	# it after adding it to exp_list
	last_passthrough = None
	for tex in whitelisted_textures:
		# maybe we should filter these if they are sRGB or not to decide
		# between connecting them to the basecolor (and get marked as
		# diffuse) or specular (and get marked as such), but not today.
		passthrough = Node("FunctionCall", {"Function": MAT_FUNC_PASSTHROUGH})
		passthrough_exp = exp_list.push(passthrough)
		if last_passthrough:
			push_exp_input(last_passthrough, "1", passthrough_exp)
		if not first_passthrough_exp:
			first_passthrough_exp = passthrough_exp
		push_exp_input(passthrough, "0", tex)
		last_passthrough = passthrough

	if first_passthrough_exp:
		prev_base_color = expressions["BaseColor"]
		main_passthrough = Node("FunctionCall", {"Function": MAT_FUNC_PASSTHROUGH})
		push_exp_input(main_passthrough, "0", prev_base_color)
		push_exp_input(main_passthrough, "1", first_passthrough_exp)
		expressions["BaseColor"] = {"expression": exp_list.push(main_passthrough) }

	can_be_twosided = True

	blend_method = material.blend_method
	if blend_method == 'CLIP':
		n.push('\n\t\t<Blendmode value="1"/>')
		n.push('\n\t\t<OpacityMaskClipValue value="%f"/>' % max(material.alpha_threshold, 0.01))
	elif blend_method == 'HASHED': 
		n.push('\n\t\t<Blendmode value="1"/>')
		n.push('\n\t\t<OpacityMaskClipValue value="0.5"/>')
		alpha_exp = expressions.get("Opacity")
		if alpha_exp:
			hashed_exp = Node("FunctionCall", { "Function": "/Engine/Functions/Engine_MaterialFunctions02/Utility/DitherTemporalAA" })

			push_exp_input(hashed_exp, "0", alpha_exp)
			new_alpha_exp = exp_list.push(hashed_exp)
			expressions["Opacity"] = new_alpha_exp

	# maybe we can check this earlier and decide
	# to push a temporal hash mask node in the material?
	elif blend_method == 'BLEND':
		n.push('\n\t\t<Blendmode value="2"/>')
	else: 
		# blend_method is only valid for Eevee, so we end up checking for
		# Opacity in expressions to handle Cycles materials too. In this case
		# we want to turn off two-sidedness because it matches better how the
		# transparency works on cycles. and while we know that people sets
		# this up for eevee, they don't do when setting a glass material in
		# cycles for example

		if "Opacity" in expressions:
			can_be_twosided = False

	# here we add those BaseColor, Roughness, etc... values to the UEPbrMaterial node
	# we don't do it before because blend_method HASHED adds more expressions
	for key, value in expressions.items():
		n.push(exp_output(key, value))

	shading_model = "DefaultLit"
	if "ClearCoat" in expressions:
		shading_model = "ClearCoat"
	# shading_model can be: "DefaultLit", "ThinTranslucent", "Subsurface", "ClearCoat"
	if shading_model != "DefaultLit":
		n.push('\n\t\t<ShadingModel value="%s"/>' % shading_model)

	if config_always_twosided:
		if can_be_twosided:
			material_hint_twosided = True

	# we always want to skip two-sidedness if the user explicitly
	# turned on backface culling
	if material.use_backface_culling:
		material_hint_twosided = False

	# this flag is enabled if any material hinted for two-sidedness or if the
	# material is opaque and the user set to always write two-sided mats
	if material_hint_twosided:
		n.push('\n\t\t<TwoSided enabled="True"/>')

	return n


def pbr_default_material():
	n = Node("UEPbrMaterial")
	n["name"] = "DefaultMaterial"
	exp_list = Node("Expressions")
	grey = 0.906332
	basecolor_idx = exp_color((grey, grey, grey, 1.0), exp_list)
	roughness_idx = exp_scalar(0.4, exp_list)
	n.push(exp_list)
	n.push(Node("BaseColor", {
		"expression": basecolor_idx,
		"OutputIndex": "0"
		}))
	n.push(Node("Roughness", {
		"expression": roughness_idx,
		"OutputIndex": "0"
		}))
	return n

def pbr_basic_material(material):
	n = Node("UEPbrMaterial")
	n['name'] = sanitize_name(material.name)
	exp_list = Node("Expressions")
	n.push(exp_list)

	basecolor_idx = exp_color(material.diffuse_color, exp_list)
	roughness_idx = exp_scalar(material.roughness, exp_list)
	metallic_idx = exp_scalar(material.metallic, exp_list)
	specular_idx = exp_scalar(material.specular_intensity, exp_list)

	n.push(Node("BaseColor", {
		"expression": basecolor_idx,
		"OutputIndex": "0"
		}))
	n.push(Node("Roughness", {
		"expression": roughness_idx,
		"OutputIndex": "0"
		}))
	n.push(Node("Metallic", {
		"expression": metallic_idx,
		"OutputIndex": "0"
		}))
	n.push(Node("Specular", {
		"expression": specular_idx,
		"OutputIndex": "0"
		}))

	return n


cached_nodes = {}
def collect_pbr_material(mat_with_owner):
	datasmith_context["material_owner"] = mat_with_owner[1]
	global cached_nodes
	cached_nodes = {}
	material = mat_with_owner[0]
	if material is None:
		log.debug("creating default material")
		return pbr_default_material()
	if not material.use_nodes:
		log.debug("creating material %s without nodes" % material.name)
		return pbr_basic_material(material)
	log.debug("creating material %s with node_tree " % material.name)
	return pbr_nodetree_material(material)





def fill_umesh(umesh, bl_mesh):
	# create copy to triangulate
	m = bl_mesh.copy()

	# triangulate with bmesh api
	bm = bmesh.new()
	bm.from_mesh(m)
	bmesh.ops.triangulate(bm, faces=bm.faces[:])

	bm.loops.layers.uv.verify() # this ensures that an UV layer exists

	bm.to_mesh(m)
	bm.free()
	
	m.calc_normals_split()
	m.transform(matrix_datasmith)
	
	vertices = m.vertices
	num_vertices = len(vertices)

	vertices_array = np.empty(num_vertices* 3, np.float32)
	vertices.foreach_get("co", vertices_array)

	umesh.vertices = vertices_array.reshape(-1, 3)

	# not sure if this is the best way to read normals
	m.calc_loop_triangles()
	loop_triangles = m.loop_triangles
	num_triangles = len(loop_triangles)
	num_loops = num_triangles * 3

	triangles = np.empty(num_loops, np.uint32)
	loop_triangles.foreach_get('vertices', triangles)
	umesh.triangles = triangles

	material_slots = np.empty(num_triangles, np.uint32)
	loop_triangles.foreach_get('material_index', material_slots)
	umesh.tris_material_slot = material_slots

	normals = np.empty(num_loops * 3, np.float32)
	loop_triangles.foreach_get('split_normals', normals)
	normals = normals.reshape((-1, 3))

	# in case vert has invalid normals, put some dummy data so UE doesn't try to recalculate
	normals_drift = np.linalg.norm(normals, axis=1) - 1
	normals_faulty = np.abs(normals_drift) > 0.008
	normals[normals_faulty] = (0, 0, 1)

	umesh.vertex_normals = np.ascontiguousarray(normals, "<f4")

	#finish inline mesh_copy_triangulate
	if len(bl_mesh.materials) == 0:
		umesh.materials[0] = 'DefaultMaterial'
	else:
		for idx, mat in enumerate(bl_mesh.materials):
			material_name = getattr(mat, 'name', 'DefaultMaterial')
			umesh.materials[idx] = sanitize_name(material_name)

	smoothing_groups = m.calc_smooth_groups()[0];
	umesh.tris_smoothing_group = np.array(smoothing_groups, np.uint32)
	umesh.tris_smoothing_group = np.zeros(num_triangles, np.uint32)

	uvs = []
	num_uvs = min(8, len(m.uv_layers))
	active_uv = 0
	for idx in range(num_uvs):
		if m.uv_layers[idx].active_render:
			active_uv = idx
	for idx in range(num_uvs):
		uv_idx = idx # swap active_render UV with channel 0
		if uv_idx == 0:
			uv_idx = active_uv
		elif uv_idx == active_uv:
			uv_idx = 0

		uv_data = m.uv_layers[uv_idx].data
		uv_loops = np.empty(len(uv_data) * 2, np.float32)
		uv_data.foreach_get("uv", uv_loops)
		uv_loops = uv_loops.reshape((-1, 2))

		uv_channel = uv_loops
		uv_channel[:,1] = 1 - uv_channel[:,1]
		uvs.append(uv_channel)
	umesh.uvs = uvs

	if (m.vertex_colors):
		vertex_colors = np.empty(num_loops * 4)
		m.vertex_colors[0].data.foreach_get("color", vertex_colors)
		vertex_colors *= 255
		vertex_colors = vertex_colors.reshape((-1, 4))
		vertex_colors[:, [0, 2]] = vertex_colors[:, [2, 0]]
		umesh.vertex_colors = vertex_colors.astype(np.uint8)

	bpy.data.meshes.remove(m)
	return umesh

def fix_uv(data):
	return (data[0], 1-data[1])

def color_uchar(data):
	return (
		int(data[0]*255),
		int(data[1]*255),
		int(data[2]*255),
		int(data[3]*255),
	)

def node_transform(mat):
	loc, rot, scale = mat.decompose()
	n = Node('Transform')
	n['tx'] = f(loc.x)
	n['ty'] = f(loc.y)
	n['tz'] = f(loc.z)
	n['qw'] = f(rot.w)
	n['qx'] = f(rot.x)
	n['qy'] = f(rot.y)
	n['qz'] = f(rot.z)
	n['sx'] = f(scale.x)
	n['sy'] = f(scale.y)
	n['sz'] = f(scale.z)
	return n

def transform_to_xml(mat):
	loc, rot, scale = mat.decompose()
	parts = [
		'\t<Transform tx="', f(loc.x),
		'" ty="', f(loc.y),
		'" tz="', f(loc.z),
		'" qw="', f(rot.w),
		'" qx="', f(rot.x),
		'" qy="', f(rot.y),
		'" qz="', f(rot.z),
		'" sx="', f(scale.x),
		'" sy="', f(scale.y),
		'" sz="', f(scale.z),
		'"/>\n',
	]
	return "".join(parts)
	
def f(value):
	return '{:6f}'.format(value)

def collect_object(
	bl_obj,
	name_override=None,
	instance_matrix=None,
	selected_only=False,
	apply_modifiers=False,
	export_animations=False,
	export_metadata=False,
):

	n = Node('Actor')

	n['name'] = sanitize_name(bl_obj.name)
	if name_override:
		n['name'] = name_override
	log.debug("reading object:%s" % bl_obj.name)

	n['layer'] = bl_obj.users_collection[0].name_full


	child_nodes = []

	for child in bl_obj.children:
		new_obj = collect_object(child,
			selected_only=selected_only,
			apply_modifiers=apply_modifiers,
			export_animations=export_animations,
			export_metadata = export_metadata,
		)
		if new_obj:
			child_nodes.append(new_obj)

	# if we are exporting only selected items, we should only continue
	# if this is selected, or if there is any child that needs this
	# object to be placed in hierarchy
	# TODO: collections don't work this way, investigate (export chair from classroom)
	export_empty_because_unselected = False
	if selected_only:
		is_selected = bl_obj in bpy.context.selected_objects
		if selected_only and not is_selected:
			if len(child_nodes) == 0:
				# We skip this object as it is not selected, and has no children selected
				return None
			else:
				# we aren't selected, but we have selected children, so create minimal object
				export_empty_because_unselected = True

	# from here, we're absolutely sure that this object should be exported

	obj_mat = collect_object_transform(bl_obj, instance_matrix)
	transform = node_transform(obj_mat)

	# if an object is not selected but is in hierarchy, we don't write data for it
	if not export_empty_because_unselected:
		# TODO: use instanced static meshes
		depsgraph = datasmith_context["depsgraph"]

		if bl_obj.is_instancer:
			dups = []
			dup_idx = 0
			for dup in depsgraph.object_instances:
				if dup.parent and dup.parent.original == bl_obj:
					dup_name = '%s_%s' % (dup.instance_object.original.name, dup_idx)
					dup_name = sanitize_name(dup_name)
					new_obj = collect_object(
						dup.instance_object.original,
						instance_matrix=dup.matrix_world.copy(),
						name_override=dup_name,
						selected_only=False, # if is instancer, maybe all child want to be instanced
						apply_modifiers=False, # if is instancer, applying modifiers may end in a lot of meshes
						export_animations=False, # TODO: test how would animation work mixed with instancing
						export_metadata=False,
					)
					child_nodes.append(new_obj)
					#dups.append((dup.instance_object.original, dup.matrix_world.copy()))
					dup_idx += 1

		collect_object_custom_data(bl_obj, n, apply_modifiers, obj_mat, depsgraph, export_metadata)

	# todo: maybe make some assumptions? like if obj is probe or reflection, don't add to animated objects list

	if export_animations:
		datasmith_context["anim_objects"].append((bl_obj, n["name"], obj_mat))

	if export_metadata:
		collect_object_metadata(n["name"], "Actor", bl_obj)

	# just to make children appear last
	n.push(transform)

	if len(child_nodes) > 0:
		children_node = Node("children");
		# strange, this visibility flag is read from the "children" node. . . 
		children_node["visible"] = not bl_obj.hide_render
		for child in child_nodes:
			if child:
				children_node.push(child)
		n.push(children_node)


	return n


def collect_object_custom_data(bl_obj, n, apply_modifiers, obj_mat, depsgraph, export_metadata=False):
		# I think that these should be ordered by how common they are
		if bl_obj.type == 'EMPTY':
			pass
		elif bl_obj.type == 'MESH':
			bl_mesh = bl_obj.data
			bl_mesh_name = bl_mesh.name

			if bl_obj.modifiers and apply_modifiers:
				bl_mesh = bl_obj.evaluated_get(depsgraph).to_mesh()
				bl_mesh_name = "%s__%s" % (bl_obj.name, bl_mesh.name)

			if bl_mesh.library:
				libraries_dict = datasmith_context["libraries"]
				prefix = libraries_dict.get(bl_mesh.library)

				if prefix is None:
					lib_filename = bpy.path.basename(bl_mesh.library.filepath)
					lib_clean_name = bpy.path.clean_name(lib_filename)
					prefix = lib_clean_name.strip("_")
					if prefix.endswith("_blend"):
						prefix = prefix[:-5] # leave the underscore
					next_prefix = prefix
					try_count = 1
					libraries_prefixes = libraries_dict.values()
					# just to reaaally make sure there are no collisions
					while next_prefix in libraries_prefixes:
						next_prefix = "%s%d_" % (prefix, try_count)
						try_count += 1
					prefix = next_prefix
					libraries_dict[bl_mesh.library] = prefix
				bl_mesh_name = prefix + bl_mesh_name


			bl_mesh_name = sanitize_name(bl_mesh_name)
			meshes = datasmith_context["meshes"]
			umesh = None
			for mesh in meshes:
				if bl_mesh_name == mesh.name:
					umesh = mesh

			if umesh == None:
				if len(bl_mesh.polygons) > 0:
					umesh = UDMesh(bl_mesh_name)
					meshes.append(umesh)
					fill_umesh(umesh, bl_mesh)

					if export_metadata:
						collect_object_metadata(n["name"], "StaticMesh", bl_mesh)

					material_list = datasmith_context["materials"]
					if len(bl_obj.material_slots) == 0:
						material_list.append((None, bl_obj))
					else:
						for slot in bl_obj.material_slots:
							material_list.append((slot.material, bl_obj))

			if umesh:
				n.name = 'ActorMesh'
				mesh_name = umesh.name
				log.error("collecting mesh: %s" % mesh_name)
				n.push(Node('mesh', {'name': mesh_name}))

				for idx, slot in enumerate(bl_obj.material_slots):
					if slot.link == 'OBJECT':
						material_list.append((slot.material, bl_obj))
						safe_name = sanitize_name(slot.material.name)
						n.push(Node('material', {'id':idx, 'name':safe_name}))

		elif bl_obj.type == 'CURVE':

			# as we cannot get geometry before evaluating depsgraph,
			# we better evaluate first, and check if it has polygons.
			# this might end with repeated geometry, gotta find solution.
			# maybe cache "evaluated curve without modifiers"?

			bl_mesh = bl_obj.evaluated_get(depsgraph).to_mesh()
			if bl_mesh and len(bl_mesh.polygons) > 0:
				bl_curve = bl_obj.data
				bl_curve_name = "%s_%s" % (bl_curve.name, bl_obj.name)
				bl_curve_name = sanitize_name(bl_curve_name)

				umesh = UDMesh(bl_curve_name)
				meshes = datasmith_context["meshes"]
				meshes.append(umesh)

				fill_umesh(umesh, bl_mesh)
				material_list = datasmith_context["materials"]

				n.name = 'ActorMesh'
				n.push(Node('mesh', {'name': umesh.name}))

				if len(bl_obj.material_slots) == 0:
					material_list.append((None, bl_obj))
				else:
					for idx, slot in enumerate(bl_obj.material_slots):
						material_list.append((slot.material, bl_obj))
						if slot.link == 'OBJECT':
							safe_name = sanitize_name(slot.material.name)
							n.push(Node('material', {'id':idx, 'name':safe_name}))

		elif bl_obj.type == 'FONT':

			# we could get bl_obj.to_mesh(), but if we do it that way, we
			# won't get the modifiers applied, maybe we can cache the mesh
			# to reuse it if there are no modifiers?
			if apply_modifiers:
				bl_mesh = bl_obj.evaluated_get(depsgraph).to_mesh()
			else:
				bl_mesh = bl_obj.to_mesh()

			if bl_mesh and len(bl_mesh.polygons) > 0:
				bl_data = bl_obj.data
				bl_data_name = "%s_%s" % (bl_data.name, bl_obj.name)
				bl_data_name = sanitize_name(bl_data_name)

				umesh = UDMesh(bl_data_name)
				meshes = datasmith_context["meshes"]
				meshes.append(umesh)

				fill_umesh(umesh, bl_mesh)
				material_list = datasmith_context["materials"]

				n.name = 'ActorMesh'
				n.push(Node('mesh', {'name': umesh.name}))

				if len(bl_obj.material_slots) == 0:
					material_list.append((None, bl_obj))
				else:
					for idx, slot in enumerate(bl_obj.material_slots):
						material_list.append((slot.material, bl_obj))
						if slot.link == 'OBJECT':
							safe_name = sanitize_name(slot.material.name)
							n.push(Node('material', {'id':idx, 'name':safe_name}))

		elif bl_obj.type == 'CAMERA':

			bl_cam = bl_obj.data
			n.name = 'Camera'

			# TODO
			# look_at_actor = sanitize_name(bl_cam.dof.focus_object.name)

			use_dof = "1" if bl_cam.dof.use_dof else "0"
			n.push(Node("DepthOfField", {"enabled": use_dof}))
			n.push(node_value('SensorWidth', bl_cam.sensor_width))
			# blender doesn't have per-camera aspect ratio
			sensor_aspect_ratio = 1.777778
			n.push(node_value('SensorAspectRatio', sensor_aspect_ratio))
			n.push(node_value('FocusDistance', bl_cam.dof.focus_distance * 100)) # to centimeters
			n.push(node_value('FStop', bl_cam.dof.aperture_fstop))
			n.push(node_value('FocalLength', bl_cam.lens))
			n.push(Node('Post'))
		# maybe move up as lights are more common?
		elif bl_obj.type == 'LIGHT':

			bl_light = bl_obj.data
			n.name = 'Light'

			n['type'] = 'PointLight'
			n['enabled'] = '1'
			n.push(node_value('SourceSize', bl_light.shadow_soft_size * 100))
			light_intensity = bl_light.energy
			light_attenuation_radius = 100 * math.sqrt(bl_light.energy)
			light_color = bl_light.color
			light_intensity_units = 'Lumens' # can also be 'Candelas' or 'Unitless'
			light_use_custom_distance = bl_light.use_custom_distance

			if bl_light.type == 'SUN':
				n['type'] = 'DirectionalLight'
				light_use_custom_distance = False
				# light_intensity = bl_light.energy # suns are in lux

			elif bl_light.type == 'SPOT':
				n['type'] = 'SpotLight'
				outer_cone_angle = bl_light.spot_size * 180 / (2*math.pi)
				inner_cone_angle = outer_cone_angle * (1 - bl_light.spot_blend)
				if inner_cone_angle < 0.0001:
					inner_cone_angle = 0.0001
				n.push(node_value('InnerConeAngle', inner_cone_angle))
				n.push(node_value('OuterConeAngle', outer_cone_angle))

				spot_use_candelas = False # TODO: test this thoroughly
				if spot_use_candelas:
					light_intensity_units = 'Candelas'
					light_intensity = bl_light.energy * 0.08 # came up with this constant by brute force
					# blender watts unit match ue4 lumens unit, but in spot lights the brightness
					# changes with the spot angle when using lumens while candelas do not.

			elif bl_light.type == 'AREA':
				n['type'] = 'AreaLight'

				size_w = size_h = bl_light.size
				if bl_light.shape == 'RECTANGLE' or bl_light.shape == 'ELLIPSE':
					size_h = bl_light.size_y

				n.push(Node('Shape', {
					"type": 'None', # can be Rectangle, Disc, Sphere, Cylinder, None
					"width": size_w * 100, # convert to cm
					"length": size_h * 100,
					"LightType": "Rect", # can be "Point", "Spot", "Rect"
				}))
			if light_use_custom_distance:
				light_attenuation_radius = 100 * bl_light.cutoff_distance
			# TODO: check how lights work when using a node tree
			# if bl_light.use_nodes and bl_light.node_tree:

			# 	node = bl_light.node_tree.nodes['Emission']
			# 	light_color = node.inputs['Color'].default_value
			# 	light_intensity = node.inputs['Strength'].default_value # have to check how to relate to candelas
			# 	log.error("unsupported: using nodetree for light " + bl_obj.name)

			n.push(node_value('Intensity', light_intensity))
			n.push(node_value('AttenuationRadius', light_attenuation_radius))
			n.push(Node('IntensityUnits', {'value': light_intensity_units}))
			n.push(Node('Color', {
				'usetemp': '0',
				'temperature': '6500.0',
				'R': f(light_color[0]),
				'G': f(light_color[1]),
				'B': f(light_color[2]),
				}))
		elif bl_obj.type == 'LIGHT_PROBE':
			# TODO: LIGHT PROBE
			n.name = 'CustomActor'
			bl_probe = bl_obj.data
			if bl_probe.type == 'PLANAR':
				n["PathName"] = "/DatasmithBlenderContent/Blueprints/BP_BlenderPlanarReflection"

			elif bl_probe.type == 'CUBEMAP':
				## we could also try using min/max if it makes a difference
				_, _, obj_scale = obj_mat.decompose()
				avg_scale = (obj_scale.x + obj_scale.y + obj_scale.z) * 0.333333

				if bl_probe.influence_type == 'BOX':
					n["PathName"] = "/DatasmithBlenderContent/Blueprints/BP_BlenderBoxReflection"


					falloff = bl_probe.falloff # this value is 0..1
					transition_distance = falloff * avg_scale
					prop = Node("KeyValueProperty", {"name": "TransitionDistance", "type":"Float", "val": "%.6f"%transition_distance})
					n.push(prop)
				else: # if bl_probe.influence_type == 'ELIPSOID'
					n["PathName"] = "/DatasmithBlenderContent/Blueprints/BP_BlenderSphereReflection"
					probe_radius = bl_probe.influence_distance * 100 * avg_scale
					radius = Node("KeyValueProperty", {"name": "Radius", "type":"Float", "val": "%.6f"%probe_radius})
					n.push(radius)
			elif bl_probe.type == 'GRID':
				# for now we just export to custom object, but it doesn't affect the render on
				# the unreal side. would be cool if it made a difference by setting volumetric importance volume
				n["PathName"] = "/DatasmithBlenderContent/Blueprints/BP_BlenderGridProbe"

				# blender influence_distance is outwards, maybe we should grow the object to match?
				# outward_influence would be 1.0 + influence_distance / size maybe?
				# obj_mat = obj_mat @ Matrix.Scale(outward_influence, 4)

			else:
				log.error("unhandled light probe")
		elif bl_obj.type == 'ARMATURE':
			pass
		else:
			log.error("unrecognized object type: %s" % bl_obj.type)



def collect_object_transform(bl_obj, instance_matrix=None):
	mat_basis = instance_matrix or bl_obj.matrix_world
	obj_mat = matrix_datasmith @ mat_basis @ matrix_datasmith.inverted()

	if bl_obj.type in 'CAMERA' or bl_obj.type == 'LIGHT':
		obj_mat = obj_mat @ matrix_forward
	elif bl_obj.type == 'LIGHT_PROBE':
		bl_probe = bl_obj.data
		if bl_probe.type == 'PLANAR':
			obj_mat = obj_mat @ Matrix.Scale(0.05, 4)
		elif bl_probe.type == 'CUBEMAP':
			if bl_probe.influence_type == 'BOX':
				size = bl_probe.influence_distance * 100
				obj_mat = obj_mat @ Matrix.Scale(size, 4)

	obj_mat.freeze() # TODO: check if this is needed
	return obj_mat


def collect_object_metadata(obj_name, obj_type, obj):
	metadata = None
	found_metadata = False
	obj_props = obj.keys()
	for prop_name in obj_props:
		if prop_name in {"_RNA_UI", "cycles", "cycles_visibility"}:
			continue
		if prop_name.startswith("archipack_"):
			continue
		if metadata is None:
			names = (obj_type, obj_name)
			metadata = Node("MetaData", {"name": "%s_%s"%names, "reference":"%s.%s"%names } )

		out_value = prop_value = obj[prop_name]
		prop_type = type(prop_value)
		out_type = None
		if prop_type is str:
			out_type = "String"
		elif prop_type in {float, int}:
			out_type = "Float"
			out_value = f(prop_value)
		elif prop_type is idprop.types.IDPropertyArray:
			out_type = "Vector"
			out_value = ",".join(f(v) for v in prop_value)
		elif prop_type is idprop.types.IDPropertyGroup:
			if len(out_value) == 0:
				continue
			out_type = "String"
			out_value = str(prop_value.to_dict())
		# elif prop_type is list:
			# archipack uses some list props, I don't think these are useful
			# but we should check if there's something specific we should do.
		else:
			log.error("%s: %s has unsupported metadata with type:%s" % (obj_type, obj_name, prop_type))
			# write as string, and sanitize output
			out_type = "String"
			out_value = str(out_value)

		if out_type == "String":
			out_value = out_value.replace("<", "&lt;")
			out_value = out_value.replace(">", "&gt;")
			out_value = out_value.replace('"', "&quot;")

		kvp = Node("KeyValueProperty", {"name": prop_name, "val": out_value, "type": out_type } )
		metadata.push(kvp)
		found_metadata = True
	if found_metadata:
		datasmith_context["metadata"].append(metadata)

def node_value(name, value):
	return Node(name, {'value': '%f' % value })
def f(value):
	return '%f' % value

def collect_environment(world):
	if not world:
		return
	if not world.use_nodes:
		return

	log.info("Collecting environment")
	nodes = world.node_tree
	output = nodes.get_output_node('EEVEE') or nodes.get_output_node('ALL') or nodes.get_output_node('CYCLES')
	background_node = output.inputs['Surface'].links[0].from_node
	while background_node.type == "REROUTE":
		background_node = background_node.inputs[0].links[0].from_node

	if not 'Color' in background_node.inputs:
		return
	if not background_node.inputs['Color'].links:
		return
	source_node = background_node.inputs['Color'].links[0].from_node
	if source_node.type != 'TEX_ENVIRONMENT':
		log.info("Background texture is "+ source_node.type)
		return

	log.info("found environment, collecting...")
	image = source_node.image

	tex_name = sanitize_name(image.name)
	get_or_create_texture(tex_name, image)

	tex_node = Node("Texture", {
		"tex": tex_name,
		})

	n2 = Node("Environment", {
		"name": "world_environment_lighting",
		"label": "world_environment_lighting",
		})
	n2.push(tex_node)
	n2.push(Node("Illuminate", {
		"enabled": "1"
		}))
	n = Node("Environment", {
		"name": "world_environment_background",
		"label": "world_environment_background",
		})
	n.push(tex_node)
	n.push(Node("Illuminate", {
		"enabled": "0"
		}))

	return [n, n2]



def get_file_header():

	n = Node('DatasmithUnrealScene')

	from . import bl_info
	plugin_version = bl_info['version']
	plugin_version_string = "%s.%s.%s" % plugin_version
	n.push(Node('Version', children=[plugin_version_string]))
	n.push(Node('SDKVersion', children=['4.24E0']))
	n.push(Node('Host', children=['Blender']))

	blender_version = bpy.app.version_string
	n.push(Node('Application', {
		'Vendor': 'Blender Foundation',
		'ProductName': 'Blender',
		'ProductVersion': blender_version,
		}))

	import os, platform
	os_name = "%s %s" % (platform.system(), platform.release())
	user_name = os.getlogin()

	n.push(Node('User', {
		'ID': user_name,
		'OS': os_name,
		}))
	return n


# in_type can be SRGB, LINEAR or NORMAL
def get_or_create_texture(in_name, in_image, in_type='SRGB'):
	textures = datasmith_context["textures"]
	for name, tex, _ in textures:
		if name == in_name:
			return tex
	log.debug("collecting texture:%s" % in_name)

	new_tex = (in_name, in_image, in_type)
	textures.append(new_tex)
	return new_tex

def get_datasmith_curves_image():
	log.info("baking curves")

	curve_list = datasmith_context["material_curves"]
	if curve_list is None:
		return None

	curves_image = None
	if "datasmith_curves" in bpy.data.images:
		curves_image = bpy.data.images["datasmith_curves"]
	else:
		curves_image = bpy.data.images.new(
			"datasmith_curves",
			DATASMITH_TEXTURE_SIZE,
			DATASMITH_TEXTURE_SIZE,
			alpha=True,
			float_buffer=True
		)
		curves_image.colorspace_settings.is_data = True
		curves_image.file_format = 'OPEN_EXR'

	curves_image.pixels[:] = curve_list.reshape((-1,))
	return curves_image


TEXTURE_MODE_DIFFUSE = "0"
TEXTURE_MODE_SPECULAR = "1"
TEXTURE_MODE_NORMAL = "2"
TEXTURE_MODE_NORMAL_GREEN_INV = "3"
TEXTURE_MODE_DISPLACE = "4"
TEXTURE_MODE_OTHER = "5"
TEXTURE_MODE_BUMP = "6" # this converts textures to normal maps automatically

# saves image, and generates node with image description to add to export
def save_texture(texture, basedir, folder_name, skip_textures = False, use_gamma_hack=False):
	name, image, img_type = texture

	log.info("writing texture:"+name)

	ext = ".png"
	if image.file_format == 'JPEG':
		ext = ".jpg"
	elif image.file_format == 'HDR':
		ext = ".hdr"
	elif image.file_format == 'OPEN_EXR':
		ext = ".exr"
	elif image.file_format == 'TARGA' or image.file_format == 'TARGA_RAW':
		ext = ".tga"

	safe_name = sanitize_name(name) + ext
	image_path = path.join(basedir, folder_name, safe_name)
	skip_image = skip_textures and not path.exists(image_path)

	# fix for invalid images, like one in mr_elephant sample.
	valid_image = (image.channels != 0)
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

	n = Node('Texture')
	n['name'] = name
	n['file'] = path.join(folder_name, safe_name)#.replace("\\", "/")
	n['rgbcurve'] = 0.0
	n['srgb'] = "1" # this parameter is only read on 4.25 onwards

	n['texturemode'] = TEXTURE_MODE_DIFFUSE
	if image.file_format == 'HDR':
		n['texturemode'] = TEXTURE_MODE_OTHER
		n['rgbcurve'] = "1.000000"
	elif img_type == 'NORMAL':
		n['texturemode'] = TEXTURE_MODE_NORMAL_GREEN_INV
		n['srgb'] = "2" # only read on 4.25 onwards, but we can still write it
	elif image.colorspace_settings.is_data:
		n['texturemode'] = TEXTURE_MODE_SPECULAR
		n['srgb'] = "2" # only read on 4.25 onwards, but we can still write it
		if use_gamma_hack:
			n['rgbcurve'] = "0.454545"

	n['texturefilter'] = "3"
	if valid_image:
		img_hash = calc_hash(image_path)
		n.push(Node('Hash', {'value': img_hash}))
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
				base_prefix = base_prefix[:-5] # leave the underscore

			prefix = base_prefix
			try_count = 0
			
			# just to reaaally make sure there are no collisions
			libraries_prefixes = libraries_dict.values()
			while prefix in libraries_prefixes:
				try_count += 1
				prefix = "%s%d_" % (prefix_base, try_count)

			libraries_dict[library] = prefix
	
		bl_mesh_name = prefix + bl_mesh_name

	bl_mesh_name = sanitize_name(bl_mesh_name)

	# if the mesh has been processed already, return the name
	# if the mesh was processed, but its result was none, is because
	# it didn't have geometry, so we convert that to simple actor
	meshes_per_original = datasmith_context["meshes_per_original"]
	if bl_mesh_name in meshes_per_original:
		if meshes_per_original[bl_mesh_name] is None:
			return None
		return bl_mesh_name

	# if we find that the mesh has no geometry, just pass null and store null
	bl_mesh = bl_obj_inst.to_mesh()
	has_geometry = bl_mesh and len(bl_mesh.polygons) > 0
	if not has_geometry:
		# we use null name as a way to mean no geometry
		meshes_per_original[bl_mesh_name] = None
		bl_obj_inst.to_mesh_clear()
		return None

	log.info("creating mesh:%s" % bl_mesh_name)
	
	mesh_data = meshes_per_original[bl_mesh_name] = {}
	mesh_data['name'] = bl_mesh_name

	mesh_data['mesh'] = bl_mesh

	meshes = datasmith_context["meshes"]
	umesh = None

	if bl_mesh:# and len(bl_mesh.polygons) > 0:
		umesh = UDMesh(bl_mesh_name)
		meshes.append(umesh)
		fill_umesh(umesh, bl_mesh)

		material_list = datasmith_context["materials"]
		if len(bl_obj.material_slots) == 0:
			material_list.append((None, bl_obj))
		else:
			for slot in bl_obj.material_slots:
				material_list.append((slot.material, bl_obj))
	bl_obj_inst.to_mesh_clear()

	if umesh:
		mesh_data['umesh'] = umesh
	return bl_mesh_name

def fill_obj_mesh(obj_dict, bl_obj):
	mesh_name = get_mesh_name(bl_obj)
	# mesh_name can be none, in that case we won't ever convert to actormesh
	if mesh_name:
		obj_dict['type'] = 'ActorMesh'
		fields = obj_dict['fields']

		fields.append('\t<mesh name="%s"/>\n' % mesh_name)

		for idx, slot in enumerate(bl_obj.material_slots):
			if slot.link == 'OBJECT':
				safe_name = sanitize_name(slot.material.name)
				material_list = datasmith_context["materials"]
				material_list.append((slot.material, bl_obj))
				fields.append('\t<material id="%i" name="%s"/>\n' % (idx, safe_name))


def fill_obj_light(obj_dict, target):
	obj_dict['type'] = 'Light'

	fields = obj_dict['fields']
	attribs = obj_dict['attrib']

	bl_light = target.data
	light_intensity = bl_light.energy
	light_attenuation_radius = 100 * math.sqrt(bl_light.energy)
	light_color = bl_light.color
	light_intensity_units = 'Lumens' # can also be 'Candelas' or 'Unitless'
	light_use_custom_distance = bl_light.use_custom_distance

	light_type = 'PointLight'
	if bl_light.type == 'SUN':
		light_type = 'DirectionalLight'
		light_use_custom_distance = False
		# light_intensity = bl_light.energy # suns are in lux

	elif bl_light.type == 'SPOT':
		light_type = 'SpotLight'
		outer_cone_angle = bl_light.spot_size * 180 / (2*math.pi)
		inner_cone_angle = outer_cone_angle * (1 - bl_light.spot_blend)
		if inner_cone_angle < 0.0001:
			inner_cone_angle = 0.0001
		fields.append('\t<InnerConeAngle value="%f"/>\n' % inner_cone_angle)
		fields.append('\t<OuterConeAngle value="%f"/>\n' % outer_cone_angle)

		spot_use_candelas = False # TODO: test this thoroughly
		if spot_use_candelas:
			light_intensity_units = 'Candelas'
			light_intensity = bl_light.energy * 0.08 # came up with this constant by brute force
			# blender watts unit match ue4 lumens unit, but in spot lights the brightness
			# changes with the spot angle when using lumens while candelas do not.

	elif bl_light.type == 'AREA':
		light_type = 'AreaLight'

		size_w = size_h = bl_light.size
		if bl_light.shape == 'RECTANGLE' or bl_light.shape == 'ELLIPSE':
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

	fields.append('\t<Intensity value="%f"/>\n' %         light_intensity)
	fields.append('\t<AttenuationRadius value="%f"/>\n' % light_attenuation_radius)
	fields.append('\t<IntensityUnits value="%s"/>\n' %    light_intensity_units)
	# we could set usetemp=1 and write temperature attribute
	fields.append('\t<Color usetemp="0" R="%f" G="%f" B="%f"/>\n' % light_color[:])
	


def fill_obj_camera(obj_dict, target):
	obj_dict['type'] = "Camera"
	
	fields = obj_dict["fields"]
	bl_cam = target.data


	use_dof = "1" if bl_cam.dof.use_dof else "0"
	fields.append('\t<DepthOfField enabled="%s"/>\n' % use_dof)
	dof_target = bl_cam.dof.focus_object
	if dof_target:
		# BAD CODE: dof target is not the same thing as lookat target.
		# lookat target should be determined from a lookat modifier if it exists
		# and focus target maybe corresponds to a different property in the camera field 
		#fields.append('\t<LookAt Actor="%s"/>\n' % sanitize_name(dof_target.name))
		pass

	fields.append('\t<SensorWidth value="%f"/>\n' % bl_cam.sensor_width)

	# blender doesn't have per-camera aspect ratio
	sensor_aspect_ratio = 1.777778
	fields.append('\t<SensorAspectRatio value="%f"/>\n' % sensor_aspect_ratio)

	focus_distance_cm = bl_cam.dof.focus_distance * 100
	fields.append('\t<FocusDistance value="%f"/>\n' % focus_distance_cm) # to centimeters
	fields.append('\t<FStop value="%f"/>\n' % bl_cam.dof.aperture_fstop)
	fields.append('\t<FocalLength value="%f"/>\n' % bl_cam.lens)

def fill_obj_lightprobe(obj_dict, target):
	# TODO: LIGHT PROBE
	obj_dict['type'] = "CustomActor"
	bl_probe = target.data

	fields = obj_dict['fields']
	attribs = obj_dict['attrib']

	probe_type = bl_probe.type
	if probe_type == 'PLANAR':
		attribs.append(' PathName="/DatasmithBlenderContent/Blueprints/BP_BlenderPlanarReflection"')

	elif probe_type == 'CUBEMAP':
		## we could also try using min/max if it makes a difference
		_, _, obj_scale = target.matrix_world.decompose() # NOCHECKIN fix this
		avg_scale = (obj_scale.x + obj_scale.y + obj_scale.z) * 0.333333

		if bl_probe.influence_type == 'BOX':
			attribs.append(' PathName="/DatasmithBlenderContent/Blueprints/BP_BlenderBoxReflection"')

			falloff = bl_probe.falloff # this value is 0..1
			transition_distance = falloff * avg_scale
			fields.append('\t<KeyValueProperty name="TransitionDistance" type="Float" val="%f"/>\n' % transition_distance)

		elif bl_probe.influence_type == 'ELIPSOID':
			attribs.append(' PathName="/DatasmithBlenderContent/Blueprints/BP_BlenderSphereReflection"')

			probe_radius = bl_probe.influence_distance * 100 * avg_scale
			fields.append('\t<KeyValueProperty name="Radius" type="Float" val="%f"/>\n' % probe_radius)

		else:
			log.error("invalid light_probe.influence_type")

	elif probe_type == 'GRID':
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
	report_error("Invalid object type: %s" % target.type, once=True)

def fill_obj_unsupported(obj_dict, target):
	report_warn("Unsupported object type: %s" % target.type, once=True)

obj_fill_funcs = {
	'EMPTY':       fill_obj_empty,
	'CAMERA':      fill_obj_camera,
	'MESH':        fill_obj_mesh,
	'CURVE':       fill_obj_mesh,
	'FONT':        fill_obj_mesh,
	'LIGHT':       fill_obj_light,
	'LIGHT_PROBE': fill_obj_lightprobe,
	'ARMATURE':    fill_obj_unsupported,
	'LATTICE':     fill_obj_unsupported,
	'GPENCIL':     fill_obj_unsupported,
}


def collect_object_transform2(bl_obj, instance_mat = None):
	mat_basis = bl_obj.matrix_world
	if instance_mat:
		mat_basis = instance_mat
	obj_mat = matrix_datasmith @ mat_basis @ matrix_datasmith.inverted()

	if bl_obj.type in 'CAMERA' or bl_obj.type == 'LIGHT':
		obj_mat = obj_mat @ matrix_forward
	elif bl_obj.type == 'LIGHT_PROBE':
		bl_probe = bl_obj.data
		if bl_probe.type == 'PLANAR':
			obj_mat = obj_mat @ Matrix.Scale(0.05, 4)
		elif bl_probe.type == 'CUBEMAP':
			if bl_probe.influence_type == 'BOX':
				size = bl_probe.influence_distance * 100
				obj_mat = obj_mat @ Matrix.Scale(size, 4)

	result = transform_to_xml(obj_mat)
	return result

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
		object_data['name'] = object_name

		if not unique:
			objects[object_name] = object_data

		parent = instance_parent or _object.parent

		if parent:
			parent_data = get_object_data(objects, parent, top_level_objs)
			
			parent_data['children'].append(object_data)
		else: # is top level object
			log.info("TOP LEVEL OBJ:%s"%object_data['name'])
			top_level_objs.append(object_data)
	return object_data
	


def create_object(obj):
	assert obj

	visible = not obj.hide_render and obj.show_instancer_for_render
	object_data = {
		'fields': [],
		'attrib': [' visible="%s"'%visible],
		'children': [],
		'instances': {},
	}
	original = obj.original
	if original:
		object_data['layer'] = original.users_collection[0].name_full
		

	object_data['transform'] = collect_object_transform2(obj)
	return object_data
		

			
# for now let's try writing the xml directly
def collect_depsgraph(output, use_instanced_meshes, selected_only):
	d = bpy.context.evaluated_depsgraph_get()
	top_level_objs = []
	instance_groups = {}

	last_parent = None
	last_parent_data = None
	for instance in d.object_instances:
		if selected_only and not instance.object.original.select_get():
			continue
		
		transform = collect_object_transform2(instance.object, instance.matrix_world)
		was_instanced = False
		if use_instanced_meshes and instance.is_instance:

			original = instance.instance_object.original

			convertible_to_mesh = ('MESH', 'CURVE')
			if original.type in convertible_to_mesh:
				
				mesh_name = get_mesh_name(instance.instance_object) # ensure that mesh data has been collected
				if mesh_name:
					was_instanced = True
					original_name = original.name
					''' # maybe optimization to avoid calling get_object_data that much
				if instance.parent == last_parent:
					parent_data = last_parent_data
				else:
					parent_data = get_object_data(instance_groups, instance.parent, top_level_objs)
					last_parent_data = parent_data
					last_parent = instance.parent
'''
					parent_data = get_object_data(instance_groups, instance.parent, top_level_objs)
					instance_lists = parent_data['instances']
					instance_list = instance_lists.get(mesh_name)
					instance_material_slots = None
					if not instance_list:
						instance_list = instance_lists[mesh_name] = []
						instance_material_slots	= []
						bl_obj = instance.instance_object
						for idx, slot in enumerate(bl_obj.material_slots):
							if slot.link == 'OBJECT':
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
				object_data['transform'] = transform

			filler = obj_fill_funcs.get(obj.type, fill_obj_unknown)
			filler(object_data, obj)


	output = []
	for parent_obj in top_level_objs:
		render_tree(parent_obj, output, indent='\t')
		
	result = "".join(output)
	return result

def make_instance_name(instance):
	id_list = []
	for id in instance.persistent_id:
		if id != 0x7fffffff:
			id_list.append("_%i" % id)
		else:
			id_list.append('_')

	instance_id = "".join(
		"_%i" % id
		for id in instance.persistent_id
		if id != 0x7fffffff
	)
	instance_id = "".join(id_list)
	inst = instance.instance_object
	parent_chain = []
	parent = instance.parent
	while parent:
		parent_chain.append(parent.name)
		parent = parent.parent
	parents_name = "_".join(parent_chain)
	name = '%s_%s_%s' % (parents_name, inst.name, instance_id)
	return name


def render_tree(obj_dict, output, indent):
	output.append(indent)
	output.append('<')
	obj_type = obj_dict.get('type', "Actor")
	output.append(obj_type)
	output.append(' name="')
	obj_name = obj_dict['name']
	output.append(obj_name)

	layer = obj_dict.get('layer')
	if layer:
		output.append('" layer="')
		obj_layer = obj_dict['layer']
		output.append(obj_layer)

	output.append('"')
	
	attribs = obj_dict['attrib']
	if attribs:
		for attr in attribs:
			output.append(attr)
	
	output.append('>\n')
	
	fields = obj_dict['fields']
	for field in fields:
		output.append(indent)
		output.append(field)

	output.append(indent)
	output.append(obj_dict['transform'])

	children = obj_dict['children']
	parent_instances = obj_dict['instances']

	if children or parent_instances:
		
		output.append(indent)
		output.append('\t<children>\n')
		# output.append('\t<children visible="')
		# output.append(str(obj_dict['visible']))
		# output.append('">\n')


		for child in children:
			next_indent = '%s\t\t' % indent
			render_tree(child, output, next_indent)
			
		for original, instances in parent_instances.items():
			num_instances = len(instances)
			if num_instances == 1:
				output.append(indent)
				output.append('\t\t<ActorMesh name="')
				output.append(obj_name)
				output.append('_')
				output.append(original)
				output.append('">\n')
				output.append(indent)
				output.append('\t\t\t<mesh name="')
				output.append(original)
				output.append('"/>\n')
				output.append(indent)
				output.append('\t\t')

				transform = instances[0][1]
				output.append(transform)

				instance_materials = instances[0][2]
				if instance_materials:
					for mat in instance_materials:
						output.append(indent)
						output.append(mat)


				output.append(indent)
				output.append('\t\t</ActorMesh>\n')
				
			else:
				output.append(indent)
				output.append('\t\t<ActorHierarchicalInstancedStaticMesh name="')
				output.append(obj_name)
				output.append('_')
				output.append(original)
				output.append('">\n')
				output.append(indent)
				output.append('\t\t\t<mesh name="')
				output.append(original)
				output.append('"/>\n')
				output.append(indent)
				output.append('\t\t\t')
				output.append(obj_dict['transform'])
				output.append(indent)
				output.append('\t\t\t<Instances count="')
				output.append(str(len(instances)))
				output.append('">\n')
				for instance in instances:
					output.append(indent)
					output.append(instance[0])

				output.append(indent)
				output.append('\t\t\t</Instances>\n')
				output.append(indent)
				output.append('\t\t</ActorHierarchicalInstancedStaticMesh>\n')

		output.append(indent)
		output.append('\t</children>\n')

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
	if object_type in ['CAMERA', 'LIGHT']:
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
		
		for frame_idx in range(frame_start, frame_end+1):
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

			timeline_repr = ['''{
				"actor": "''', obj_name, '",'
			]

			translations = np.empty((num_frames, 4), dtype=np.float32)
			rotations = np.empty((num_frames, 4), dtype=np.float32)
			scales = np.empty((num_frames, 4), dtype=np.float32)
			translations[:, 0] = np.arange(frame_start, frame_end+1)
			rotations[:, 0] = np.arange(frame_start, frame_end+1)
			scales[:, 0] = np.arange(frame_start, frame_end+1)

			timeline = obj_data["frames"]
			for frame_idx, frame_mat in enumerate(timeline):
				loc, rot, scale = frame_mat.decompose()
				tx_slice = (frame_idx, slice(1,4))
				translations[frame_idx, 1:4] = loc
				rotations[frame_idx, 1:4] = rot_fix * rot.to_euler('XYZ')
				scales[frame_idx, 1:4] = scale

			translations[np.isnan(translations)] = 0
			trans_expression = ",".join(
				'{"id":%d,"x":%f,"y":%f,"z":%f}'% tuple(v)
				for v in translations
			)
			timeline_repr.extend(('"trans":[', trans_expression, '],'))

			rotations[np.isnan(rotations)] = 0
			rot_expression = ",".join(
				'{"id":%d,"x":%f,"y":%f,"z":%f}'% tuple(v)
				for v in rotations
			)
			timeline_repr.extend(('"rot":[', rot_expression, '],'))

			scales[np.isnan(scales)] = 0
			scale_expression = ",".join(
				'{"id":%d,"x":%f,"y":%f,"z":%f}'% tuple(v)
				for v in scales
			)
			timeline_repr.extend(('"scl":[', scale_expression, '],'))

			timeline_repr.append('"type":"transform"}')
			result = "".join(timeline_repr)
			anims_strings.append(result)


	else: # if not new_iterator

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

		for arr_idx, frame_idx in enumerate(range(frame_start, frame_end+1)):

			context.scene.frame_set(frame_idx)

			for obj_idx, obj in enumerate(anim_objs):

				obj_mat = collect_object_transform(obj[0])
				object_timelines[obj_idx][arr_idx] = obj_mat

				if arr_idx == 0:
					continue

				if not object_animates[obj_idx]:
					changed = obj_mat != object_timelines[obj_idx][arr_idx -1]
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

			timeline_repr = ['''{
				"actor": "''', anim_objs[idx][1], '",'
			]

			translations = np.empty((num_frames, 4), dtype=np.float32)
			rotations = np.empty((num_frames, 4), dtype=np.float32)
			scales = np.empty((num_frames, 4), dtype=np.float32)
			translations[:, 0] = np.arange(frame_start, frame_end+1)
			rotations[:, 0] = np.arange(frame_start, frame_end+1)
			scales[:, 0] = np.arange(frame_start, frame_end+1)

			for frame_idx, frame_mat in enumerate(timeline):
				loc, rot, scale = frame_mat.decompose()
				tx_slice = (frame_idx, slice(1,4))
				translations[frame_idx, 1:4] = loc
				rotations[frame_idx, 1:4] = rot_fix * rot.to_euler('XYZ')
				scales[frame_idx, 1:4] = scale

			trans_expression = ",".join(
				'{"id":%d,"x":%f,"y":%f,"z":%f}'% tuple(v)
				for v in translations
			)
			timeline_repr.extend(('"trans":[', trans_expression, '],'))

			rot_expression = ",".join(
				'{"id":%d,"x":%f,"y":%f,"z":%f}'% tuple(v)
				for v in rotations
			)
			timeline_repr.extend(('"rot":[', rot_expression, '],'))

			scale_expression = ",".join(
				'{"id":%d,"x":%f,"y":%f,"z":%f}'% tuple(v)
				for v in scales
			)
			timeline_repr.extend(('"scl":[', scale_expression, '],'))

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
		"meshes": [],
		"meshes_per_original": {},
		"materials": [],
		"material_curves": None,
		"metadata": [],
		"compatibility_mode": args["compatibility_mode"],
		"libraries": {},
	}

	log.info("collecting objects")
	all_objects = context.scene.objects


	selected_only = args["export_selected"]
	apply_modifiers = args["apply_modifiers"]
	skip_textures = args["skip_textures"]
	export_metadata = args["export_metadata"]
	export_animations = args["export_animations"]
	use_old_iterator = args["use_old_iterator"]
	use_instanced_meshes = args["use_instanced_meshes"]
	global config_always_twosided
	config_always_twosided = args["always_twosided"]

	objects = []
	obj_output = ""
	if use_old_iterator:
		datasmith_context['depsgraph'] = context.evaluated_depsgraph_get()
		root_objects = [obj for obj in all_objects if obj.parent is None]
		for obj in root_objects:
			uobj = collect_object(
				bl_obj=obj,
				selected_only=selected_only,
				apply_modifiers=apply_modifiers,
				export_animations=export_animations,
				export_metadata=export_metadata,
			)
			if uobj:
				objects.append(uobj)
	else: # if not use_old_iterator:
		# with the depsgraph iterator, we don't start with root objects and then find children.
		# with the new object iterator, we read the depsgraph evaluated object array
		log.info("USE NEW OBJECT ITERATOR")
		obj_output = collect_depsgraph(objects, use_instanced_meshes, selected_only)

	anims = []
	if export_animations:
		anims = collect_anims(context, not use_old_iterator, use_instanced_meshes)


	environment = collect_environment(context.scene.world)

	log.info("Collecting materials")
	materials = datasmith_context["materials"]
	unique_materials = []
	for material in materials:
		found = False
		for mat in unique_materials:
			if material[0] is mat[0]: # materials here are tuple (material, owner)
				found = True
				break
		if not found:
			unique_materials.append(material)
	material_nodes = [collect_pbr_material(mat) for mat in unique_materials]

	curves_image = get_datasmith_curves_image()
	if curves_image:
		get_or_create_texture("datasmith_curves", curves_image)

	log.info("finished collecting, now saving")

	basedir, file_name = path.split(save_path)
	folder_name = file_name + '_Assets'
	# make sure basepath_Assets directory exists
	try:
		os.makedirs(path.join(basedir, folder_name))
	except FileExistsError as e:
		pass

	log.info("writing anims")
	anim_nodes = []

	assert len(anims) < 2
	if anims:
		anim = anims[0]
		filename = path.join(basedir, folder_name, "anim_new.json")
		log.info("writing to file:%s" % filename)
		with open(filename, 'w') as f:
			f.write(anim)

		anim = Node("LevelSequence", {"name": "anim_new"})
		anim.push(Node("File", {"path": f"{folder_name}/anim_new.json"}))
		anim_nodes.append(anim)




	log.info("writing meshes")
	num_meshes = 0
	for mesh in datasmith_context["meshes"]:
		mesh.save(basedir, folder_name)
		num_meshes += 1
	summary["Num meshes"] = num_meshes


	log.info("writing textures")

	tex_nodes = []
	use_gamma_hack = args["use_gamma_hack"]
	num_textures = 0
	for tex in datasmith_context["textures"]:
		tex_node = save_texture(tex, basedir, folder_name, skip_textures, use_gamma_hack)
		tex_nodes.append(tex_node)
		num_textures += 1

	summary["Num textures"] = num_textures

	log.info("building XML tree")

	n = get_file_header()
	n.push('\n')

	for anim in anim_nodes:
		n.push(anim)

	for obj in objects:
		n.push(obj)

	if obj_output:
		n.push(obj_output)

	if environment:
		for env in environment:
			n.push(env)

	for mesh in datasmith_context["meshes"]:
		n.push(mesh.node())
	for mat in material_nodes:
		n.push(mat)

	for tex in tex_nodes:
		n.push(tex)

	for metadata in datasmith_context["metadata"]:
		n.push(metadata)

	end_time = time.monotonic()
	total_time = end_time - start_time

	log.info("generating datasmith data took:%f"%total_time)
	n.push(
		Node("Export", {"Duration":total_time})
	)

	log.info("generating xml")
	result = n.string_rep(first=True)

	filename = path.join(basedir, file_name + '.udatasmith')
	log.info("writing to file: %s" % filename)

	with open(filename, 'w') as f:
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
		handler = logging.FileHandler(log_path, mode='w')

		formatter = logging.Formatter(
			fmt='%(asctime)s.%(msecs)03d %(levelname)-8s %(message)s',
			datefmt='%Y-%m-%d %H:%M:%S'
		)
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
			"status": 'SUCCESS',
			"log": 'placeholder log',
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
		except:
			log.warn("unable to reach telemetry server")
	return {'FINISHED'}

