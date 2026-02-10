# SPDX-FileCopyrightText: 2025 Andrés Botero
# SPDX-License-Identifier: AGPL-3.0-only
# SPDX-FileName: export_material.py

import math
import logging

import numpy as np

import bpy
from mathutils import Vector, Euler

from .data_types import Node, sanitize_name


log = logging.getLogger("bl_datasmith")


DATASMITH_TEXTURE_SIZE = 1024
BLENDER_CURVES_NAME = "blender_curves"

# only functions you need to care about from the outside


def collect_all_materials(unique_materials, textures_dict, config_always_twosided):
	global material_curves
	global material_curves_count
	global tex_dict
	material_curves = np.zeros((DATASMITH_TEXTURE_SIZE, DATASMITH_TEXTURE_SIZE, 4))
	material_curves_count = 0
	tex_dict = textures_dict

	material_nodes = [collect_pbr_material(mat, config_always_twosided) for mat in unique_materials]

	if material_curves_count != 0:
		curves_image = None
		if BLENDER_CURVES_NAME in bpy.data.images:
			curves_image = bpy.data.images[BLENDER_CURVES_NAME]
		else:
			curves_image = bpy.data.images.new(BLENDER_CURVES_NAME, DATASMITH_TEXTURE_SIZE, DATASMITH_TEXTURE_SIZE, alpha=True, float_buffer=True)
			curves_image.colorspace_settings.is_data = True
			curves_image.file_format = "OPEN_EXR"

		curves_image.pixels[:] = material_curves.reshape((-1,))

		# add image to textures_dict
		get_texture_name(textures_dict, curves_image)

	return material_nodes


# type_hint can be SRGB, LINEAR or NORMAL
def get_texture_name(img_dict, in_image, type_hint="SRGB"):
	name = sanitize_name(in_image.name)
	existing_img = img_dict.get(name)
	if existing_img:
		return name

	log.debug("collecting texture:%s" % name)
	img_dict[name] = (name, in_image, type_hint)
	return name


# From here, everything is "private"


def collect_pbr_material(mat_with_owner, config_always_twosided):
	global reported_errors
	global reported_warns
	global material_owner
	reported_errors = set()
	reported_warns = set()

	material_owner = mat_with_owner[1]

	material = mat_with_owner[0]
	if material is None:
		log.debug("creating default material")
		return pbr_default_material()
	if not material.use_nodes:
		log.debug("creating material %s without nodes" % material.name)
		return pbr_basic_material(material)
	log.debug("creating material %s with node_tree " % material.name)
	return pbr_nodetree_material(material, config_always_twosided)


def add_material_curve(curve):
	global material_curves
	global material_curves_count
	mat_curve_idx = material_curves_count
	material_curves_count += 1
	log.info("writing curve:%s" % mat_curve_idx)

	# write texture from top
	row_idx = DATASMITH_TEXTURE_SIZE - mat_curve_idx - 1
	values = material_curves[row_idx]
	factor = DATASMITH_TEXTURE_SIZE  # divide range 0-1 in 1023 parts

	# check for curve type, do sampling
	curve_type = type(curve)
	if curve_type is bpy.types.ColorRamp:
		for idx in range(DATASMITH_TEXTURE_SIZE):
			values[idx] = curve.evaluate(idx / factor)

	elif curve_type is bpy.types.CurveMapping:
		curves = curve.curves

		position = 0
		for idx in range(DATASMITH_TEXTURE_SIZE):
			position = idx / factor
			values[idx, 0] = curve.evaluate(curves[0], position)
			values[idx, 1] = curve.evaluate(curves[1], position)
			values[idx, 2] = curve.evaluate(curves[2], position)
			values[idx, 3] = curve.evaluate(curves[3], position)

	return mat_curve_idx


def report_warn(message, user_info=None, once=False):
	if once:
		if message in reported_warns:
			return
		reported_warns.add(message)

	if user_info:
		log.warn(message % user_info)
	else:
		log.warn(message)


def report_error(message, user_info=None, once=False):
	if once:
		if message in reported_errors:
			return
		reported_errors.add(message)

	if user_info:
		log.error(message % user_info)
	else:
		log.error(message)


def pbr_default_material():
	n = Node("UEPbrMaterial")
	n["name"] = "DefaultMaterial"
	exp_list = Node("Expressions")
	grey = 0.906332
	basecolor_idx = exp_color((grey, grey, grey, 1.0), exp_list)
	roughness_idx = exp_scalar(0.4, exp_list)
	n.push(exp_list)
	n.push(Node("BaseColor", {"expression": basecolor_idx, "OutputIndex": "0"}))
	n.push(Node("Roughness", {"expression": roughness_idx, "OutputIndex": "0"}))
	return n


def pbr_basic_material(material):
	n = Node("UEPbrMaterial")
	n["name"] = sanitize_name(material.name)
	exp_list = Node("Expressions")
	n.push(exp_list)

	basecolor_idx = exp_color(material.diffuse_color, exp_list)
	roughness_idx = exp_scalar(material.roughness, exp_list)
	metallic_idx = exp_scalar(material.metallic, exp_list)
	specular_idx = exp_scalar(material.specular_intensity, exp_list)

	n.push(Node("BaseColor", {"expression": basecolor_idx, "OutputIndex": "0"}))
	n.push(Node("Roughness", {"expression": roughness_idx, "OutputIndex": "0"}))
	n.push(Node("Metallic", {"expression": metallic_idx, "OutputIndex": "0"}))
	n.push(Node("Specular", {"expression": specular_idx, "OutputIndex": "0"}))

	return n


# if we try to use textures that end up being connected to the normal input of
# a material in UE, UE tries to be smart and flag them as normal maps, but
# sometimes these aren't normal maps. for example when we use a texture to
# blend between other two. in those cases we want to tell unreal to NOT flag
# these as normal maps, and the only way to do this is to connect them to a
# basecolor or specular socket too
MAT_FUNC_PASSTHROUGH = "/DatasmithBlenderContent/MaterialFunctions/Passthrough"
whitelisted_textures = []

cached_nodes = {}
material_hint_twosided = False


def pbr_nodetree_material(material, config_always_twosided):
	global cached_nodes
	cached_nodes = {}
	log.info("Collecting material: " + material.name)
	n = Node("UEPbrMaterial")
	n["name"] = sanitize_name(material.name)

	output_node = material.node_tree.get_output_node("EEVEE") or material.node_tree.get_output_node("ALL") or material.node_tree.get_output_node("CYCLES")

	if not output_node:
		report_warn("Material %s with use_nodes does not have nodes", material.name, once=True)
		return n

	exp_list = Node("Expressions")
	n.push(exp_list)
	global material_hint_twosided
	material_hint_twosided = False

	surface_field = output_node.inputs["Surface"]
	volume_field = output_node.inputs["Volume"]
	# TODO: also check for output_node.inputs['Displacement']

	expressions = None
	if volume_field.links and not surface_field.links:
		report_warn("Material %s has volume nodes, which are unsupported. Writing transparent material.", material.name, once=True)
		expressions = {
			"BaseColor": {"expression": exp_vector((0, 0, 0), exp_list)},
			"Refraction": {"expression": exp_scalar(1.0, exp_list)},
			"Opacity": {"expression": exp_scalar(0.0, exp_list)},
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
		expressions["BaseColor"] = {"expression": exp_list.push(main_passthrough)}

	can_be_twosided = True

	blend_method = material.blend_method
	if blend_method == "CLIP":
		n.push('\n\t\t<Blendmode value="1"/>')
		n.push('\n\t\t<OpacityMaskClipValue value="%f"/>' % max(material.alpha_threshold, 0.01))
	elif blend_method == "HASHED":
		n.push('\n\t\t<Blendmode value="1"/>')
		n.push('\n\t\t<OpacityMaskClipValue value="0.5"/>')
		alpha_exp = expressions.get("Opacity")
		if alpha_exp:
			hashed_exp = Node("FunctionCall", {"Function": "/Engine/Functions/Engine_MaterialFunctions02/Utility/DitherTemporalAA"})

			push_exp_input(hashed_exp, "0", alpha_exp)
			new_alpha_exp = exp_list.push(hashed_exp)
			expressions["Opacity"] = new_alpha_exp

	# maybe we can check this earlier and decide
	# to push a temporal hash mask node in the material?
	elif blend_method == "BLEND":
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


def exp_scalar(value, exp_list):
	n = Node(
		"Scalar",
		{
			# "Name": "",
			"constant": "%f" % value
		},
	)
	return exp_list.push(n)


def exp_vector(value, exp_list):
	n = Node(
		"Color",
		{
			# "Name": name,
			"constant": "(R=%.6f,G=%.6f,B=%.6f,A=1.0)" % tuple(value)
		},
	)
	return exp_list.push(n)


def exp_color(value, exp_list, name=None):
	color = Node("Color", {"constant": "(R=%.6f,G=%.6f,B=%.6f,A=%.6f)" % tuple(value)})
	if name:
		color["Name"] = name
	color_exp = exp_list.push(color)

	alpha_exp = exp_scalar(value[3], exp_list)

	append = Node("AppendVector")
	push_exp_input(append, "0", color_exp)
	push_exp_input(append, "1", alpha_exp)

	return exp_list.push(append)


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
	elif expression is not None:
		assert type(expression) is int
		expression_idx = expression

	if output_idx == 0:
		return '\n\t\t<%s expression="%s"/>' % (output_id, expression_idx)

	else:
		return '\n\t\t<%s expression="%s" OutputIndex="%s"/>' % (output_id, expression_idx, output_idx)


MAT_CTX_BUMP = "BUMP"
MAT_CTX_NORMAL = "NORMAL"
context_stack = []


def push_texture_context(context):
	context_stack.append(context)


def pop_texture_context():
	context_stack.pop()


def get_context():
	if context_stack:
		return context_stack[-1]


def exp_input(input_idx, expression, output_idx=0):
	expression_idx = -1
	if type(expression) is dict:
		if "expression" not in expression:
			log.error(expression)
		expression_idx = expression["expression"]
		output_idx = expression.get("OutputIndex", 0)
	elif type(expression) is tuple:
		expression_idx, output_idx = expression
	elif expression is not None:
		assert type(expression) is int
		expression_idx = expression
		# output_idx = 0 # already set as default value

	# TODO: find loose ends by enabling this error
	# or change this function to receive the parent node as parameter
	# and early exit if expression is None
	# if expression_idx == -1:
	# report_error("trying to use expression=None for input for another expression")

	return '\n\t\t\t\t<Input Name="%s" expression="%s" OutputIndex="%s"/>' % (input_idx, expression_idx, output_idx)


# convenience function to skip adding an input if the input is None
def push_exp_input(node, input_idx, expression, output_idx=0):
	if expression is not None:
		node.push(exp_input(input_idx, expression, output_idx))


expression_log_prefix = ""


def get_expression(field, exp_list, force_default=False, skip_default_warn=False):
	# this may return none for fields without default value
	# most of the time blender doesn't have default value for vector
	# node inputs, but it does for scalars and colors
	# TODO: check which cases we should be careful
	global expression_log_prefix
	node = field.node
	log.debug(
		"%s%s:%s/%s:%s"
		% (
			expression_log_prefix,
			node.type,
			node.name,
			field.type,
			field.name,
		)
	)

	if not field.links or not field.links[0].from_socket.enabled:
		if field.type == "VALUE":
			exp = exp_scalar(field.default_value, exp_list)
			return {"expression": exp, "OutputIndex": 0}
		elif field.type == "RGBA":
			color_value = field.default_value

			if get_context() == MAT_CTX_NORMAL:
				color_value = (color_value[0] * 2.0 - 1.0, color_value[1] * 2.0 - 1.0, color_value[2] * 2.0 - 1.0, color_value[3])
			exp = exp_color(color_value, exp_list)
			return {"expression": exp, "OutputIndex": 0}
		elif field.type == "VECTOR":
			use_vector_default = force_default or type(field.default_value) in {Vector, Euler}
			# here, we're specifically discarding when the field type is
			# bpy.types.bpy_prop_array. we do that because when that happens,
			# most of the time it is because this socket default value is a
			# custom expression, an example is TEX_IMAGE nodes that by
			# default use the main UV channel if not connected, while
			# TEX_NOISE use TEXCOORD_GENERATED values by default.
			if use_vector_default:
				exp = exp_vector(field.default_value, exp_list)
				return {"expression": exp, "OutputIndex": 0}
		elif field.type == "SHADER":
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

	if return_exp:
		other_output = field.links[0].from_socket
		# if a color output is connected to a scalar input, average by using dot product
		if field.type == "VALUE":
			if other_output.type == "RGBA":
				n = Node("FunctionCall", {"Function": MAT_FUNC_RGB_TO_BW})
				push_exp_input(n, "0", return_exp)
				dot_exp = exp_list.push(n)
				return_exp = {"expression": dot_exp}

			elif other_output.type == "VECTOR":
				n = Node("DotProduct")
				exp_0 = return_exp
				n.push(exp_input("0", exp_0))
				exp_1 = exp_vector((0.333333, 0.333333, 0.333333), exp_list)
				n.push(exp_input("1", {"expression": exp_1}))
				dot_exp = exp_list.push(n)
				return_exp = {"expression": dot_exp}
		elif field.type == "VECTOR":
			if other_output.type == "RGBA":
				n = Node("ComponentMask")
				push_exp_input(n, "0", return_exp)
				n.push('<Prop name="R" val="True" type="Bool" />')
				n.push('<Prop name="G" val="True" type="Bool" />')
				n.push('<Prop name="B" val="True" type="Bool" />')
				return_exp = {"expression": exp_list.push(n)}

		elif field.type == "RGBA":
			if other_output.type == "VECTOR":
				alpha = exp_scalar(1, exp_list)  # Don't know if its better to use 0 or 1 here
				n = Node("AppendVector")
				push_exp_input(n, "0", return_exp)
				push_exp_input(n, "1", alpha)
				return_exp = {"expression": exp_list.push(n)}
			elif other_output.type == "VALUE":
				# This makes the output safer, because next node may expect this is a vector
				n = Node("FunctionCall", {"Function": MAT_FUNC_COMBINE_RGB})
				push_exp_input(n, "0", return_exp)
				push_exp_input(n, "1", return_exp)
				push_exp_input(n, "2", return_exp)
				return_exp = {"expression": exp_list.push(n)}

		elif field.type == "SHADER":
			other_output = field.links[0].from_socket
			if other_output.type != "SHADER":
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
	socket_names = cached_node[1]
	# Blender 5.0 changed "Fac" sockets label to "Factor"
	if socket_name == "Factor" and "Fac" in socket_names:
		output_index = socket_names.index("Fac")
	else:
		output_index = socket_names.index(socket_name)
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
	if node.type == "GROUP":
		# exp = exp_group(node, exp_list)
		# as exp_group can output shaders (dicts with basecolor/roughness)
		# or other types of values (dicts with expression:)
		# it may be better to return as is and handle internally
		return exp_group(socket, exp_list)  # TODO node trees can have multiple outputs

	if node.type == "GROUP_INPUT":
		return exp_group_input(socket, exp_list, target_socket)

	if node.type == "REROUTE":
		return get_expression(node.inputs["Input"], exp_list)

	# Shader nodes return a dictionary
	bsdf = None
	if node.type == "BSDF_PRINCIPLED":
		bsdf = {
			"BaseColor": get_expression(node.inputs["Base Color"], exp_list),
			"Metallic": get_expression(node.inputs["Metallic"], exp_list),
			"Roughness": get_expression(node.inputs["Roughness"], exp_list),
		}
		specular = node.inputs.get("Specular IOR Level")
		if not specular:
			specular = node.inputs["Specular"]
		bsdf["Specular"] = get_expression(specular, exp_list)

		# only add opacity if alpha != 1
		opacity_field = node.inputs["Alpha"]
		add_opacity = False
		if len(opacity_field.links) != 0:
			add_opacity = True
		elif opacity_field.default_value != 1:
			add_opacity = True
		if add_opacity:
			bsdf["Opacity"] = get_expression(opacity_field, exp_list)

		emission_field = node.inputs.get("Emission Color")
		if not emission_field:
			emission_field = node.inputs["Emission"]
		emission_strength_field = node.inputs["Emission Strength"]
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

	if node.type == "EEVEE_SPECULAR":
		report_warn("EEVEE_SPECULAR incomplete implementation", once=True)
		bsdf = {
			"BaseColor": get_expression(node.inputs["Base Color"], exp_list),
			"Roughness": get_expression(node.inputs["Roughness"], exp_list),
		}

	elif node.type == "BSDF_DIFFUSE":
		bsdf = {
			"BaseColor": get_expression(node.inputs["Color"], exp_list),
			"Roughness": {"expression": exp_scalar(1.0, exp_list)},
			"Metallic": {"expression": exp_scalar(0.0, exp_list)},
		}
	elif node.type == "BSDF_TOON":
		report_warn("BSDF_TOON incomplete implementation", once=True)
		bsdf = {
			"BaseColor": get_expression(node.inputs["Color"], exp_list),
			"Roughness": {"expression": exp_scalar(1.0, exp_list)},
			"Metallic": {"expression": exp_scalar(0.0, exp_list)},
		}
	elif node.type == "BSDF_GLOSSY":
		bsdf = {
			"BaseColor": get_expression(node.inputs["Color"], exp_list),
			"Roughness": get_expression(node.inputs["Roughness"], exp_list),
			"Metallic": {"expression": exp_scalar(1.0, exp_list)},
		}
	elif node.type == "BSDF_VELVET":
		report_warn("BSDF_VELVET incomplete implementation", once=True)
		bsdf = {
			"BaseColor": get_expression(node.inputs["Color"], exp_list),
			"Roughness": {"expression": exp_scalar(1.0, exp_list)},
		}
	elif node.type == "BSDF_TRANSPARENT":
		report_warn("BSDF_TRANSPARENT incomplete implementation", once=True)
		bsdf = {
			"BaseColor": get_expression(node.inputs["Color"], exp_list),
			"Refraction": {"expression": exp_scalar(1.0, exp_list)},
			"Opacity": {"expression": exp_scalar(0.0, exp_list)},
		}
	elif node.type == "BSDF_TRANSLUCENT":
		report_warn("BSDF_TRANSLUCENT incomplete implementation", once=True)
		bsdf = {
			"BaseColor": get_expression(node.inputs["Color"], exp_list),
		}
	elif node.type == "BSDF_GLASS":
		report_warn("BSDF_GLASS incomplete implementation", once=True)
		bsdf = {
			"BaseColor": get_expression(node.inputs["Color"], exp_list),
			"Metallic": {"expression": exp_scalar(1, exp_list)},
			"Roughness": get_expression(node.inputs["Roughness"], exp_list),
			"Refraction": get_expression(node.inputs["IOR"], exp_list),
			"Opacity": {"expression": exp_scalar(0.5, exp_list)},
		}
	elif node.type == "BSDF_HAIR":
		report_warn("BSDF_HAIR incomplete implementation", once=True)
		bsdf = {
			"BaseColor": get_expression(node.inputs["Color"], exp_list),
			"Roughness": {"expression": exp_scalar(0.5, exp_list)},
		}
	elif node.type == "SUBSURFACE_SCATTERING":
		report_warn("SUBSURFACE_SCATTERING incomplete implementation", once=True)
		bsdf = {"BaseColor": get_expression(node.inputs["Color"], exp_list)}
	elif node.type == "BSDF_REFRACTION":
		report_warn("BSDF_REFRACTION incomplete implementation", once=True)
		bsdf = {
			"BaseColor": get_expression(node.inputs["Color"], exp_list),
			"Roughness": get_expression(node.inputs["Roughness"], exp_list),
			"Refraction": get_expression(node.inputs["IOR"], exp_list),
			"Opacity": {"expression": exp_scalar(0.5, exp_list)},
		}
	elif node.type == "BSDF_ANISOTROPIC":
		report_warn("BSDF_ANISOTROPIC incomplete implementation", once=True)
		bsdf = {
			"BaseColor": get_expression(node.inputs["Color"], exp_list),
			"Roughness": get_expression(node.inputs["Roughness"], exp_list),
			# TODO: read inputs 'Anisotropy' and 'Rotation' and 'Tangent'
		}

	elif node.type == "EMISSION":
		mult = Node("Multiply")
		mult.push(exp_input("0", get_expression(node.inputs["Color"], exp_list)))
		mult.push(exp_input("1", get_expression(node.inputs["Strength"], exp_list)))
		mult_exp = exp_list.push(mult)
		bsdf = {"EmissiveColor": {"expression": mult_exp}}

	elif node.type == "HOLDOUT":
		bsdf = {
			"BaseColor": {"expression": exp_vector((0, 0, 0), exp_list)},
			"Roughness": {"expression": exp_scalar(1.0, exp_list)},
		}

	if bsdf:
		assert socket.type == "SHADER"
		if socket.type == "SHADER":
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

	if node.type == "ADD_SHADER":
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
		all_keys.sort()  # we do this to have deterministic outputs

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

				add_expression[name] = {"expression": exp_list.push(n)}
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
	if node.type == "MIX_SHADER":
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
		fac_expression = get_expression(node.inputs["Fac"], exp_list)
		for name, exp in expressions1.items():
			if name in expressions:
				n = Node("LinearInterpolate")
				n.push(exp_input("0", expressions[name]))
				n.push(exp_input("1", exp))
				n.push(exp_input("2", fac_expression))
				expressions[name] = {"expression": exp_list.push(n)}
			else:
				expressions[name] = exp
		return expressions

	# from here the return type should be {expression:node_idx, OutputIndex: socket_idx}
	node_handler = node_handlers.get(node.type)
	if node_handler:
		return node_handler(socket, exp_list)

	report_error("Node %s:%s not handled" % (node.type, socket.name))
	exp = exp_scalar(0, exp_list)
	return {"expression": exp}


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
	for idx, input in enumerate(node.inputs):  # use input.identifier
		value_has_links = len(input.links) > 0
		value_exp = get_expression(input, exp_list, force_default=True)
		new_context[input.identifier] = (value_exp, value_has_links)

	group_context = new_context
	reverse_expressions = {}
	cached_nodes = {}

	# search for active output node inside the group node_tree:
	output_node = None
	for node in node_tree.nodes:
		if type(node) is bpy.types.NodeGroupOutput:
			if node.is_active_output or output_node is None:
				output_node = node

	if not output_node:
		log.error("group does not have output node!")

	# now traverse the inner graph
	inner_socket = None
	for input in output_node.inputs:
		if input.identifier == socket.identifier:
			inner_socket = input
	assert inner_socket
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
	if type(target_socket) is bpy.types.NodeSocketVector:
		if type(target_socket.default_value) is bpy.types.bpy_prop_array:
			value_has_links = outer_expression_data[1]
			if not value_has_links:
				return None
	outer_expression = outer_expression_data[0]
	return outer_expression


node_handlers = {}


def blender_node(key):
	def decorator(func):
		node_handlers[key] = func
		return func  # return the function unmodified

	return decorator


# Add > Input


@blender_node("AMBIENT_OCCLUSION")
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
		return {"expression": exp}
	else:
		report_error("Unsupported AMBIENT_OCCLUSION output: %s" % socket_name)


@blender_node("ATTRIBUTE")
def exp_attribute(socket, exp_list):
	exp = exp_list.push(Node("VertexColor"))
	# average channels if socket is Fac
	if socket.name == "Fac":
		# TODO: check if we should do some colorimetric aware convertion to grayscale
		n = Node("DotProduct")
		exp_1 = exp_vector((0.333333, 0.333333, 0.333333), exp_list)
		push_exp_input(n, "0", exp)
		push_exp_input(n, "1", exp_1)
		dot_exp = exp_list.push(n)
		return {"expression": dot_exp}

	elif socket.name == "Vector":
		return {"expression": exp}

	else:  # if socket.name == "Color":
		append = Node("AppendVector")
		push_exp_input(append, "0", exp, 0)
		push_exp_input(append, "1", exp, 4)
		append_exp = exp_list.push(append)
		return {"expression": append_exp}


@blender_node("VERTEX_COLOR")
def exp_vertex_color(socket, exp_list):
	exp = exp_list.push(Node("VertexColor"))
	if socket.name == "Color":
		append = Node("AppendVector")
		push_exp_input(append, "0", exp, 0)
		push_exp_input(append, "1", exp, 4)
		append_exp = exp_list.push(append)
		return {"expression": append_exp, "OutputIndex": 0}
	elif socket.name == "Alpha":
		return {"expression": exp, "OutputIndex": 4}


@blender_node("BEVEL")
def exp_bevel(socket, exp_list):
	report_warn("Unsupported node 'Bevel', writing unmodified normal", once=True)
	exp = get_expression(socket.node.inputs["Normal"], exp_list)
	if not exp:
		exp = {"expression": exp_vector((0, 0, 1), exp_list)}
	return exp


@blender_node("FRESNEL")
def exp_fresnel(socket, exp_list):
	node = socket.node
	n = Node("FunctionCall", {"Function": op_custom_functions["FRESNEL"]})
	exp_ior = get_expression(node.inputs["IOR"], exp_list)
	n.push(exp_input("0", exp_ior))
	return {"expression": exp_list.push(n)}


@blender_node("NEW_GEOMETRY")
def exp_new_geometry(socket, exp_list):
	socket_name = socket.name
	if socket_name == "Position":
		output = Node("FunctionCall", {"Function": "/DatasmithBlenderContent/MaterialFunctions/BlenderWorldPosition"})
		return {"expression": exp_list.push(output)}
	if socket_name == "Normal":
		output = Node("VertexNormalWS")
		return {"expression": exp_list.push(output)}
	if socket_name == "Tangent":
		output = Node("VertexTangentWS")
		return {"expression": exp_list.push(output)}
	if socket_name == "True Normal":
		output = Node("FunctionCall", {"Function": "/DatasmithBlenderContent/MaterialFunctions/BlenderTrueNormal"})
		return {"expression": exp_list.push(output)}
	if socket_name == "Incoming":
		output = Node("FunctionCall", {"Function": "/DatasmithBlenderContent/MaterialFunctions/Incoming"})
		return {"expression": exp_list.push(output)}
	if socket_name == "Backfacing":
		global material_hint_twosided
		material_hint_twosided = True
		output = Node("FunctionCall", {"Function": "/DatasmithBlenderContent/MaterialFunctions/Backfacing"})
		return {"expression": exp_list.push(output)}

	if socket_name == "Parametric":
		report_warn("Unsupported node 'Geometry:Parametric'.", once=True)
		return {"expression": exp_scalar(0.5, exp_list)}
	if socket_name == "Pointiness":
		report_warn("Unsupported node 'Geometry:Pointiness'.", once=True)
		return {"expression": exp_scalar(0.5, exp_list)}
	if socket_name == "Random Per Island":
		report_warn("Unsupported node 'Geometry:Random Per Island'.", once=True)
		return {"expression": exp_scalar(0, exp_list)}


@blender_node("LAYER_WEIGHT")
def exp_layer_weight(socket, exp_list):
	expr = None
	if socket.node in reverse_expressions:
		expr = reverse_expressions[socket.node]
	else:
		exp_blend = get_expression(socket.node.inputs["Blend"], exp_list)
		n = Node("FunctionCall", {"Function": op_custom_functions["LAYER_WEIGHT"]})
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


@blender_node("LIGHT_PATH")
def exp_light_path(socket, exp_list):
	report_warn("Unsupported node 'Light Path:%s'. Writing 1.0 value." % socket.name, once=True)
	n = exp_scalar(1, exp_list)
	return {"expression": n}


@blender_node("OBJECT_INFO")
def exp_object_info(socket, exp_list):
	field = socket.name
	if field == "Location":
		report_warn("Node 'Object Info:Location' Will get inverted Y coordinates, matching UE4 coordinate system.", once=True)
		n = Node("FunctionCall", {"Function": "/DatasmithBlenderContent/MaterialFunctions/Object_Location"})
		exp = exp_list.push(n)
	elif field == "Color":
		report_warn("Node 'Object Info:Color' is not supported by Unreal, writing white color.", once=True)
		exp = exp_vector((1, 1, 1), exp_list)
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


@blender_node("PARTICLE_INFO")
def exp_particle_info(socket, exp_list):
	field = socket.name
	report_warn("Unsupported node 'Particle Info:%s'. Writing value 0." % field, once=True)
	exp = exp_scalar(0, exp_list)

	return {"expression": exp, "OutputIndex": 0}


@blender_node("RGB")
def exp_rgb(socket, exp_list):
	return exp_color(socket.default_value, exp_list, socket.node.label)


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
		flip = Node("FunctionCall", {"Function": MAT_FUNC_FLIPY})
		push_exp_input(flip, "0", exp_uv)
		exp_uv = exp_list.push(flip)

	pad = Node("AppendVector")
	push_exp_input(pad, "0", exp_uv)
	push_exp_input(pad, "1", exp_scalar(0, exp_list))
	return {"expression": exp_list.push(pad)}


@blender_node("TEX_COORD")
def exp_texcoord_node(socket, exp_list):
	socket_name = socket.name
	if socket_name == "Generated":
		output = Node("FunctionCall", {"Function": MAT_FUNC_TEXCOORD_GENERATED})
		return {"expression": exp_list.push(output)}
	if socket_name == "Normal":
		output = Node("VertexNormalWS")
		return {"expression": exp_list.push(output)}
	if socket_name == "UV":
		return exp_texcoord(exp_list)
	if socket_name == "Object":
		output = Node("FunctionCall", {"Function": op_custom_functions["LOCAL_POSITION"]})
		return {"expression": exp_list.push(output)}
	if socket_name == "Camera":
		output = Node("FunctionCall", {"Function": "/DatasmithBlenderContent/MaterialFunctions/TexCoord_Camera"})
		return {"expression": exp_list.push(output)}
	if socket_name == "Window":
		output = Node("FunctionCall", {"Function": "/DatasmithBlenderContent/MaterialFunctions/TexCoord_Window"})
		return {"expression": exp_list.push(output)}
	if socket_name == "Reflection":
		output = Node("ReflectionVectorWS")
		return {"expression": exp_list.push(output)}


@blender_node("UVMAP")
def exp_uvmap(socket, exp_list):
	uv_index = 0
	m = material_owner.data
	if type(m) is bpy.types.Mesh:
		for idx, uv in enumerate(m.uv_layers):
			if uv.name == id:
				uv_index = idx
	return exp_texcoord(exp_list, uv_index)


@blender_node("VALUE")
def exp_value(socket, exp_list):
	node_value = socket.default_value
	n = Node("Scalar", {"constant": "%f" % node_value})
	if socket.node.label:
		n["Name"] = socket.node.label
	return {"expression": exp_list.push(n)}


@blender_node("WIREFRAME")
def exp_wireframe(socket, exp_list):
	report_warn("Unsupported node 'Wireframe'. Writing value 0.", once=True)
	return {"expression": exp_scalar(0, exp_list)}


# Add > Texture


MAT_FUNC_TEXCOORD_GENERATED = "/DatasmithBlenderContent/MaterialFunctions/TexCoord_Generated"


def exp_texcoord_generated(exp_list):
	# this function is used as a generator for default inputs in some tex nodes
	n = Node("FunctionCall", {"Function": MAT_FUNC_TEXCOORD_GENERATED})
	return {"expression": exp_list.push(n)}


VEC_ZERO = Vector()
ROT_ZERO = Euler()
VEC_ONE = Vector((1, 1, 1))


# the generator param is a function that receives the exp_list and returns
# the expression for the default value, for example `exp_texcoord`
def get_expression_mapped(socket, exp_list, generator, force_exp=False):
	# there is this secret menu to the right in TEX_IMAGE nodes that
	# consists in a mapping node + axis reprojection
	# we don't want to create mapping node if not needed
	result_exp = None
	if len(socket.links) != 0:
		result_exp = get_expression(socket, exp_list)

	if result_exp is None and force_exp:
		result_exp = generator(exp_list)
	node = socket.node
	mapping = node.texture_mapping
	mapping_axes = (mapping.mapping_x, mapping.mapping_y, mapping.mapping_z)
	base_axes = ("X", "Y", "Z")
	if mapping_axes != base_axes:
		if not result_exp:
			result_exp = generator(exp_list)

		node_break = Node("FunctionCall", {"Function": MAT_FUNC_BREAK_FLOAT3})
		push_exp_input(node_break, "0", result_exp)
		node_break_exp = exp_list.push(node_break)

		node_make = Node("FunctionCall", {"Function": MAT_FUNC_MAKE_FLOAT3})
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

		n = Node("FunctionCall", {"Function": mapping_func})

		push_exp_input(n, "0", result_exp)
		push_exp_input(n, "1", exp_vector(tx_loc, exp_list))
		push_exp_input(n, "2", exp_vector(tx_rot, exp_list))
		push_exp_input(n, "3", exp_vector(tx_scale, exp_list))

		result_exp = {"expression": exp_list.push(n)}

	return result_exp


tex_dimensions_map = {
	"1D": "1d",
	"2D": "2d",
	"3D": "3d",
	"4D": "4d",
}


@blender_node("TEX_BRICK")
def exp_tex_brick(socket, exp_list):
	node = socket.node

	function_path = "/DatasmithBlenderContent/MaterialFunctions/TexBrick"
	n = Node("FunctionCall", {"Function": function_path})

	inputs = node.inputs
	vector_exp = get_expression_mapped(inputs["Vector"], exp_list, exp_texcoord_generated)
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
	NODE_TEX_BRICK_OUTPUTS = ("Color", "Fac")
	cached_node = (exp_idx, NODE_TEX_BRICK_OUTPUTS)
	cached_nodes[node] = cached_node
	return exp_from_cache(cached_node, socket.name)


@blender_node("TEX_CHECKER")
def exp_tex_checker(socket, exp_list):
	node = socket.node

	inputs = node.inputs
	n = Node("FunctionCall", {"Function": "/DatasmithBlenderContent/MaterialFunctions/TexChecker"})
	vector_exp = get_expression_mapped(inputs["Vector"], exp_list, exp_texcoord_generated)
	push_exp_input(n, "0", vector_exp)
	push_exp_input(n, "1", get_expression(inputs["Color1"], exp_list))
	push_exp_input(n, "2", get_expression(inputs["Color2"], exp_list))
	push_exp_input(n, "3", get_expression(inputs["Scale"], exp_list))

	exp_idx = exp_list.push(n)
	NODE_TEX_CHECKER_OUTPUTS = ("Color", "Fac")
	cached_node = (exp_idx, NODE_TEX_CHECKER_OUTPUTS)
	cached_nodes[node] = cached_node

	return exp_from_cache(cached_node, socket.name)


TEX_GRADIENT_NODE_MAP = {
	"LINEAR": "/DatasmithBlenderContent/MaterialFunctions/TexGradient_Linear",
	"QUADRATIC": "/DatasmithBlenderContent/MaterialFunctions/TexGradient_Quadratic",
	"EASING": "/DatasmithBlenderContent/MaterialFunctions/TexGradient_Easing",
	"DIAGONAL": "/DatasmithBlenderContent/MaterialFunctions/TexGradient_Diagonal",
	"SPHERICAL": "/DatasmithBlenderContent/MaterialFunctions/TexGradient_Spherical",
	"QUADRATIC_SPHERE": "/DatasmithBlenderContent/MaterialFunctions/TexGradient_QuadraticSphere",
	"RADIAL": "/DatasmithBlenderContent/MaterialFunctions/TexGradient_Radial",
}


@blender_node("TEX_GRADIENT")
def exp_tex_gradient(socket, exp_list):
	node = socket.node
	gradient_type = node.gradient_type

	function_path = TEX_GRADIENT_NODE_MAP[gradient_type]
	n = Node("FunctionCall", {"Function": function_path})

	vector_exp = get_expression_mapped(node.inputs["Vector"], exp_list, exp_texcoord_generated)
	push_exp_input(n, "0", vector_exp)

	exp_idx = exp_list.push(n)
	NODE_TEX_GRADIENT_OUTPUTS = ("Color", "Fac")
	cached_node = (exp_idx, NODE_TEX_GRADIENT_OUTPUTS)
	cached_nodes[node] = cached_node
	return exp_from_cache(cached_node, socket.name)


@blender_node("TEX_IMAGE")
def exp_tex_image(socket, exp_list):
	node = socket.node

	image = node.image
	if not image:
		return {"expression": exp_scalar(0, exp_list)}

	should_whitelist = False
	# we use this to know if this texture is behind a normalmap node, so
	# we mark it as non-sRGB+invert green channel
	texture_type = get_context() or "SRGB"
	if texture_type == MAT_CTX_BUMP:
		should_whitelist = True
		texture_type = "SRGB"

	# ensures that texture is exported
	name = get_texture_name(tex_dict, image, texture_type)

	texture_exp = Node("Texture", {"PathName": name})

	tex_coord = get_expression_mapped(node.inputs["Vector"], exp_list, exp_texcoord)

	tex_coord_exp = None
	if tex_coord:
		proj = None
		if node.projection == "FLAT":
			proj = Node("ComponentMask")
		elif node.projection == "BOX":
			proj = Node("FunctionCall", {"Function": "/DatasmithBlenderContent/MaterialFunctions/TexImage_ProjBox"})
		elif node.projection == "SPHERE":
			proj = Node("FunctionCall", {"Function": "/DatasmithBlenderContent/MaterialFunctions/TexImage_ProjSphere"})
		elif node.projection == "TUBE":
			proj = Node("FunctionCall", {"Function": "/DatasmithBlenderContent/MaterialFunctions/TexImage_ProjTube"})
		else:
			log.error("node TEX_IMAGE has unhandled projection: %s" % node.projection)

		push_exp_input(proj, "0", tex_coord)
		tex_coord_exp = {"expression": exp_list.push(proj)}

	if tex_coord_exp:
		if USE_TEXCOORD_FLIP_Y:
			flip = Node("FunctionCall", {"Function": MAT_FUNC_FLIPY})
			push_exp_input(flip, "0", tex_coord_exp)
			tex_coord_exp = {"expression": exp_list.push(flip)}

		texture_exp.push(Node("Coordinates", tex_coord_exp))

	exp_idx = exp_list.push(texture_exp)

	NODE_TEX_IMAGE_OUTPUTS = (0, 0, 0, 0, "Alpha", "Color")
	if texture_type == MAT_CTX_NORMAL:
		NODE_TEX_IMAGE_OUTPUTS = ("Color", "Alpha")
		normal_to_01 = Node("FunctionCall", {"Function": "/DatasmithBlenderContent/MaterialFunctions/NormalTo01"})
		push_exp_input(normal_to_01, "0", exp_idx, 5)
		exp_idx = exp_list.push(normal_to_01)

	cached_node = (exp_idx, NODE_TEX_IMAGE_OUTPUTS)
	cached_nodes[node] = cached_node

	if should_whitelist:
		whitelisted_textures.append({"expression": cached_node[0]})

	return exp_from_cache(cached_node, socket.name)


@blender_node("TEX_MAGIC")
def exp_tex_magic(socket, exp_list):
	node = socket.node

	function_path = "/DatasmithBlenderContent/MaterialFunctions/TexMagic"
	n = Node("FunctionCall", {"Function": function_path})

	inputs = node.inputs
	vector_exp = get_expression_mapped(inputs["Vector"], exp_list, exp_texcoord_generated)
	push_exp_input(n, "0", vector_exp)
	push_exp_input(n, "1", get_expression(inputs["Scale"], exp_list))
	push_exp_input(n, "2", get_expression(inputs["Distortion"], exp_list))
	push_exp_input(n, "3", exp_scalar(node.turbulence_depth, exp_list))

	exp_idx = exp_list.push(n)
	NODE_TEX_MAGIC_OUTPUTS = ("Color", "Fac")
	cached_node = (exp_idx, NODE_TEX_MAGIC_OUTPUTS)
	cached_nodes[node] = cached_node
	return exp_from_cache(cached_node, socket.name)


tex_musgrave_type_map = {
	"MULTIFRACTAL": "multi_fractal",
	"RIDGED_MULTIFRACTAL": "ridged_multi_fractal",
	"HYBRID_MULTIFRACTAL": "hybrid_multi_fractal",
	"FBM": "fBm",
	"HETERO_TERRAIN": "hetero_terrain",
}


@blender_node("TEX_MUSGRAVE")
def exp_tex_musgrave(socket, exp_list):
	node = socket.node

	musgrave_type = tex_musgrave_type_map[node.musgrave_type]
	dimensions = tex_dimensions_map[node.musgrave_dimensions]
	function_name = "node_tex_musgrave_%s_%s" % (musgrave_type, dimensions)

	n = Node(
		"Custom",
		{
			"Description": function_name,
			"OutputType": "1",  # output is scalar,
		},
	)

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

	use_vector = dimensions != "1d"
	if use_vector:
		vector_exp = get_expression_mapped(inputs["Vector"], exp_list, exp_texcoord_generated, force_exp=True)
		push_exp_input(n, "0", vector_exp)
		arguments.append("Vector")
		arguments2.append(("Vector", vector_exp))
	else:
		arguments.append("0")

	use_w = dimensions == "1d" or dimensions == "4d"
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

	return {"expression": exp_list.push(n)}


@blender_node("TEX_NOISE")
def exp_tex_noise(socket, exp_list):
	node = socket.node
	dimensions = tex_dimensions_map[node.noise_dimensions]

	function_path = "/DatasmithBlenderContent/MaterialFunctions/TexNoise_%s" % dimensions
	n = Node("FunctionCall", {"Function": function_path})

	input_idx = 0
	inputs = node.inputs

	def push_input(name):
		nonlocal input_idx
		exp = get_expression(inputs[name], exp_list, skip_default_warn=True)
		assert exp
		push_exp_input(n, input_idx, exp)
		input_idx += 1

	if dimensions != "1d":
		vector_exp = get_expression_mapped(inputs["Vector"], exp_list, exp_texcoord_generated, force_exp=True)
		push_exp_input(n, input_idx, vector_exp)
		input_idx += 1
	if dimensions == "1d" or dimensions == "4d":
		push_input("W")

	push_input("Scale")
	push_input("Detail")
	push_input("Roughness")
	push_input("Distortion")

	exp_idx = exp_list.push(n)
	NODE_TEX_NOISE_OUTPUTS = ("Fac", "Color")
	cached_node = (exp_idx, NODE_TEX_NOISE_OUTPUTS)
	cached_nodes[node] = cached_node
	return exp_from_cache(cached_node, socket.name)


@blender_node("TEX_SKY")
def exp_tex_sky(socket, exp_list):
	report_warn("Unsupported node 'Sky Texture', Writing value 0.", once=True)
	return {"expression": exp_scalar(0, exp_list)}


# these are encoded as float values when sent to the shader code
tex_voronoi_metric_map = {
	"EUCLIDEAN": 0,
	"MANHATTAN": 1,
	"CHEBYCHEV": 2,
	"MINKOWSKI": 3,
}

tex_voronoi_type_map = {
	"F1": "f1",
	"F2": "f2",
	"SMOOTH_F1": "smooth_f1",
	"DISTANCE_TO_EDGE": "distance_to_edge",
	"N_SPHERE_RADIUS": "n_sphere_radius",
}


@blender_node("TEX_VORONOI")
def exp_tex_voronoi(socket, exp_list):
	node = socket.node
	dimensions = tex_dimensions_map[node.voronoi_dimensions]
	voronoi_type = node.feature
	voronoi_type_fn = tex_voronoi_type_map[voronoi_type]

	function_path = "/DatasmithBlenderContent/MaterialFunctions/TexVoronoi_%s_%s" % (voronoi_type_fn, dimensions)
	n = Node("FunctionCall", {"Function": function_path})

	input_idx = 0
	inputs = node.inputs

	def push_input(name):
		nonlocal input_idx
		exp = get_expression(inputs[name], exp_list, skip_default_warn=True)
		assert exp
		push_exp_input(n, input_idx, exp)
		input_idx += 1

	if dimensions != "1d":
		vector_exp = get_expression_mapped(inputs["Vector"], exp_list, exp_texcoord_generated, force_exp=True)
		push_exp_input(n, "0", vector_exp)
		input_idx += 1
	if dimensions == "1d" or dimensions == "4d":
		push_input("W")

	push_input("Scale")

	if voronoi_type == "SMOOTH_F1":
		push_input("Smoothness")

	use_metric = (dimensions != "1d") and (voronoi_type not in ("DISTANCE_TO_EDGE", "N_SPHERE_RADIUS"))
	metric = node.distance
	if use_metric:
		if metric == "MINKOWSKI":
			push_input("Exponent")
		else:
			input_idx += 1

	push_input("Randomness")

	if use_metric:
		metric_float = tex_voronoi_metric_map[metric]
		n.push(exp_input(input_idx, exp_scalar(metric_float, exp_list)))

	NODE_TEX_VORONOI_OUTPUTS = None
	if voronoi_type == "DISTANCE_TO_EDGE":
		NODE_TEX_VORONOI_OUTPUTS = ("Distance",)
	elif voronoi_type == "N_SPHERE_RADIUS":
		NODE_TEX_VORONOI_OUTPUTS = ("Radius",)
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


@blender_node("TEX_WAVE")
def exp_tex_wave(socket, exp_list):
	node = socket.node
	wave_type = node.wave_type
	wave_type_val = 0
	direction_val = 0
	if wave_type == "BANDS":
		wave_type_val = 0
		direction_val = ("X", "Y", "Z", "DIAGONAL").index(node.bands_direction)
	elif wave_type == "RINGS":
		wave_type_val = 1
		direction_val = ("X", "Y", "Z", "SPHERICAL").index(node.rings_direction)

	profile_val = ("SIN", "SAW", "TRI").index(node.wave_profile)

	function_path = "/DatasmithBlenderContent/MaterialFunctions/TexWave"
	n = Node("FunctionCall", {"Function": function_path})

	inputs = node.inputs
	vector_exp = get_expression_mapped(inputs["Vector"], exp_list, exp_texcoord_generated)
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
	NODE_TEX_WAVE_OUTPUTS = ("Color", "Fac")
	cached_node = (exp_idx, NODE_TEX_WAVE_OUTPUTS)
	cached_nodes[node] = cached_node
	return exp_from_cache(cached_node, socket.name)


@blender_node("TEX_WHITE_NOISE")
def exp_tex_white_noise(socket, exp_list):
	node = socket.node
	dimensions = tex_dimensions_map[node.noise_dimensions]

	function_path = "/DatasmithBlenderContent/MaterialFunctions/TexWhiteNoise_%s" % dimensions
	n = Node("FunctionCall", {"Function": function_path})

	input_idx = 0
	inputs = node.inputs

	if dimensions != "1d":
		exp = get_expression(inputs["Vector"], exp_list, skip_default_warn=True)
		push_exp_input(n, input_idx, exp)
		input_idx += 1
	if dimensions == "1d" or dimensions == "4d":
		exp = get_expression(inputs["W"], exp_list, skip_default_warn=True)
		push_exp_input(n, input_idx, exp)

	exp_idx = exp_list.push(n)
	NODE_TEX_WHITE_NOISE_OUTPUTS = ("Value", "Color")
	cached_node = (exp_idx, NODE_TEX_WHITE_NOISE_OUTPUTS)
	cached_nodes[node] = cached_node
	return exp_from_cache(cached_node, socket.name)


# Add > Color


op_custom_functions = {
	"BRIGHTCONTRAST": "/DatasmithBlenderContent/MaterialFunctions/BrightContrast",
	"COLOR_RAMP": "/DatasmithBlenderContent/MaterialFunctions/ColorRamp",
	"CURVE_RGB": "/DatasmithBlenderContent/MaterialFunctions/RGBCurveLookup2",
	"FRESNEL": "/DatasmithBlenderContent/MaterialFunctions/BlenderFresnel",
	"HUE_SAT": "/DatasmithBlenderContent/MaterialFunctions/AdjustHSV",
	"LAYER_WEIGHT": "/DatasmithBlenderContent/MaterialFunctions/LayerWeight",
	"LOCAL_POSITION": "/DatasmithBlenderContent/MaterialFunctions/BlenderLocalPosition",
	"NORMAL_FROM_HEIGHT": "/Engine/Functions/Engine_MaterialFunctions03/Procedurals/NormalFromHeightmap",
}


@blender_node("BRIGHTCONTRAST")
def exp_bright_contrast(socket, exp_list):
	node = socket.node
	n = Node("FunctionCall", {"Function": op_custom_functions["BRIGHTCONTRAST"]})
	for idx, socket_name in enumerate(("Color", "Bright", "Contrast")):
		input_expression = get_expression(node.inputs[socket_name], exp_list)
		n.push(exp_input(idx, input_expression))
	return {"expression": exp_list.push(n)}


@blender_node("GAMMA")
def exp_gamma(socket, exp_list):
	node = socket.node
	n = Node(MATH_TWO_INPUTS["POWER"])
	exp_0 = get_expression(node.inputs["Color"], exp_list)
	n.push(exp_input("0", exp_0))
	exp_1 = get_expression(node.inputs["Gamma"], exp_list)
	n.push(exp_input("1", exp_1))
	return {"expression": exp_list.push(n)}


@blender_node("HUE_SAT")
def exp_hsv(socket, exp_list):
	node = socket.node
	n = Node("FunctionCall", {"Function": op_custom_functions["HUE_SAT"]})
	exp_hue = get_expression(node.inputs["Hue"], exp_list)
	n.push(exp_input("0", exp_hue))
	exp_sat = get_expression(node.inputs["Saturation"], exp_list)
	n.push(exp_input("1", exp_sat))
	exp_value = get_expression(node.inputs["Value"], exp_list)
	n.push(exp_input("2", exp_value))
	exp_fac = get_expression(node.inputs["Fac"], exp_list)
	n.push(exp_input("3", exp_fac))
	exp_color = get_expression(node.inputs["Color"], exp_list)
	n.push(exp_input("4", exp_color))
	return {"expression": exp_list.push(n), "OutputIndex": 0}


@blender_node("INVERT")
def exp_invert(socket, exp_list):
	node = socket.node
	n = Node("OneMinus")
	exp_color = get_expression(node.inputs["Color"], exp_list)
	n.push(exp_input("0", exp_color))
	invert_exp = exp_list.push(n)

	blend = Node("LinearInterpolate")
	exp_fac = get_expression(node.inputs["Fac"], exp_list)
	blend.push(exp_input("0", exp_color))
	blend.push(exp_input("1", {"expression": invert_exp}))
	blend.push(exp_input("2", exp_fac))

	return {"expression": exp_list.push(blend)}


@blender_node("LIGHT_FALLOFF")
def exp_light_falloff(socket, exp_list):
	report_warn("Unsupported node 'Light Falloff', returning unmodified light strength", once=True)
	exp = get_expression(socket.node.inputs["Strength"], exp_list)
	return {"expression": exp}


op_map_blend = {
	"MIX": "/DatasmithBlenderContent/MaterialFunctions/Blend_Mix",
	"DARKEN": "/DatasmithBlenderContent/MaterialFunctions/Blend_Darken",
	"MULTIPLY": "/DatasmithBlenderContent/MaterialFunctions/Blend_Multiply",
	"BURN": "/DatasmithBlenderContent/MaterialFunctions/Blend_ColorBurn",
	"LIGHTEN": "/DatasmithBlenderContent/MaterialFunctions/Blend_Lighten",
	"SCREEN": "/DatasmithBlenderContent/MaterialFunctions/Blend_Screen",
	"DODGE": "/DatasmithBlenderContent/MaterialFunctions/Blend_Dodge",
	"ADD": "/DatasmithBlenderContent/MaterialFunctions/Blend_Add",
	"OVERLAY": "/DatasmithBlenderContent/MaterialFunctions/Blend_Overlay",
	"SOFT_LIGHT": "/DatasmithBlenderContent/MaterialFunctions/Blend_SoftLight",
	"LINEAR_LIGHT": "/DatasmithBlenderContent/MaterialFunctions/Blend_LinearLight",
	"DIFFERENCE": "/DatasmithBlenderContent/MaterialFunctions/Blend_Difference",
	"EXCLUSION": "/DatasmithBlenderContent/MaterialFunctions/Blend_Exclusion",
	"SUBTRACT": "/DatasmithBlenderContent/MaterialFunctions/Blend_Subtract",
	"DIVIDE": "/DatasmithBlenderContent/MaterialFunctions/Blend_Divide",
	"HUE": "/DatasmithBlenderContent/MaterialFunctions/Blend_Hue",
	"SATURATION": "/DatasmithBlenderContent/MaterialFunctions/Blend_Saturation",
	"COLOR": "/DatasmithBlenderContent/MaterialFunctions/Blend_Color",
	"VALUE": "/DatasmithBlenderContent/MaterialFunctions/Blend_Value",
}


@blender_node("MIX_RGB")
def exp_mixrgb(socket, exp_list):
	node = socket.node
	inputs = node.inputs
	exp_t = get_expression(inputs["Fac"], exp_list)
	# blender did always clamp factor input for color blends
	# doesn't do it forcefully in new mix node because it is optional
	t_clamped = Node("Saturate")
	push_exp_input(t_clamped, 0, exp_t)
	exp_t2 = exp_list.push(t_clamped)

	exp_a = get_expression(inputs["Color1"], exp_list)
	exp_b = get_expression(inputs["Color2"], exp_list)

	blend = Node("FunctionCall", {"Function": op_map_blend[node.blend_type]})
	push_exp_input(blend, 0, exp_t2)
	push_exp_input(blend, 1, exp_a)
	push_exp_input(blend, 2, exp_b)
	exp_blend = exp_list.push(blend)

	if node.use_clamp:
		clamp = Node("Saturate")
		push_exp_input(clamp, "0", exp_blend)
		exp_blend = exp_list.push(clamp)

	return {"expression": exp_blend, "OutputIndex": 0}


def exp_texture_object(name, exp_list):
	n = Node("TextureObject")
	n.push(
		Node(
			"Input",
			{
				"name": "Texture",
				"type": "Texture",
				"val": name,
			},
		)
	)
	return exp_list.push(n)


@blender_node("CURVE_RGB")
def exp_curvergb(socket, exp_list):
	from_node = socket.node
	mapping = from_node.mapping
	mapping.initialize()

	idx = add_material_curve(mapping)

	factor = get_expression(from_node.inputs["Fac"], exp_list)
	color = get_expression(from_node.inputs["Color"], exp_list)

	curve_idx = exp_scalar(idx, exp_list)
	vertical_res = exp_scalar(DATASMITH_TEXTURE_SIZE, exp_list)  # curves texture size

	texture = exp_texture_object(BLENDER_CURVES_NAME, exp_list)

	lookup = Node("FunctionCall", {"Function": op_custom_functions["CURVE_RGB"]})
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
	return {"expression": result, "OutputIndex": 0}


# Add > Vector


@blender_node("BUMP")
def exp_bump(socket, exp_list):
	node = socket.node
	MAT_FUNC_BUMP = "/DatasmithBlenderContent/MaterialFunctions/Bump"
	bump_node = Node("FunctionCall", {"Function": MAT_FUNC_BUMP})

	exp_invert = exp_scalar(-1 if node.invert else 1, exp_list)
	push_exp_input(bump_node, "0", exp_invert)

	push_texture_context(MAT_CTX_BUMP)
	inputs = node.inputs
	push_exp_input(bump_node, "1", get_expression(inputs["Strength"], exp_list))
	push_exp_input(bump_node, "2", get_expression(inputs["Distance"], exp_list))
	push_exp_input(bump_node, "3", get_expression(inputs["Height"], exp_list))
	pop_texture_context()

	push_exp_input(bump_node, "4", get_expression(inputs["Normal"], exp_list, skip_default_warn=True))
	return {"expression": exp_list.push(bump_node)}


MAT_FUNC_MAPPINGS = {
	"NORMAL": "/DatasmithBlenderContent/MaterialFunctions/MappingNormal",
	"POINT": "/DatasmithBlenderContent/MaterialFunctions/MappingPoint3D",
	"TEXTURE": "/DatasmithBlenderContent/MaterialFunctions/MappingTexture3D",
	"VECTOR": "/DatasmithBlenderContent/MaterialFunctions/MappingVector",
}


@blender_node("MAPPING")
def exp_mapping(socket, exp_list):
	node = socket.node
	mapping_func = MAT_FUNC_MAPPINGS[node.vector_type]

	n = Node("FunctionCall", {"Function": mapping_func})

	input_vector = get_expression(node.inputs["Vector"], exp_list)
	input_rotation = get_expression(node.inputs["Rotation"], exp_list)
	input_scale = get_expression(node.inputs["Scale"], exp_list)

	n.push(exp_input("0", input_vector))
	if node.vector_type not in ("NORMAL", "VECTOR"):
		input_location = get_expression(node.inputs["Location"], exp_list)
		n.push(exp_input("1", input_location))

	n.push(exp_input("2", input_rotation))
	n.push(exp_input("3", input_scale))

	return {"expression": exp_list.push(n)}


@blender_node("NORMAL")
def exp_normal(socket, exp_list):
	node = socket.node
	n = Node("FunctionCall", {"Function": "/DatasmithBlenderContent/MaterialFunctions/Normal"})
	push_exp_input(n, "0", exp_vector(node.outputs[0].default_value, exp_list))
	push_exp_input(n, "1", get_expression(node.inputs[0], exp_list))
	exp = exp_list.push(n)

	NODE_NORMAL_OUTPUTS = ("Normal", "Dot")
	cached_node = (exp, NODE_NORMAL_OUTPUTS)
	cached_nodes[node] = cached_node
	return exp_from_cache(cached_node, socket.name)


@blender_node("NORMAL_MAP")
def exp_normal_map(socket, exp_list):
	input_strength = socket.node.inputs["Strength"]
	exp_strength = get_expression(input_strength, exp_list)

	# hack: is it safe to assume that everything under here is normal?
	# maybe not, because it could be masks to mix normals
	# most certainly, these wouldn't be colors (so should be non-srgb nonetheless)
	input_color = socket.node.inputs["Color"]
	push_texture_context(MAT_CTX_NORMAL)
	exp_color = get_expression(input_color, exp_list)
	pop_texture_context()

	node_strength = Node("FunctionCall", {"Function": "/DatasmithBlenderContent/MaterialFunctions/NormalStrength"})
	push_exp_input(node_strength, "0", exp_strength)
	push_exp_input(node_strength, "1", exp_color)
	return {"expression": exp_list.push(node_strength)}


VECT_TRANSFORM_TYPE = ("POINT", "VECTOR", "NORMAL")

VECT_TRANSFORM_RENAME_MAP = {
	"WORLD": "World",
	"CAMERA": "Camera",
	"OBJECT": "Object",
}


@blender_node("VECT_TRANSFORM")
def exp_vect_transform(socket, exp_list):
	node = socket.node

	input_exp = get_expression(node.inputs[0], exp_list)
	if node.convert_from == node.convert_to:
		return input_exp

	name_from = VECT_TRANSFORM_RENAME_MAP[node.convert_from]
	name_to = VECT_TRANSFORM_RENAME_MAP[node.convert_to]
	func_path = "/DatasmithBlenderContent/MaterialFunctions/VectorTransform%sTo%s" % (name_from, name_to)
	output = Node("FunctionCall", {"Function": func_path})
	push_exp_input(output, "0", input_exp)

	output_index = VECT_TRANSFORM_TYPE.index(node.vector_type)
	if node.vector_type == "NORMAL":
		report_warn("Unsupported vector type:Normal in Vector Transform node. FIXME", once=True)
	return {"expression": exp_list.push(output), "OutputIndex": output_index}


MAT_FUNC_VECTOR_ROTATE_ANGLEAXIS = "/DatasmithBlenderContent/MaterialFunctions/VectorRotateAngleAxis"
MAT_FUNC_VECTOR_ROTATE_EULERANGLES = "/DatasmithBlenderContent/MaterialFunctions/VectorRotateEulerAngles"


@blender_node("VECTOR_ROTATE")
def exp_vector_rotate(socket, exp_list):
	node = socket.node
	inputs = node.inputs

	rotation_type = node.rotation_type
	node_fn = MAT_FUNC_VECTOR_ROTATE_ANGLEAXIS
	if rotation_type == "EULER_XYZ":
		node_fn = MAT_FUNC_VECTOR_ROTATE_EULERANGLES

	node_rotate = Node("FunctionCall", {"Function": node_fn})
	push_exp_input(node_rotate, "0", exp_scalar(-1 if node.invert else 1, exp_list))  # Sign
	push_exp_input(node_rotate, "1", get_expression(inputs["Vector"], exp_list))  # Vector
	push_exp_input(node_rotate, "2", get_expression(inputs["Center"], exp_list, force_default=True))  # Center

	if rotation_type == "EULER_XYZ":
		push_exp_input(node_rotate, "3", get_expression(inputs["Rotation"], exp_list))
	else:
		axis = None
		if rotation_type == "X_AXIS":
			axis = exp_vector((1, 0, 0), exp_list)
		elif rotation_type == "Y_AXIS":
			axis = exp_vector((0, 1, 0), exp_list)
		elif rotation_type == "Z_AXIS":
			axis = exp_vector((0, 0, 1), exp_list)
		else:
			axis = get_expression(inputs["Axis"], exp_list, force_default=True)
		push_exp_input(node_rotate, "3", axis)
		push_exp_input(node_rotate, "4", get_expression(inputs["Angle"], exp_list))

	return {"expression": exp_list.push(node_rotate)}


# Add > Converter


@blender_node("BLACKBODY")
def exp_blackbody(socket, exp_list):
	from_node = socket.node
	n = Node("BlackBody")
	exp_0 = get_expression(from_node.inputs[0], exp_list)
	n.push(exp_input("0", exp_0))
	exp = exp_list.push(n)
	return {"expression": exp}


@blender_node("CLAMP")
def exp_clamp(socket, exp_list):
	node = socket.node
	clamp_type = node.clamp_type

	value = get_expression(node.inputs["Value"], exp_list)
	clamp_min = get_expression(node.inputs["Min"], exp_list)
	clamp_max = get_expression(node.inputs["Max"], exp_list)

	n = Node("Clamp")

	if clamp_type == "MINMAX":
		n.push(exp_input("0", value))
		n.push(exp_input("1", clamp_min))
		n.push(exp_input("2", clamp_max))

	elif clamp_type == "RANGE":
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


@blender_node("VALTORGB")
def exp_color_ramp(socket, exp_list):
	from_node = socket.node
	ramp = from_node.color_ramp

	idx = add_material_curve(ramp)

	level = get_expression(from_node.inputs["Fac"], exp_list)

	curve_idx = exp_scalar(idx, exp_list)

	vertical_res = exp_scalar(DATASMITH_TEXTURE_SIZE, exp_list)  # curves texture size
	texture = exp_texture_object(BLENDER_CURVES_NAME, exp_list)

	lookup = Node("FunctionCall", {"Function": op_custom_functions["COLOR_RAMP"]})
	lookup.push(exp_input("0", level))
	lookup.push(exp_input("1", curve_idx))
	lookup.push(exp_input("2", vertical_res))
	lookup.push(exp_input("3", texture))
	result = exp_list.push(lookup)
	return {"expression": result, "OutputIndex": 0}


MAT_FUNC_MAKE_FLOAT3 = "/Engine/Functions/Engine_MaterialFunctions02/Utility/MakeFloat3"


@blender_node("COMBXYZ")
def exp_make_vec3(socket, exp_list):
	node = socket.node
	output = Node("FunctionCall", {"Function": MAT_FUNC_MAKE_FLOAT3})
	output.push(exp_input("0", get_expression(node.inputs[0], exp_list)))
	output.push(exp_input("1", get_expression(node.inputs[1], exp_list)))
	output.push(exp_input("2", get_expression(node.inputs[2], exp_list)))
	return {"expression": exp_list.push(output)}


MAT_FUNC_COMBINE_RGB = "/DatasmithBlenderContent/MaterialFunctions/CombineRGB"


@blender_node("COMBRGB")
def exp_combine_rgb(socket, exp_list):
	node = socket.node
	output = Node("FunctionCall", {"Function": MAT_FUNC_COMBINE_RGB})
	output.push(exp_input("0", get_expression(node.inputs[0], exp_list)))
	output.push(exp_input("1", get_expression(node.inputs[1], exp_list)))
	output.push(exp_input("2", get_expression(node.inputs[2], exp_list)))
	return {"expression": exp_list.push(output)}


MAT_FUNC_HSV_TO_RGB = "/DatasmithBlenderContent/MaterialFunctions/HSV_To_RGB"


@blender_node("COMBHSV")
def exp_make_hsv(socket, exp_list):
	inputs = socket.node.inputs
	output = Node("FunctionCall", {"Function": MAT_FUNC_HSV_TO_RGB})
	push_exp_input(output, "0", get_expression(inputs[0], exp_list))
	push_exp_input(output, "1", get_expression(inputs[1], exp_list))
	push_exp_input(output, "2", get_expression(inputs[2], exp_list))
	return {"expression": exp_list.push(output)}


NODE_COMBINE_COLOR_MAP = {
	"RGB": MAT_FUNC_COMBINE_RGB,
	"HSV": MAT_FUNC_HSV_TO_RGB,
	# TODO: implement HSL
}


@blender_node("COMBINE_COLOR")
def exp_combine_color(socket, exp_list):
	node = socket.node
	func_path = NODE_COMBINE_COLOR_MAP[node.mode]
	output = Node("FunctionCall", {"Function": func_path})
	inputs = node.inputs
	push_exp_input(output, "0", get_expression(inputs[0], exp_list))
	push_exp_input(output, "1", get_expression(inputs[1], exp_list))
	push_exp_input(output, "2", get_expression(inputs[2], exp_list))
	return {"expression": exp_list.push(output)}


NODE_BREAK_XYZ_OUTPUTS = ("X", "Y", "Z")
MAT_FUNC_BREAK_FLOAT3 = "/Engine/Functions/Engine_MaterialFunctions02/Utility/BreakOutFloat3Components"


@blender_node("SEPXYZ")
def exp_break_vec3(socket, exp_list):
	node = socket.node
	output = Node("FunctionCall", {"Function": MAT_FUNC_BREAK_FLOAT3})
	output.push(exp_input("0", get_expression(node.inputs[0], exp_list)))
	expression_idx = exp_list.push(output)

	cached_node = (expression_idx, NODE_BREAK_XYZ_OUTPUTS)
	cached_nodes[node] = cached_node
	return exp_from_cache(cached_node, socket.name)


NODE_BREAK_RGB_OUTPUTS = ("R", "G", "B")
MAT_FUNC_SEPRGB = "/DatasmithBlenderContent/MaterialFunctions/SeparateRGB"


@blender_node("SEPRGB")
def exp_seprgb(socket, exp_list):
	node = socket.node
	output = Node("FunctionCall", {"Function": MAT_FUNC_SEPRGB})
	output.push(exp_input("0", get_expression(node.inputs[0], exp_list)))
	expression_idx = exp_list.push(output)

	cached_node = (expression_idx, NODE_BREAK_RGB_OUTPUTS)
	cached_nodes[node] = cached_node
	return exp_from_cache(cached_node, socket.name)


MAT_FUNC_RGB_TO_HSV = "/DatasmithBlenderContent/MaterialFunctions/RGB_To_HSV"
NODE_BREAK_HSV_OUTPUTS = ("H", "S", "V")


@blender_node("SEPHSV")
def exp_break_hsv(socket, exp_list):
	output = Node("FunctionCall", {"Function": MAT_FUNC_RGB_TO_HSV})
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
	# TODO: implement HSL
}


@blender_node("SEPARATE_COLOR")
def exp_separate_color(socket, exp_list):
	node = socket.node

	func_path = NODE_SEPARATE_COLOR_MAP[node.mode]

	output = Node("FunctionCall", {"Function": func_path})
	push_exp_input(output, "0", get_expression(node.inputs[0], exp_list))
	expression_idx = exp_list.push(output)

	cached_node = (expression_idx, NODE_SEPARATE_COLOR_OUTPUTS)
	cached_nodes[node] = cached_node
	return exp_from_cache(cached_node, socket.name)


MAT_FUNC_RGB_TO_BW = "/DatasmithBlenderContent/MaterialFunctions/RGB_To_BW"


@blender_node("RGBTOBW")
def exp_rgb_to_bw(socket, exp_list):
	input_exp = get_expression(socket.node.inputs[0], exp_list)
	n = Node("FunctionCall", {"Function": MAT_FUNC_RGB_TO_BW})
	push_exp_input(n, "0", input_exp)
	n_exp = exp_list.push(n)
	return {"expression": n_exp}


MAT_FUNC_MAPRANGE_LINEAR = "/DatasmithBlenderContent/MaterialFunctions/MapRange_Linear"
MAT_FUNC_MAPRANGE_LINEAR_CLAMPED = "/DatasmithBlenderContent/MaterialFunctions/MapRange_Linear_Clamped"
MAT_FUNC_MAPRANGE_STEPPED = "/DatasmithBlenderContent/MaterialFunctions/MapRange_Stepped"
MAT_FUNC_MAPRANGE_STEPPED_CLAMPED = "/DatasmithBlenderContent/MaterialFunctions/MapRange_Stepped_Clamped"
MAT_FUNC_MAPRANGE_SMOOTHSTEP = "/DatasmithBlenderContent/MaterialFunctions/MapRange_SmoothStep"
MAT_FUNC_MAPRANGE_SMOOTHERSTEP = "/DatasmithBlenderContent/MaterialFunctions/MapRange_SmootherStep"


@blender_node("MAP_RANGE")
def exp_map_range(socket, exp_list):
	node = socket.node
	interpolation_type = node.interpolation_type
	func_path = None
	if interpolation_type == "LINEAR":
		if node.clamp:
			func_path = MAT_FUNC_MAPRANGE_LINEAR_CLAMPED
		else:
			func_path = MAT_FUNC_MAPRANGE_LINEAR
	elif interpolation_type == "STEPPED":
		if node.clamp:
			func_path = MAT_FUNC_MAPRANGE_STEPPED_CLAMPED
		else:
			func_path = MAT_FUNC_MAPRANGE_STEPPED
	elif interpolation_type == "SMOOTHSTEP":
		func_path = MAT_FUNC_MAPRANGE_SMOOTHSTEP
	elif interpolation_type == "SMOOTHERSTEP":
		func_path = MAT_FUNC_MAPRANGE_SMOOTHERSTEP

	assert func_path

	value = get_expression(node.inputs["Value"], exp_list)
	from_min = get_expression(node.inputs["From Min"], exp_list)
	from_max = get_expression(node.inputs["From Max"], exp_list)
	to_min = get_expression(node.inputs["To Min"], exp_list)
	to_max = get_expression(node.inputs["To Max"], exp_list)

	n = Node("FunctionCall", {"Function": func_path})
	n.push(exp_input("0", value))
	n.push(exp_input("1", from_min))
	n.push(exp_input("2", from_max))
	n.push(exp_input("3", to_min))
	n.push(exp_input("4", to_max))

	if interpolation_type == "STEPPED":
		steps = get_expression(node.inputs["Steps"], exp_list)
		n.push(exp_input("5", steps))

	return {"expression": exp_list.push(n)}


def exp_generic(name, inputs, exp_list, force_default=False):
	n = Node(name)
	for idx, input in enumerate(inputs):
		input_exp = get_expression(input, exp_list, force_default)
		n.push(exp_input(idx, input_exp))
	return {"expression": exp_list.push(n)}


def exp_function_call(path, inputs, exp_list, force_default=False):
	n = Node("FunctionCall", {"Function": path})
	if inputs:
		for idx, input in enumerate(inputs):
			input_exp = get_expression(input, exp_list, force_default)
			n.push(exp_input(idx, input_exp))
	return {"expression": exp_list.push(n)}


MATH_CUSTOM_FUNCTIONS = {
	"INVERSE_SQRT": (1, "/DatasmithBlenderContent/MaterialFunctions/MathInvSqrt"),
	"EXPONENT": (1, "/DatasmithBlenderContent/MaterialFunctions/MathExp"),
	"SINH": (1, "/DatasmithBlenderContent/MaterialFunctions/MathSinH"),
	"COSH": (1, "/DatasmithBlenderContent/MaterialFunctions/MathCosH"),
	"TANH": (1, "/DatasmithBlenderContent/MaterialFunctions/MathTanH"),
	"MULTIPLY_ADD": (3, "/DatasmithBlenderContent/MaterialFunctions/MathMultiplyAdd"),
	"COMPARE": (3, "/DatasmithBlenderContent/MaterialFunctions/MathCompare"),
	"SMOOTH_MIN": (3, "/DatasmithBlenderContent/MaterialFunctions/MathSmoothMin"),
	"SMOOTH_MAX": (3, "/DatasmithBlenderContent/MaterialFunctions/MathSmoothMax"),
	"WRAP": (3, "/DatasmithBlenderContent/MaterialFunctions/MathWrap"),
	"SNAP": (2, "/DatasmithBlenderContent/MaterialFunctions/MathSnap"),
	"PINGPONG": (2, "/DatasmithBlenderContent/MaterialFunctions/MathPingPong"),
}

# these map 1:1 with UE4 nodes:
MATH_TWO_INPUTS = {
	"ADD": "Add",
	"SUBTRACT": "Subtract",
	"MULTIPLY": "Multiply",
	"DIVIDE": "Divide",
	"POWER": "Power",
	"MINIMUM": "Min",
	"MAXIMUM": "Max",
	"MODULO": "Fmod",
	"ARCTAN2": "Arctangent2",
}

# these use only one input in UE4
MATH_ONE_INPUT = {
	"SQRT": "SquareRoot",
	"ABSOLUTE": "Abs",
	"ROUND": "Round",
	"FLOOR": "Floor",
	"CEIL": "Ceil",
	"FRACT": "Frac",
	"SINE": "Sine",
	"COSINE": "Cosine",
	"TANGENT": "Tangent",
	"ARCSINE": "Arcsine",
	"ARCCOSINE": "Arccosine",
	"ARCTANGENT": "Arctangent",
	"SIGN": "Sign",
	"TRUNC": "Truncate",
}

# these require specific implementations:
MATH_CUSTOM_IMPL = {
	"LOGARITHM",  # ue4 only has log2 and log10
	"LESS_THAN",  # use UE4 If node
	"GREATER_THAN",  # use UE4 If node
	"RADIANS",
	"DEGREES",
}


@blender_node("MATH")
def exp_math(socket, exp_list):
	node = socket.node
	op = node.operation
	exp = None
	if op in MATH_TWO_INPUTS:
		exp = exp_generic(
			name=MATH_TWO_INPUTS[op],
			inputs=node.inputs[:2],
			exp_list=exp_list,
			force_default=True,
		)
	elif op in MATH_ONE_INPUT:
		exp = exp_generic(
			name=MATH_ONE_INPUT[op],
			inputs=node.inputs[:1],
			exp_list=exp_list,
			force_default=True,
		)
	elif op in MATH_CUSTOM_FUNCTIONS:
		size, path = MATH_CUSTOM_FUNCTIONS[op]
		exp = exp_function_call(
			path,
			inputs=node.inputs[:size],
			exp_list=exp_list,
		)
	elif op in MATH_CUSTOM_IMPL:
		in_0 = get_expression(node.inputs[0], exp_list)
		n = None
		if op == "RADIANS":
			n = Node("Multiply")
			n.push(exp_input("0", in_0))
			n.push(exp_input("1", {"expression": exp_scalar(math.tau / 360, exp_list)}))
		elif op == "DEGREES":
			n = Node("Multiply")
			n.push(exp_input("0", in_0))
			n.push(exp_input("1", {"expression": exp_scalar(360 / math.tau, exp_list)}))
		else:
			# these use two inputs
			in_1 = get_expression(node.inputs[1], exp_list)
			if op == "LOGARITHM":  # take two logarithms and divide
				log0 = Node("Logarithm2")
				log0.push(exp_input("0", in_0))
				exp_0 = exp_list.push(log0)
				log1 = Node("Logarithm2")
				log1.push(exp_input("0", in_1))
				exp_1 = exp_list.push(log1)
				n = Node("Divide")
				n.push(exp_input("0", {"expression": exp_0}))
				n.push(exp_input("1", {"expression": exp_1}))
			elif op == "LESS_THAN":
				n = Node("If")
				one = {"expression": exp_scalar(1.0, exp_list)}
				zero = {"expression": exp_scalar(0.0, exp_list)}
				n.push(exp_input("0", in_0))  # A
				n.push(exp_input("1", in_1))  # B
				n.push(exp_input("2", zero))  # A > B
				n.push(exp_input("3", one))  # A == B
				n.push(exp_input("4", one))  # A < B
			elif op == "GREATER_THAN":
				n = Node("If")
				one = {"expression": exp_scalar(1.0, exp_list)}
				zero = {"expression": exp_scalar(0.0, exp_list)}
				n.push(exp_input("0", in_0))  # A
				n.push(exp_input("1", in_1))  # B
				n.push(exp_input("2", one))  # A > B
				n.push(exp_input("3", zero))  # A == B
				n.push(exp_input("4", zero))  # A < B
		assert n
		exp = {"expression": exp_list.push(n)}

	assert exp, "unrecognized math operation: %s" % op

	if getattr(node, "use_clamp", False):
		clamp = Node("Saturate")
		clamp.push(exp_input("0", exp))
		exp = {"expression": exp_list.push(clamp)}
	return exp


# these nodes should only be built-ins (green nodes)
VECT_MATH_SAME_AS_SCALAR = {
	"ADD",
	"SUBTRACT",
	"MULTIPLY",
	"DIVIDE",
	"ABSOLUTE",
	"MINIMUM",
	"MAXIMUM",
	"FLOOR",
	"CEIL",
	"MODULO",
	"SINE",
	"COSINE",
	"TANGENT",
}


VECT_MATH_NODES = {
	"CROSS_PRODUCT": (2, "CrossProduct"),
	"DOT_PRODUCT": (2, "DotProduct"),
	"DISTANCE": (2, "Distance"),
	"NORMALIZE": (1, "Normalize"),
	"FRACTION": (1, "Frac"),
}
VECT_MATH_FUNCTIONS = {  # tuples are (input_count, path)
	"WRAP": (3, "/DatasmithBlenderContent/MaterialFunctions/VectWrap"),
	"SNAP": (2, "/DatasmithBlenderContent/MaterialFunctions/VectSnap"),
	"PROJECT": (2, "/DatasmithBlenderContent/MaterialFunctions/VectProject"),
	"REFLECT": (2, "/DatasmithBlenderContent/MaterialFunctions/VectReflect"),
}


@blender_node("VECT_MATH")
def exp_vect_math(socket, exp_list):
	node = socket.node
	node_op = node.operation
	if node_op in VECT_MATH_SAME_AS_SCALAR:
		return exp_math(socket, exp_list)
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
			inputs=node.inputs[:size],
			exp_list=exp_list,
			force_default=True,
		)
	elif node_op == "SCALE":
		return exp_generic(
			name="Multiply",
			inputs=(node.inputs[0], node.inputs[3]),
			exp_list=exp_list,
			force_default=True,
		)
	elif node_op == "LENGTH":
		n = Node("Distance")
		n.push(exp_input("0", get_expression(node.inputs[0], exp_list)))
		n.push(exp_input("1", exp_vector((0, 0, 0), exp_list)))
		return {"expression": exp_list.push(n)}

	log.error("VECT_MATH node operation:%s not found" % node_op)


@blender_node("SHADERTORGB")
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


EXP_MIX_FACTOR_SCALAR = 0
EXP_MIX_FACTOR_VECTOR = 1
EXP_MIX_A_SCALAR = 2
EXP_MIX_B_SCALAR = 3
EXP_MIX_A_VECTOR = 4
EXP_MIX_B_VECTOR = 5
EXP_MIX_A_RGBA = 6
EXP_MIX_B_RGBA = 7


@blender_node("MIX")
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
		assert False
		print("ERROR! unknown data type")

	if data_type == "FLOAT" or data_type == "VECTOR":
		result = Node("LinearInterpolate")
		push_exp_input(result, 0, in_a)
		push_exp_input(result, 1, in_b)
		push_exp_input(result, 2, in_factor)
	else:
		assert data_type == "RGBA"
		result = Node("FunctionCall", {"Function": op_map_blend[node.blend_type]})
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
