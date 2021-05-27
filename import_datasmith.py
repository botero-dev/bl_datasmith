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

matrix_datasmith = Matrix.Scale(100, 4)
matrix_datasmith[1][1] *= -1.0

matrix_datasmith2 = Matrix.Scale(1, 4)
matrix_datasmith2[1][1] *= -1.0

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


def handle_transform(node, iter):
        p = lambda x: float(node.attrib[x])
        loc =   (p("tx"), p("ty"), p("tz"))
        print('LOC', loc)
        rot =   (p("qw"), p("qx"), p("qy"), p("qz"))
        scale = (p("sx"), p("sy"), p("sz"))

        action, closing = next(iter)
        assert action == "end"
        assert closing == node

        return (loc, rot, scale)

# may be named parse_light_color?
def handle_color(node, iter):
        attr = node.attrib
        use_temp = attr['usetemp']

        color = (attr['R'], attr['G'], attr['B'])

        action, closing = next(iter)
        assert action == "end"
        assert closing == node

        return color

def unhandled(_ctx, node, iter):
        if node.tag == "material":
                import pdb
                pdb.set_trace()
        print (f"<{node.tag} UNHANDLED>")
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
        assert visible_str != "True" # just ensuring that we're not dealing with this
        assert visible_str != "TRUE"
        visible = visible_str == "true"
        # we also have "selector" (bool) and "selection" (int) which we won't check for now

        for action, child in iter:
                if action == 'end':
                        break
                actor_child = handle_actor_common(None, child, iter)
                assert actor_child != None
                target["children"].append(actor_child)

        assert child == node
        assert action == 'end'

def check_close(node, iter):
        action, child = next(iter)
        assert child == node
        assert action == 'end'

def fill_value(target, node, iter):
        check_close(node, iter)
        target[node.tag] = float(node.attrib["value"])

def fill_light_color(target, node, iter):
        check_close(node, iter)
        attr = node.attrib
        use_temp = attr['usetemp']
        target["color"] = (attr['R'], attr['G'], attr['B'])

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
        loc =   (p("tx"), p("ty"), p("tz"))
        rot =   (p("qw"), p("qx"), p("qy"), p("qz"))
        scale = (p("sx"), p("sy"), p("sz"))

        target["transform"] = (loc, rot, scale)

def fill_actor_mesh(target, node, iter):
        check_close(node, iter)
        attr = node.attrib
        target["mesh"] = attr["name"]

def fill_actor_material(target, node, iter):
        check_close(node, iter)
        attr = node.attrib
        slot = attr["id"]
        material_name = attr["name"]
        # TODO: fill actor with material

actor_maps = {
        "Actor": {
                "Transform":  fill_transform,
                "tag":        ignore,
                "children":   handle_actor_children,
        },
        "ActorMesh": {
                "Transform":  fill_transform,
                "mesh":       fill_actor_mesh,
                "tag":        ignore,
                "children":   handle_actor_children,
                "material":   fill_actor_material,
        },
        "Camera": {
                "Transform":      fill_transform,
                "FocalLength":    fill_value,
                "children":       handle_actor_children,
        },
        "Light": {
                "Transform":  fill_transform,
                "Color":      fill_light_color,
                "children":   handle_actor_children,
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
        filler_map = actor_maps.get(node_type, {})
        for action, child in iter:
                if action == 'end':
                        break
                handler = filler_map.get(child.tag, unhandled)
                handler(actor, child, iter)
        assert child == node
        assert action == 'end'
        
        log.debug(f"{node_type}: {actor_name}")
        return actor




def fill_mesh_material(mesh, node, iter):
        assert next(iter) == ("end", node)
        id = node.attrib["id"]
        name = node.attrib["name"]
        mesh["materials"].append((id, name))


import struct

# don't like this much, maybe we should benchmark specifying sizes directly
def unpack_from_file(length, format, file):
        # length = struct.calcsize(format)
        return struct.unpack(format, file.read(length))

def read_string(buffer):
        string_size = unpack_from_file(4, "<I", buffer)[0]
        string = buffer.read(string_size)
        return string

def load_udsmesh_file(mesh, node, iter):
        check_close(node, iter)
        path = node.attrib["path"]
        full_path = "%s/%s" % (import_ctx["dir_path"], path)
        mesh["path"] = full_path
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
                assert b'\x00\x01\x00\x00\x00' == unknown_a

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
                # log.debug(f"unknown_b {unknown_b}")
                assert unknown_b[0] in (159, 160, 161)
                assert unknown_b[1] == 0

                mesh_start = f.tell()

                # FRawMeshBulkData starts here, which calls FRawMesh operator<<

                # FRawMesh spec starts here, which seems to be an instance of FByteBulkData
                mesh_version = f.read(4)
                assert b'\x01\x00\x00\x00' == mesh_version # mesh version
                mesh_lic_version = f.read(4)
                assert b'\x00\x00\x00\x00' == mesh_lic_version # mesh lic version

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
        filename_start = path.index("/")
        filename = path[filename_start+1:]
        texture = {
                "name": texture_name,
                "filename": filename,
                "path": path,
        }
        for action, child in iter:
                if action == 'end':
                        assert child == node
                        break
                assert child.tag == "Hash"
                ignore(None, child, iter)
        assert child == node
        assert action == 'end'

        # seems to be a better idea to index by filename
        uscene["textures"][filename] = texture


def handle_mastermaterial(uscene, node, iter):
        material_name = node.attrib["name"] # see also: label
        material = {
                "name": material_name,
                "type": node.tag,
        }
# <MasterMaterial name="Default-G7a1920d61156abc05a60135aefe8bc67"  label="Default" Type="1" Quality="0" >
        for action, child in iter:
                if action == 'end':
                        assert child == node
                        break
                assert child.tag == "KeyValueProperty"
                fill_keyvalueproperty(material, child, iter)
        assert child == node
        assert action == 'end'
        uscene["materials"][material_name] = material

def handle_staticmesh(uscene, node, iter):
        mesh_name = node.attrib["name"] # see also: label
        mesh = {
                "name": mesh_name,
                "materials": [],
        }

        filler_map = {
                "Material":  fill_mesh_material,
                "file":      load_udsmesh_file,
                # used to hint UE4 on mesh usage to calculate lightmap size
                "Size":      ignore,
                # Tells UE4 which mesh UV to use when generating the lightmap UVs
                "LightmapUV":  ignore,
                # Tells UE4 that a lightmap UV is already generated at this channel.
                # should be -1 to let UE4 calculate the lightmap
                "LightmapCoordinateIndex": ignore,
                # maybe we can use this hash to skip model importing.
                "Hash":  ignore,
        }
        for action, child in iter:
                if action == 'end':
                        assert child == node
                        break
                handler = filler_map.get(child.tag, unhandled)
                handler(mesh, child, iter)
        assert child == node
        assert action == 'end'

        # all data should be loaded by now, so we just add/update the mesh
        bl_mesh = bpy.data.meshes.new(mesh["name"])
        verts, indices = mesh["vertices"], mesh["indices"]
        verts = verts * 0.01

        # flip in Y axis
        # verts[1::3] *= -1
        # TODO: tunable to apply Y-axis mirror in mesh or in object

        num_vertices = len(verts) // 3
        bl_mesh.vertices.add(num_vertices)
        num_indices = len(indices)
        bl_mesh.loops.add(num_indices)
        num_tris = num_indices//3
        bl_mesh.polygons.add(num_tris)

        bl_mesh.vertices.foreach_set("co", verts)

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

        # not sure when is the best moment to call this
        # TODO: use mesh normals
        bl_mesh.update(calc_edges=True)

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
                "StaticMesh":     handle_staticmesh,
                "Texture":        handle_texture,
                "MasterMaterial": handle_mastermaterial,
        }

        handler = root_tags.get(node.tag, unhandled)
        result = handler(uscene, node, iter)
        return result

def handle_scene(iter, path):

        uscene = {
                "actors":    [],
                "materials": {},
                "meshes":    {},
                "textures":  {},
                "path":      path,
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
        textures = uscene["textures"]
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
        for actor in actors:
                link_actor(uscene, actor)

        print(f"finished scene! {child}")

def color_from_string(color_string):
        r = 0
        g = 0
        b = 0
        a = 0
        cursor = 0
        cursor_end = 0
        
        assert color_string[cursor_end:cursor_end+3] == "(R="
        cursor = cursor_end + 3
        cursor_end = color_string.index(',', cursor)
        r = float(color_string[cursor: cursor_end])
        
        assert color_string[cursor_end:cursor_end+3] == ",G="
        cursor = cursor_end + 3
        cursor_end = color_string.index(',', cursor)
        g = float(color_string[cursor: cursor_end])
        
        assert color_string[cursor_end:cursor_end+3] == ",B="
        cursor = cursor_end + 3
        cursor_end = color_string.index(',', cursor)
        b = float(color_string[cursor: cursor_end])
        
        assert color_string[cursor_end:cursor_end+3] == ",A="
        cursor = cursor_end + 3
        cursor_end = color_string.index(')', cursor)
        a = float(color_string[cursor: cursor_end])

        return (r, g, b, a)
        

def link_texture(uscene, texture):
        texture_path = texture["path"]
        full_path = f"{uscene['path']}/{texture_path}"
        log.debug(full_path)
        image = bpy.data.images.load(full_path)
        texture["image"] = image

def link_material(uscene, material):
        material_name = material["name"]
        bl_mat = bpy.data.materials.new(material_name)
        material["bl_mat"] = bl_mat

        if material["type"] == "MasterMaterial":
                color = (1, 1, 1, 1)
                color_prop = material.get("Color")
                if color_prop:
                        color = color_from_string(color_prop)

                blend_method = 'OPAQUE'
                opacity_prop = material.get("Opacity")
                if opacity_prop:
                        color = color[0:3] + (float(opacity_prop), )
                        blend_method = 'BLEND'

                bl_mat.diffuse_color = color
                bl_mat.blend_method = blend_method

                texture_prop = material.get("Texture")
                if texture_prop:
                        texture = uscene["textures"][texture_prop]
                        image = texture["image"]
                        bl_mat.use_nodes = True
                        node_tree = bl_mat.node_tree
                        nodes = node_tree.nodes
                        principled = nodes["Principled BSDF"]
                        image_node = nodes.new('ShaderNodeTexImage')
                        node_tree.links.new(image_node.outputs['Color'], principled.inputs['Base Color'])
                        image_node.image = image



def link_mesh(uscene, mesh):
        mesh_name = mesh["name"]
        bl_mesh = mesh["bl_mesh"]
        bl_mesh.materials.clear()
        material_ids = mesh["materials"]
        scene_mats = uscene["materials"]
        for mat_id, mat_name in material_ids:
                material = scene_mats[mat_name]["bl_mat"]
                bl_mesh.materials.append(material)


def link_actor(uscene, actor, in_parent=None):
        actor_name = actor["name"]
        data = None
        if actor["type"] == 'ActorMesh':
                mesh_name = actor["mesh"]
                data = uscene["meshes"][mesh_name]["bl_mesh"]
        bl_obj = bpy.data.objects.new(actor_name, data)
        bl_obj.parent = in_parent

        transform = actor["transform"]
        # log.debug(f"postprocessing {actor_name} {transform}")
        mat_loc = Matrix.Translation(np.array(transform[0]) * 0.01)
        mat_rot = Quaternion(transform[1]).to_matrix()
        mat_sca = Matrix.Diagonal(transform[2])
        mat_out = mat_loc.to_4x4() @ mat_rot.to_4x4() @ mat_sca.to_4x4()

        # TODO: be able to mirror Y-axis from the mesh, so we don't end up with
        # a bunch of -1s in scale and a 180 rotation
        mat_out = matrix_datasmith2 @ mat_out
        # mat_out = mat_out @ matrix_datasmith.inverted()

        bl_obj.matrix_world = mat_out
        master_collection = bpy.data.collections[0]
        master_collection.objects.link(bl_obj)

        children = actor["children"]
        for child in children:
                link_actor(uscene, child, bl_obj)


import_ctx = {}

def load(context, kwargs, file_path):
        start_time = time.monotonic()
        log.info(f"loading file: {file_path}")
        log.info(f"args: {kwargs}")
        dir_path = path.dirname(file_path)
        import_ctx["dir_path"] = dir_path
        indent = ""
        with open(file_path, encoding='utf-8') as f:
                iter = ET.iterparse(f, events=('start', 'end'))
                handle_scene(iter, dir_path)

        end_time = time.monotonic()
        total_time = end_time - start_time

        log.info(f"import finished in {total_time} seconds")


def load_wrapper(*, context, filepath, **kwargs):

	handler = None
	use_logging = bool(kwargs["use_logging"])

	if use_logging:
		log_path = filepath + ".log"
		handler = logging.FileHandler(log_path, mode='w')

		formatter = logging.Formatter(
			fmt='%(asctime)s.%(msecs)03d %(levelname)-8s %(message)s',
			datefmt='%Y-%m-%d %H:%M:%S'
		)
		handler.setFormatter(formatter)
		log.addHandler(handler)
		logging_level = logging.INFO
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

	return {'FINISHED'}

