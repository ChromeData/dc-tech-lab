"""Cycles renders of the lab models.

Usage:  python render.py <shot> [samples] [frames]
Shots:  tray   open compute tray on an ESD mat
        hall   R12 in the cold aisle (hero still)
        pano   360 panorama of the aisle without R12 (background + lighting for the web app)
        fly    camera move down the aisle to R12 (PNG frames in renders/fly)
"""
import math
import os
import sys

import bpy
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "renders")
os.makedirs(OUT, exist_ok=True)
shot = sys.argv[1] if len(sys.argv) > 1 else "tray"
samples = int(sys.argv[2]) if len(sys.argv) > 2 else 96

bpy.ops.wm.open_mainfile(filepath=os.path.join(HERE, "models.blend"))
sc = bpy.context.scene
sc.render.engine = "CYCLES"
prefs = bpy.context.preferences.addons["cycles"].preferences
for kind in ("OPTIX", "CUDA"):
    try:
        prefs.compute_device_type = kind
        prefs.get_devices()
        if any(d.type == kind for d in prefs.devices):
            break
    except Exception:
        pass
for d in prefs.devices:
    d.use = d.type in ("OPTIX", "CUDA")
sc.cycles.device = "GPU"
sc.cycles.samples = samples
sc.cycles.use_denoising = True
try:
    sc.cycles.denoiser = "OPTIX"
except Exception:
    pass
sc.render.resolution_x, sc.render.resolution_y = 1920, 1080
sc.view_settings.view_transform = "AgX"
sc.view_settings.look = "AgX - Medium High Contrast"


def cam(loc, target, lens=50):
    c = bpy.data.cameras.new("cam")
    c.lens = lens
    o = bpy.data.objects.new("cam", c)
    sc.collection.objects.link(o)
    o.location = loc
    d = Vector(target) - Vector(loc)
    o.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    sc.camera = o
    return o


def area(loc, target, size, power, color=(1, 1, 1)):
    l = bpy.data.lights.new("area", "AREA")
    l.size = size
    l.energy = power
    l.color = color
    o = bpy.data.objects.new("area", l)
    sc.collection.objects.link(o)
    o.location = loc
    d = Vector(target) - Vector(loc)
    o.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    return o


def world(strength=0.25, color=(0.02, 0.025, 0.035)):
    w = bpy.data.worlds.new("w")
    w.use_nodes = True
    sc.world = w
    bg = w.node_tree.nodes["Background"]
    bg.inputs[0].default_value = (*color, 1)
    bg.inputs[1].default_value = strength


def flat_mat(name, color, rough=0.5, metallic=0.0, emit=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*color, 1)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metallic
    if emit:
        b.inputs["Emission Color"].default_value = (*color, 1)
        b.inputs["Emission Strength"].default_value = emit
    return m


def plane(size, z, color, rough=0.35, name="floor"):
    bpy.ops.mesh.primitive_plane_add(size=size, location=(0, 0, z))
    o = bpy.context.object
    o.name = name
    o.data.materials.append(flat_mat(name, color, rough))
    return o


def cube(name, size, loc, material):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    o = bpy.context.object
    o.name = name
    o.scale = size
    o.data.materials.append(material)
    return o


def root_of(o):
    while o.parent:
        o = o.parent
    return o


def drop(rootname):
    """Remove every object under the given root (RACK or TRAY)."""
    doomed = [o for o in bpy.data.objects if o and root_of(o).name == rootname]
    for o in doomed:
        bpy.data.objects.remove(o)


def enrich():
    """Cycles-only material detail (the GLB keeps the plain values)."""
    for m in bpy.data.materials:
        if not m.use_nodes:
            continue
        nt = m.node_tree
        b = nt.nodes.get("Principled BSDF")
        if b is None:
            continue
        if m.name in ("steel", "aluminum", "zinc", "dark_metal", "rack_frame", "copper"):
            tex = nt.nodes.new("ShaderNodeTexNoise")
            tex.inputs["Scale"].default_value = 220
            tex.inputs["Detail"].default_value = 8
            bump = nt.nodes.new("ShaderNodeBump")
            bump.inputs["Strength"].default_value = 0.035
            nt.links.new(tex.outputs["Fac"], bump.inputs["Height"])
            nt.links.new(bump.outputs["Normal"], b.inputs["Normal"])
        if m.name == "pcb":
            b.inputs["Base Color"].default_value = (0.004, 0.045, 0.02, 1)
        if m.name == "steel":
            b.inputs["Roughness"].default_value = 0.32


def build_hall(with_r12=True):
    """Two rows of racks facing a cold aisle. R12 is the original rack at the origin."""
    drop("TRAY")
    enrich()
    rack_coll = bpy.data.collections["rack"]
    rw = 0.62
    hall = bpy.data.collections.new("hall")
    sc.collection.children.link(hall)

    def inst(loc, rotz=0.0):
        e = bpy.data.objects.new("rackinst", None)
        e.instance_type = "COLLECTION"
        e.instance_collection = rack_coll
        e.location = loc
        e.rotation_euler = (0, 0, rotz)
        hall.objects.link(e)

    for k in range(-9, 10):
        if k != 0:
            inst((k * rw, 0, 0))
        inst((k * rw + rw, -1.25, 0), math.pi)
    if not with_r12:
        def excl(lc):
            for c in lc.children:
                if c.collection == rack_coll:
                    c.exclude = True
                excl(c)
        excl(bpy.context.view_layer.layer_collection)

    fl = plane(60, 0, (0.2, 0.2, 0.21), 0.22, "floor")
    nt = fl.data.materials[0].node_tree
    b = nt.nodes["Principled BSDF"]
    co = nt.nodes.new("ShaderNodeTexCoord")
    br = nt.nodes.new("ShaderNodeTexBrick")
    br.offset = 0.0
    br.inputs["Scale"].default_value = 1.0
    br.inputs["Mortar Size"].default_value = 0.004
    br.inputs["Brick Width"].default_value = 0.6
    br.inputs["Row Height"].default_value = 0.6
    br.inputs["Color1"].default_value = (0.17, 0.175, 0.185, 1)
    br.inputs["Color2"].default_value = (0.2, 0.205, 0.215, 1)
    br.inputs["Mortar"].default_value = (0.02, 0.02, 0.02, 1)
    nt.links.new(co.outputs["Object"], br.inputs["Vector"])
    nt.links.new(br.outputs["Color"], b.inputs["Base Color"])
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.4
    bump.invert = True
    nt.links.new(br.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], b.inputs["Normal"])

    ceil = plane(60, 3.1, (0.015, 0.016, 0.018), 0.8, "ceiling")
    ceil.rotation_euler = (math.pi, 0, 0)
    lm = flat_mat("fixture", (1.0, 0.97, 0.92), 0.5, 0.0, 28)
    for k in range(-5, 6):
        cube(f"light{k}", (1.25, 0.14, 0.03), (k * 1.9 + 0.31, -0.62, 2.95), lm)
    ym = flat_mat("raceway", (0.95, 0.72, 0.02), 0.45)
    cube("raceway", (14, 0.12, 0.1), (0.3, 0.35, 2.52), ym)
    cube("raceway2", (14, 0.12, 0.1), (0.3, -1.6, 2.52), ym)
    tm = flat_mat("tray_steel", (0.35, 0.36, 0.38), 0.4, 1.0)
    cube("cabletray", (14, 0.4, 0.02), (0.3, 0.75, 2.72), tm)
    cube("cabletray2", (14, 0.4, 0.02), (0.3, -2.0, 2.72), tm)
    bm_ = flat_mat("beam", (0.03, 0.032, 0.036), 0.5, 0.6)
    for k in range(-6, 7):
        cube(f"beam{k}", (0.04, 1.25, 0.04), (k * 1.24, -0.62, 2.36), bm_)
    wm = flat_mat("wall", (0.06, 0.065, 0.07), 0.7)
    cube("wall_e", (0.1, 12, 3.2), (6.4, -0.6, 1.6), wm)
    cube("wall_w", (0.1, 12, 3.2), (-6.0, -0.6, 1.6), wm)
    world(0.04, (0.02, 0.03, 0.05))


if shot == "tray":
    drop("RACK")
    lid = bpy.data.objects.get("PART_lid")
    for o in list(lid.children_recursive) + [lid]:
        bpy.data.objects.remove(o)
    enrich()
    world(0.25, (0.04, 0.045, 0.055))
    plane(6, -0.001, (0.012, 0.03, 0.05), 0.45, "esd_mat")
    c = cam((0.27 - 0.5, -0.5, 0.6), (0.27, 0.36, 0.0), 42)
    c.data.dof.use_dof = True
    c.data.dof.focus_distance = 1.05
    c.data.dof.aperture_fstop = 5.6
    area((0.3, 0.3, 1.3), (0.27, 0.4, 0), 1.2, 60)
    area((-0.9, -0.3, 0.5), (0.27, 0.4, 0), 0.8, 22, (0.7, 0.82, 1.0))
    area((1.3, 1.0, 0.45), (0.27, 0.4, 0), 0.8, 26, (1.0, 0.82, 0.62))
    sc.render.filepath = os.path.join(OUT, "tray_open.png")
    bpy.ops.render.render(write_still=True)
elif shot == "hall":
    build_hall(True)
    cam((1.45, -0.98, 1.32), (0.31, 0.0, 1.15), 22)
    sc.render.filepath = os.path.join(OUT, "hall_r12.png")
    bpy.ops.render.render(write_still=True)
elif shot == "pano":
    build_hall(False)
    c = cam((0.31, -0.62, 1.3), (5.0, -0.62, 1.3), 18)
    c.data.type = "PANO"
    c.data.panorama_type = "EQUIRECTANGULAR"
    sc.render.resolution_x, sc.render.resolution_y = 4096, 2048
    sc.render.image_settings.file_format = "HDR"
    sc.render.filepath = os.path.join(OUT, "hall_pano.hdr")
    bpy.ops.render.render(write_still=True)
    sc.render.image_settings.file_format = "JPEG"
    sc.render.image_settings.quality = 90
    bpy.data.images["Render Result"].save_render(os.path.join(OUT, "hall_pano.jpg"))
    img = bpy.data.images.load(sc.render.filepath)
    img.scale(1024, 512)
    img.file_format = "HDR"
    img.filepath_raw = os.path.join(OUT, "hall_env.hdr")
    img.save()
elif shot == "fly":
    build_hall(True)
    c = cam((5.6, -0.62, 1.62), (0.31, -0.3, 1.2), 22)
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 150
    sc.frame_start, sc.frame_end = 1, n
    tgt = bpy.data.objects.new("tgt", None)
    sc.collection.objects.link(tgt)
    con = c.constraints.new("TRACK_TO")
    con.target = tgt
    con.track_axis = "TRACK_NEGATIVE_Z"
    con.up_axis = "UP_Y"
    for f, loc, t in ((1, (5.6, -0.62, 1.62), (0.31, -0.3, 1.2)), (n, (1.45, -0.98, 1.32), (0.31, 0.0, 1.15))):
        c.location = loc
        c.keyframe_insert("location", frame=f)
        tgt.location = t
        tgt.keyframe_insert("location", frame=f)
    sc.render.resolution_x, sc.render.resolution_y = 1280, 720
    sc.render.image_settings.file_format = "PNG"
    os.makedirs(os.path.join(OUT, "fly"), exist_ok=True)
    sc.render.filepath = os.path.join(OUT, "fly", "f_")
    bpy.ops.render.render(animation=True)
print("rendered", shot, sc.render.filepath)
