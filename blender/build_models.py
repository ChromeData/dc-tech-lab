"""Build the GB200 NVL72 rack and an open XE9712 compute tray, export GLB for the web app.

Run with the bpy venv:  E:\\wan\\bpyenv\\Scripts\\python.exe build_models.py [--render]

Layout is simplified from the class slides: part names, counts and relative
positions are right; exact dimensions are not (Dell does not publish CAD).
Every quiz part is an empty named PART_<id> with its meshes as children.
"""
import math
import os
import sys

import bpy  # must come first: it registers bmesh and mathutils
import bmesh  # noqa: E402
from mathutils import Vector  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "lab", "web", "assets")
os.makedirs(OUT, exist_ok=True)

OU = 0.048
TW, TD, TH = 0.535, 0.78, 0.043        # tray width, depth, height
RW, RD, RH = 0.62, 1.10, 2.26          # rack


# ------------------------------------------------------------------ helpers
def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    for m in list(bpy.data.materials):
        bpy.data.materials.remove(m)


MATS = {}


def mat(name, color, metallic=0.0, rough=0.5, emit=None, strength=0.0, alpha=1.0):
    if name in MATS:
        return MATS[name]
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*color, 1)
    b.inputs["Metallic"].default_value = metallic
    b.inputs["Roughness"].default_value = rough
    if emit:
        b.inputs["Emission Color"].default_value = (*emit, 1)
        b.inputs["Emission Strength"].default_value = strength
    if alpha < 1:
        b.inputs["Alpha"].default_value = alpha
        m.blend_method = "BLEND"
    MATS[name] = m
    return m


def M():
    """Material palette (plain PBR values so glTF keeps them)."""
    return dict(
        steel=mat("steel", (0.62, 0.64, 0.66), 1.0, 0.38),
        dark=mat("dark_metal", (0.045, 0.048, 0.055), 0.9, 0.42),
        frame=mat("rack_frame", (0.035, 0.037, 0.042), 0.6, 0.42),
        black=mat("black_plastic", (0.012, 0.012, 0.014), 0.0, 0.55),
        pcb=mat("pcb", (0.012, 0.09, 0.04), 0.1, 0.45),
        pcb_blk=mat("pcb_black", (0.015, 0.02, 0.03), 0.1, 0.4),
        copper=mat("copper", (0.95, 0.52, 0.30), 1.0, 0.22),
        gold=mat("gold", (1.0, 0.78, 0.34), 1.0, 0.25),
        alu=mat("aluminum", (0.83, 0.84, 0.86), 1.0, 0.28),
        hose=mat("hose", (0.01, 0.01, 0.012), 0.0, 0.7),
        blue=mat("qd_blue", (0.02, 0.18, 0.75), 0.3, 0.35),
        red=mat("qd_red", (0.75, 0.04, 0.03), 0.3, 0.35),
        chip=mat("chip", (0.03, 0.03, 0.035), 0.4, 0.3),
        white=mat("label", (0.92, 0.92, 0.9), 0.0, 0.6),
        tag=mat("tag_label", (1.0, 0.86, 0.1), 0.0, 0.5, (1.0, 0.8, 0.1), 0.6),
        led_g=mat("led_green", (0.05, 0.9, 0.2), 0.0, 0.3, (0.05, 1.0, 0.2), 4.0),
        led_a=mat("led_amber", (1.0, 0.55, 0.0), 0.0, 0.3, (1.0, 0.5, 0.0), 4.0),
        led_b=mat("led_blue", (0.1, 0.4, 1.0), 0.0, 0.3, (0.1, 0.45, 1.0), 4.0),
        led_off=mat("led_off", (0.05, 0.06, 0.05), 0.0, 0.4),
        port=mat("port", (0.0, 0.0, 0.0), 0.5, 0.3),
        sensor=mat("leak_sensor", (0.9, 0.9, 0.2), 0.0, 0.4),
        zinc=mat("zinc", (0.5, 0.52, 0.5), 1.0, 0.5),
        fanblade=mat("fan_blade", (0.03, 0.03, 0.035), 0.0, 0.45),
        orange=mat("handle_orange", (0.9, 0.32, 0.02), 0.0, 0.5),
    )


def link(obj, coll):
    coll.objects.link(obj)
    return obj


def empty(name, coll, parent=None, loc=(0, 0, 0)):
    e = bpy.data.objects.new(name, None)
    e.empty_display_size = 0.01
    e.location = loc
    e.parent = parent
    return link(e, coll)


def box(name, size, loc, material, coll, parent=None, bevel=0.0):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=Vector(size), verts=bm.verts)
    if bevel > 0:
        bmesh.ops.bevel(bm, geom=bm.edges[:], offset=min(bevel, min(size) * 0.45), segments=2, affect="EDGES")
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = bevel > 0
    me.materials.append(material)
    o = bpy.data.objects.new(name, me)
    o.location = loc
    o.parent = parent
    return link(o, coll)


def cyl(name, r, h, loc, material, coll, parent=None, axis="Z", segs=28):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=segs, radius1=r, radius2=r, depth=h)
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = len(p.vertices) == 4
    me.materials.append(material)
    o = bpy.data.objects.new(name, me)
    o.location = loc
    if axis == "X":
        o.rotation_euler = (0, math.pi / 2, 0)
    elif axis == "Y":
        o.rotation_euler = (math.pi / 2, 0, 0)
    o.parent = parent
    return link(o, coll)


def tube(name, pts, radius, material, coll, parent=None):
    cu = bpy.data.curves.new(name, "CURVE")
    cu.dimensions = "3D"
    cu.bevel_depth = radius
    cu.bevel_resolution = 4
    sp = cu.splines.new("BEZIER")
    sp.bezier_points.add(len(pts) - 1)
    for bp, p in zip(sp.bezier_points, pts):
        bp.co = p
        bp.handle_left_type = bp.handle_right_type = "AUTO"
    cu.materials.append(material)
    o = bpy.data.objects.new(name, cu)
    o.parent = parent
    return link(o, coll)


def dup(obj, coll, parent=None, loc=None, name=None):
    """Linked duplicate of an object tree (shares mesh data)."""
    n = obj.copy()
    n.name = name or obj.name
    n.parent = parent
    if loc is not None:
        n.location = loc
    link(n, coll)
    for ch in obj.children:
        dup(ch, coll, n, None, ch.name.split(".")[0])
    return n


# ------------------------------------------------------------------ tray faceplate (front of the 9712a)
def faceplate(coll, parent, m, prefix=""):
    """Front of a compute tray, origin at the front-bottom-left corner. Returns dict of key objects."""
    g = {}
    y = -0.004
    box(prefix + "face", (TW, 0.006, TH), (TW / 2, y, TH / 2), m["dark"], coll, parent, 0.0015)
    # handles at both ends
    for i, x in enumerate((0.018, TW - 0.018)):
        box(prefix + f"handle{i}", (0.022, 0.03, TH * 0.8), (x, y - 0.016, TH / 2), m["orange"], coll, parent, 0.004)
    # BlueField-3 (two cages, left)
    bf = empty(prefix + "PART_bf3_front", coll, parent)
    for i in range(2):
        box(prefix + f"bf3cage{i}", (0.026, 0.012, 0.016), (0.062 + i * 0.032, y - 0.003, TH * 0.68), m["steel"], coll, bf, 0.001)
        box(prefix + f"bf3hole{i}", (0.021, 0.004, 0.011), (0.062 + i * 0.032, y - 0.0095, TH * 0.68), m["port"], coll, bf)
    # LOM + BMC RJ45
    lom = empty(prefix + "PART_lom", coll, parent)
    box(prefix + "lom_rj45", (0.016, 0.012, 0.013), (0.062, y - 0.003, TH * 0.28), m["steel"], coll, lom, 0.001)
    box(prefix + "lom_hole", (0.012, 0.004, 0.009), (0.062, y - 0.0095, TH * 0.28), m["port"], coll, lom)
    bmc = empty(prefix + "PART_bmc_port", coll, parent)
    box(prefix + "bmc_rj45", (0.016, 0.012, 0.013), (0.086, y - 0.003, TH * 0.28), m["steel"], coll, bmc, 0.001)
    box(prefix + "bmc_hole", (0.012, 0.004, 0.009), (0.086, y - 0.0095, TH * 0.28), m["port"], coll, bmc)
    # luggage tag (service tag) next to the BMC port
    lt = empty(prefix + "PART_luggage_tag", coll, parent)
    box(prefix + "luggage", (0.024, 0.02, 0.0016), (0.112, y - 0.012, TH * 0.28), m["tag"], coll, lt)
    # micro-USB serial + DisplayPort
    ser = empty(prefix + "PART_serial_usb", coll, parent)
    box(prefix + "microusb", (0.008, 0.004, 0.003), (0.134, y - 0.0035, TH * 0.3), m["port"], coll, ser)
    dp = empty(prefix + "PART_displayport", coll, parent)
    box(prefix + "dp", (0.017, 0.004, 0.005), (0.152, y - 0.0035, TH * 0.3), m["port"], coll, dp)
    # 8 E1.S drive slots in the middle
    dr = empty(prefix + "PART_nvme", coll, parent)
    for i in range(8):
        x = 0.185 + i * 0.0215
        box(prefix + f"drive{i}", (0.0175, 0.01, TH * 0.72), (x, y - 0.004, TH / 2), m["steel"] if i < 4 else m["black"], coll, dr, 0.001)
        g[f"dled{i}"] = box(prefix + f"LED_drive{i}", (0.004, 0.002, 0.004), (x, y - 0.0095, TH * 0.86),
                            m["led_g"] if i < 4 else m["led_off"], coll, dr)
    # OSFP header cages (right)
    os_ = empty(prefix + "PART_osfp_front", coll, parent)
    for i in range(4):
        x = 0.385 + i * 0.03
        box(prefix + f"osfp{i}", (0.025, 0.014, 0.016), (x, y - 0.004, TH / 2), m["steel"], coll, os_, 0.001)
        box(prefix + f"osfph{i}", (0.02, 0.004, 0.011), (x, y - 0.0115, TH / 2), m["port"], coll, os_)
    # control panel + power LED
    cp = empty(prefix + "PART_control_panel", coll, parent)
    box(prefix + "cpanel", (0.018, 0.004, 0.026), (TW - 0.046, y - 0.003, TH / 2), m["black"], coll, cp, 0.001)
    g["pled"] = box(prefix + "LED_power", (0.006, 0.002, 0.006), (TW - 0.046, y - 0.0055, TH * 0.66), m["led_g"], coll, cp)
    return g


# ------------------------------------------------------------------ open compute tray (tray.glb)
def fan(name, x, y, coll, parent, m):
    f = empty(name, coll, parent, (x, y, 0.004))
    box(name + "_frame", (0.04, 0.056, 0.038), (0, 0, 0.019), m["black"], coll, f, 0.002)
    box(name + "_tab", (0.014, 0.02, 0.003), (0.008, -0.012, 0.0395), m["orange"], coll, f, 0.001)     # release tab
    box(name + "_lbl", (0.016, 0.012, 0.0004), (-0.008, 0.014, 0.0383), m["white"], coll, f)
    for dy in (-0.0285, 0.0285):
        cyl(name + f"_ring{dy}", 0.0175, 0.002, (0, dy, 0.019), m["chip"], coll, f, "Y")
    cyl(name + "_hub", 0.008, 0.058, (0, 0, 0.019), m["steel"], coll, f, "Y", 16)
    for k in range(7):
        b = box(name + f"_blade{k}", (0.014, 0.05, 0.0012), (0, 0, 0.019), m["fanblade"], coll, f)
        a = k * 2 * math.pi / 7
        b.location = (math.cos(a) * 0.011, 0, 0.019 + math.sin(a) * 0.011)
        b.rotation_euler = (0, -a + 0.5, 0)
    return f


def coldplate(name, size, loc, coll, parent, m, fins=True):
    p = empty(name, coll, parent, loc)
    name = name.replace("PART_", "")
    box(name + "_base", (size[0], size[1], 0.006), (0, 0, 0.003), m["copper"], coll, p, 0.0015)
    box(name + "_top", (size[0] * 0.82, size[1] * 0.82, 0.007), (0, 0, 0.0095), m["copper"], coll, p, 0.002)
    for sx in (-1, 1):
        for sy in (-1, 1):
            cyl(name + f"_scr{sx}{sy}", 0.003, 0.004, (sx * size[0] * 0.43, sy * size[1] * 0.43, 0.008), m["zinc"], coll, p, "Z", 12)
    for i, mm in enumerate((m["blue"], m["red"])):
        cyl(name + f"_barb{i}", 0.0045, 0.012, ((i - 0.5) * size[0] * 0.36, size[1] * 0.2, 0.018), mm, coll, p, "Z", 14)
    return p


def bianca(idx, x0, coll, root, m):
    """One Bianca board: 1 Grace CPU + 2 GPUs under cold plates, memory, leak sensors, hoses to the rear manifold."""
    w, d = 0.245, 0.33
    y0 = 0.425
    b = empty(f"PART_bianca{idx}", coll, root, (x0, y0, 0.006))
    box(f"bianca{idx}_pcb", (w, d, 0.002), (w / 2, d / 2, 0.001), m["pcb_blk"], coll, b)
    gp = empty("PART_gpus" if idx == 0 else f"PART_gpus{idx}", coll, b)
    for g in range(2):
        gx = w * (0.27 + 0.46 * g)
        box(f"gpu{idx}{g}_pkg", (0.078, 0.078, 0.003), (gx, d * 0.66, 0.0035), m["chip"], coll, gp)
        coldplate(f"PART_coldplate{idx}{g}", (0.088, 0.088), (gx, d * 0.66, 0.005), coll, gp, m)
    cp = empty("PART_cpu_mem" if idx == 0 else f"PART_cpu_mem{idx}", coll, b)
    box(f"cpu{idx}_pkg", (0.07, 0.06, 0.003), (w * 0.5, d * 0.26, 0.0035), m["chip"], coll, cp)
    coldplate(f"cpuplate{idx}", (0.078, 0.066), (w * 0.5, d * 0.26, 0.005), coll, cp, m)
    for k in range(8):
        sx = -1 if k < 4 else 1
        box(f"lpddr{idx}{k}", (0.014, 0.012, 0.002), (w * 0.5 + sx * 0.058, d * 0.26 - 0.03 + (k % 4) * 0.02, 0.003), m["chip"], coll, cp)
    # CX7/8 mezz at the back edge
    mz = empty("PART_cx_mezz" if idx == 0 else f"PART_cx_mezz{idx}", coll, b)
    box(f"mezz{idx}_pcb", (w * 0.7, 0.045, 0.002), (w * 0.5, d * 0.07, 0.006), m["pcb"], coll, mz)
    for k in range(2):
        box(f"mezz{idx}_conn{k}", (0.03, 0.02, 0.01), (w * (0.3 + 0.4 * k), d * 0.07, 0.012), m["steel"], coll, mz, 0.001)
        box(f"mezz{idx}_tbar{k}", (0.05, 0.006, 0.004), (w * (0.3 + 0.4 * k), d * 0.07 + 0.016, 0.018), m["alu"], coll, mz, 0.001)
    # manifold at the rear + quick disconnects
    mf = empty("PART_manifold" if idx == 0 else f"PART_manifold{idx}", coll, b)
    for i, mm in enumerate((m["blue"], m["red"])):
        cyl(f"manifold{idx}{i}", 0.008, w * 0.8, (w * 0.5, d - 0.02 - i * 0.022, 0.022 + i * 0.002), m["alu"], coll, mf, "X", 18)
        cyl(f"qd{idx}{i}", 0.011, 0.03, (w * (0.12 + 0.76 * i), d + 0.008, 0.022), mm, coll, mf, "Y", 18)
    # hoses: each cold plate to the manifold
    for g in range(2):
        gx = w * (0.27 + 0.46 * g)
        for i, off in enumerate((-0.016, 0.016)):
            tube(f"hose{idx}{g}{i}", [(gx + off, d * 0.66 + 0.018, 0.026), (gx + off * 1.6, d * 0.82, 0.034),
                                      (gx + off * 1.2, d - 0.02 - i * 0.022, 0.03)], 0.0042, m["hose"], coll, mf)
    tube(f"hosecpu{idx}", [(w * 0.5 - 0.014, d * 0.26 + 0.014, 0.026), (w * 0.5 - 0.05, d * 0.45, 0.036),
                           (w * 0.27 - 0.016, d * 0.66 - 0.02, 0.028)], 0.0042, m["hose"], coll, mf)
    # leak sensors: cold plate (Mx_0) and manifold (Mx_1)
    for k, (sx, sy, sz) in enumerate(((w * 0.27 + 0.05, d * 0.66 - 0.05, 0.008), (w * 0.5, d - 0.052, 0.008))):
        s = empty(f"PART_leak_M{idx}_{k}", coll, b, (sx, sy, sz))
        box(f"leak{idx}{k}_pad", (0.02, 0.012, 0.002), (0, 0, 0), m["sensor"], coll, s)
        tube(f"leak{idx}{k}_wire", [(0.01, 0, 0.001), (0.03, 0.01, 0.006), (0.05, 0.0, 0.004)], 0.0012, m["white"], coll, s)
    return b


def build_tray(coll, m, name="TRAY", with_lid=True):
    root = empty(name, coll)
    # chassis
    ch = empty("PART_chassis", coll, root)
    box("floor", (TW, TD, 0.002), (TW / 2, TD / 2, 0.001), m["steel"], coll, ch)
    for x in (0.001, TW - 0.001):
        box(f"wall{x}", (0.002, TD, TH), (x, TD / 2, TH / 2), m["steel"], coll, ch)
    box("rearwall", (TW, 0.002, TH * 0.55), (TW / 2, TD - 0.001, TH * 0.275), m["steel"], coll, ch)
    for x in (-0.006, TW + 0.006):
        r = empty("PART_rails" if x < 0 else "PART_rails_r", coll, root)
        box(f"rail{x}", (0.01, TD * 0.92, 0.018), (x, TD / 2, TH / 2), m["zinc"], coll, r, 0.002)
    hd = empty("PART_handles", coll, root)
    for i, x in enumerate((0.018, TW - 0.018)):
        box(f"handle_grip{i}", (0.022, 0.03, TH * 0.8), (x, -0.02, TH / 2), m["orange"], coll, hd, 0.004)
    fp = faceplate(coll, root, m)
    for o in [c for c in root.children if c.name.startswith("handle")]:
        bpy.data.objects.remove(o)

    # ---- front zone
    fio = empty("PART_front_io", coll, root)
    box("fio_pcb", (0.15, 0.05, 0.002), (0.09, 0.035, 0.007), m["pcb"], coll, fio)
    box("fio_conn", (0.03, 0.012, 0.008), (0.14, 0.05, 0.012), m["black"], coll, fio)
    cm = empty("PART_cmos", coll, root)
    cyl("cmos_cell", 0.01, 0.0032, (0.035, 0.045, 0.0105), m["alu"], coll, cm, "Z", 24)
    bf = empty("PART_bf3", coll, root)
    box("bf3_pcb", (0.1, 0.12, 0.002), (0.075, 0.135, 0.012), m["pcb_blk"], coll, bf)
    box("bf3_sink", (0.07, 0.07, 0.014), (0.075, 0.145, 0.02), m["alu"], coll, bf, 0.002)
    for k in range(9):
        box(f"bf3_fin{k}", (0.068, 0.002, 0.008), (0.075, 0.115 + k * 0.0075, 0.031), m["alu"], coll, bf)
    for i in range(2):
        box(f"bf3_cage{i}", (0.026, 0.05, 0.016), (0.062 + i * 0.032, 0.03, 0.03), m["steel"], coll, bf, 0.001)
    bp = empty("PART_backplane", coll, root)
    box("bp_pcb", (0.18, 0.003, 0.034), (0.26, 0.105, 0.021), m["pcb"], coll, bp)
    nv = empty("PART_nvme_inside", coll, root)
    for i in range(8):
        box(f"e1s{i}", (0.0175, 0.095, 0.03), (0.185 + i * 0.0215, 0.052, 0.02), m["steel"] if i < 4 else m["black"], coll, nv, 0.001)
    osf = empty("PART_osfp_header", coll, root)
    for i in range(4):
        x = 0.385 + i * 0.03
        box(f"osfp_cage{i}", (0.025, 0.07, 0.016), (x, 0.036, 0.022), m["steel"], coll, osf, 0.001)
        box(f"osfp_sink{i}", (0.022, 0.045, 0.006), (x, 0.04, 0.033), m["alu"], coll, osf, 0.001)
        tube(f"osfp_cable{i}", [(x, 0.072, 0.022), (x + 0.012, 0.2, 0.036), (TW * 0.5 + (i - 1.5) * 0.09, 0.4, 0.036),
                                (0.02 + (0.245 + 0.025) * (i // 2) + 0.245 * (0.3 + 0.4 * (i % 2)), 0.445, 0.02)],
             0.0035, m["black"], coll, osf)
    m2 = empty("PART_m2", coll, root)
    box("m2_riser", (0.03, 0.09, 0.03), (0.50, 0.14, 0.021), m["pcb"], coll, m2)
    box("m2_stick", (0.022, 0.08, 0.003), (0.482, 0.14, 0.03), m["pcb_blk"], coll, m2)
    hm = empty("PART_hmc", coll, root)
    box("hmc_pcb", (0.085, 0.07, 0.002), (0.47, 0.235 - 0.16, 0.036), m["pcb"], coll, hm)
    box("hmc_chip", (0.022, 0.022, 0.003), (0.47, 0.075, 0.0385), m["chip"], coll, hm)
    sl = empty("PART_slimline", coll, root)
    for i in range(2):
        tube(f"slim{i}", [(0.45 + i * 0.03, 0.11, 0.037), (0.44 + i * 0.03, 0.25, 0.04), (0.40 + i * 0.05, 0.42, 0.03)],
             0.0028, m["blue"], coll, sl)
    tp = empty("PART_tpm", coll, root)
    box("tpm_mod", (0.014, 0.02, 0.006), (0.385, 0.165, 0.012), m["pcb"], coll, tp)
    box("tpm_chip", (0.008, 0.008, 0.002), (0.385, 0.165, 0.016), m["chip"], coll, tp)

    # ---- fan row
    fn = empty("PART_fans", coll, root)
    for i in range(10):
        fan(f"fan{i}", 0.035 + i * 0.0517, 0.245, coll, fn, m)

    # ---- mid zone: interposer + BMC, PDB, IPEX, internal busbar
    ib = empty("PART_interposer_bmc", coll, root)
    box("interposer_pcb", (0.14, 0.11, 0.002), (0.085, 0.345, 0.008), m["pcb"], coll, ib)
    box("bmc_module", (0.05, 0.07, 0.012), (0.07, 0.345, 0.016), m["pcb_blk"], coll, ib, 0.001)
    box("bmc_chip", (0.02, 0.02, 0.002), (0.07, 0.345, 0.023), m["chip"], coll, ib)
    pd = empty("PART_pdb", coll, root)
    box("pdb_pcb", (0.2, 0.11, 0.003), (0.27, 0.345, 0.008), m["pcb_blk"], coll, pd)
    box("pdb_sink", (0.15, 0.06, 0.014), (0.27, 0.335, 0.017), m["alu"], coll, pd, 0.002)
    for k in range(18):
        box(f"pdb_fin{k}", (0.002, 0.058, 0.01), (0.2 + k * 0.0082, 0.335, 0.029), m["alu"], coll, pd)
    for k in range(5):
        cyl(f"pdb_cap{k}", 0.006, 0.016, (0.19 + k * 0.04, 0.39, 0.017), m["dark"], coll, pd, "Z", 14)
    ip = empty("PART_ipex", coll, root)
    box("ipex_pcb", (0.1, 0.09, 0.002), (0.45, 0.345, 0.008), m["pcb"], coll, ip)
    box("ipex_cage", (0.07, 0.06, 0.012), (0.45, 0.345, 0.015), m["steel"], coll, ip, 0.001)
    bb = empty("PART_busbar", coll, root)
    for i, x in enumerate((TW / 2 - 0.012, TW / 2 + 0.012)):
        box(f"busbar{i}", (0.014, 0.39, 0.004), (x, 0.59, 0.03), m["copper"], coll, bb, 0.001)
    for sec, y in (("back", 0.76), ("middle", 0.59), ("front", 0.42)):
        for i, x in enumerate((TW / 2 - 0.012, TW / 2 + 0.012)):
            cyl(f"busbar_screw_{sec}{i}", 0.004, 0.005, (x, y, 0.034), m["zinc"], coll, bb, "Z", 6)
    box("busbar_clip", (0.05, 0.03, 0.03), (TW / 2, TD + 0.012, 0.022), m["copper"], coll, bb, 0.003)

    # ---- rear zone: two Bianca boards
    bianca(0, 0.02, coll, root, m)
    bianca(1, 0.02 + 0.245 + 0.025, coll, root, m)

    if with_lid:
        lid = empty("PART_lid", coll, root)
        box("lid_panel", (TW, TD, 0.0015), (TW / 2, TD / 2, TH + 0.001), m["steel"], coll, lid)
    return root, fp


# ------------------------------------------------------------------ rack (rack.glb)
def closed_tray(coll, m, name):
    """Light-weight closed tray for the rack view: body + faceplate + LEDs."""
    root = empty(name, coll)
    box(name + "_body", (TW, TD, TH), (TW / 2, TD / 2, TH / 2), m["steel"], coll, root)
    faceplate(coll, root, m)
    return root


def switch_tray(coll, m, name):
    root = empty(name, coll)
    box(name + "_body", (TW, TD * 0.9, TH), (TW / 2, TD * 0.45, TH / 2), m["dark"], coll, root)
    box(name + "_face", (TW, 0.006, TH), (TW / 2, -0.004, TH / 2), m["black"], coll, root, 0.0015)
    for i in range(12):
        box(name + f"_vent{i}", (0.03, 0.002, TH * 0.6), (0.06 + i * 0.036, -0.008, TH / 2), m["dark"], coll, root)
    box("LED_status", (0.006, 0.002, 0.006), (TW - 0.03, -0.0085, TH * 0.66), m["led_g"], coll, root)
    lt = empty("PART_luggage_tag", coll, root)
    box(name + "_luggage", (0.024, 0.02, 0.0016), (0.03, -0.016, TH * 0.3), m["tag"], coll, lt)
    for i, x in enumerate((0.012, TW - 0.012)):
        box(name + f"_h{i}", (0.014, 0.022, TH * 0.7), (x, -0.012, TH / 2), m["alu"], coll, root, 0.003)
    return root


def power_tray(coll, m, name, kind="pt"):
    root = empty(name, coll)
    box(name + "_body", (TW, TD * 0.8, TH), (TW / 2, TD * 0.4, TH / 2), m["dark"], coll, root)
    n = 6 if kind == "pt" else (3 if kind == "inv" else 1)
    w = (TW - 0.03) / n
    for i in range(n):
        x = 0.015 + w * (i + 0.5)
        box(name + f"_mod{i}", (w - 0.006, 0.01, TH * 0.82), (x, -0.004, TH / 2), m["steel"] if kind != "cap" else m["alu"], coll, root, 0.0015)
        box(name + f"_grip{i}", (0.02, 0.012, 0.008), (x, -0.014, TH * 0.3), m["orange"] if kind == "pt" else m["black"], coll, root, 0.002)
        box(name + f"_led{i}", (0.004, 0.002, 0.004), (x + w * 0.3, -0.0095, TH * 0.75), m["led_g"], coll, root)
    return root


def build_rack(coll, m):
    rack = empty("RACK", coll)
    fr = empty("PART_rack_frame", coll, rack)
    x0 = (RW - TW) / 2
    for x in (0.02, RW - 0.02):
        for y in (0.02, RD - 0.02):
            box(f"post{x}{y}", (0.04, 0.04, RH), (x, y, RH / 2), m["frame"], coll, fr, 0.003)
    box("top", (RW, RD, 0.03), (RW / 2, RD / 2, RH - 0.015), m["frame"], coll, fr, 0.003)
    box("base", (RW, RD, 0.06), (RW / 2, RD / 2, 0.03), m["frame"], coll, fr, 0.003)
    for x in (0.003, RW - 0.003):
        box(f"side{x}", (0.004, RD - 0.1, RH - 0.1), (x, RD / 2, RH / 2), m["frame"], coll, fr)

    slots = [("CAP1", "cap"), ("INV1", "inv")] + [(f"PT{i}", "pt") for i in range(1, 5)]
    slots += [(f"CT{i:02d}", "ct") for i in range(1, 9)]
    slots += [(f"SW{i}", "sw") for i in range(1, 10)]
    slots += [(f"CT{i:02d}", "ct") for i in range(9, 19)]
    slots += [(f"PT{i}", "pt") for i in range(5, 9)] + [("INV2", "inv")]
    src = {"ct": closed_tray(coll, m, "SRC_ct"), "sw": switch_tray(coll, m, "SRC_sw"),
           "pt": power_tray(coll, m, "SRC_pt", "pt"), "inv": power_tray(coll, m, "SRC_inv", "inv"),
           "cap": power_tray(coll, m, "SRC_cap", "cap")}
    z = 0.085
    for name, kind in slots:
        o = dup(src[kind], coll, rack, (x0, 0.06, z), name)
        o["kind"] = kind
        z += OU
    for s in src.values():
        for ch in list(s.children_recursive):
            bpy.data.objects.remove(ch)
        bpy.data.objects.remove(s)

    # rear: bus bar, cable cartridges, liquid manifolds
    bb = empty("PART_rack_busbar", coll, rack)
    box("rack_busbar", (0.05, 0.012, RH - 0.25), (RW / 2, RD - 0.045, RH / 2), m["copper"], coll, bb, 0.002)
    for i in range(4):
        cc = empty(f"CC{i + 1}", coll, rack)
        cx = RW / 2 + (i - 1.5) * 0.085 + (0.03 if i > 1 else -0.03)
        box(f"cc{i}_body", (0.07, 0.05, OU * 27 * 0.95), (cx, RD - 0.11, 0.085 + OU * (6 + 13.5)), m["dark"], coll, cc, 0.004)
        for k in range(27):
            box(f"cc{i}_conn{k}", (0.05, 0.012, OU * 0.5), (cx, RD - 0.14, 0.085 + OU * (6.5 + k)), m["gold"], coll, cc)
    for i, (x, mm) in enumerate(((0.065, m["blue"]), (RW - 0.065, m["red"]))):
        mf = empty("PART_rack_manifold" if i == 0 else "PART_rack_manifold_r", coll, rack)
        cyl(f"rack_manifold{i}", 0.02, RH - 0.3, (x, RD - 0.07, RH / 2), m["alu"], coll, mf, "Z", 24)
        for k in range(18):
            zz = 0.085 + OU * (6.5 + (k if k < 8 else k + 9))
            cyl(f"rack_qd{i}{k}", 0.009, 0.03, (x, RD - 0.1, zz), mm, coll, mf, "Y", 12)

    # service-tag stickers (quiz targets)
    for name, loc in (("TAG_rack_back_right_corner", (RW - 0.03, RD + 0.001, RH - 0.12)),
                      ("TAG_rack_top_center", (RW / 2, -0.001, RH - 0.016)),
                      ("TAG_rack_front_right_corner", (RW - 0.02, -0.001, RH - 0.12)),
                      ("TAG_cartridge_left_middle", (RW / 2 - 0.195, RD - 0.11, 0.085 + OU * 19.5)),
                      ("TAG_cartridge_left_top", (RW / 2 - 0.195, RD - 0.11, 0.085 + OU * 32)),
                      ("TAG_cartridge_left_bottom", (RW / 2 - 0.195, RD - 0.11, 0.085 + OU * 7)),
                      ("TAG_power_back_right_busbar", (RW / 2 + 0.06, RD - 0.03, 0.085 + OU * 3))):
        t = empty(name, coll, rack)
        box(name + "_sticker", (0.05, 0.003, 0.022) if "cartridge" not in name else (0.003, 0.04, 0.02), loc, m["tag"], coll, t)
    return rack


def export(path, coll_name):
    for o in bpy.data.objects:
        o.select_set(False)
    for o in bpy.data.collections[coll_name].all_objects:
        o.select_set(True)
    bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", use_selection=True, export_apply=True,
                              export_yup=True, export_extras=True)
    print("exported", path, f"{os.path.getsize(path) / 1e6:.2f} MB")


def main():
    reset()
    m = M()
    sc = bpy.context.scene
    c_tray = bpy.data.collections.new("tray")
    c_rack = bpy.data.collections.new("rack")
    sc.collection.children.link(c_tray)
    sc.collection.children.link(c_rack)
    build_tray(c_tray, m)
    build_rack(c_rack, m)
    export(os.path.join(OUT, "tray.glb"), "tray")
    export(os.path.join(OUT, "rack.glb"), "rack")
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(HERE, "models.blend"))
    print("PARTS tray:", sorted(o.name for o in c_tray.all_objects if o.name.startswith("PART_")))


if __name__ == "__main__":
    main()
