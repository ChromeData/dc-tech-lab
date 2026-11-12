"""Data hall v3: a rock-cavern data center (white cabinets, granite, suspended glass room).

The look follows the user's six reference photos. The gear does not change: R12 is still the
GB200 NVL72 rack from the class slides, shown with its white doors open.

    python hall3.py test                 quick stills
    python hall3.py panos [samples]      360 beauty + ID layers (front, rear, hall)
    python hall3.py tray [samples]       tray orbit frames + ID layers
    python hall3.py fly [samples] [n]    fly-through frames
    python hall3.py all [samples] [n]
"""
import json
import math
import os
import random
import sys

import bpy  # noqa: E402
import bmesh  # noqa: E402
from mathutils import Vector, noise  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_models as bm  # noqa: E402
import hall2 as h2  # noqa: E402

IMG, REN = h2.IMG, h2.REN
RW, RD, RH, OU, TW, TD, TH = bm.RW, bm.RD, bm.RH, bm.OU, bm.TW, bm.TD, bm.TH
ROW = range(-9, 12)
X_LO, X_HI = -11.0, 17.0          # cavern length
Y_WALL, Y_FAR = 3.0, -17.0        # rock wall behind the row, far wall
YC, WD, CEIL = (Y_WALL + Y_FAR) / 2, (Y_WALL - Y_FAR), 7.2
POD = (5.0, -8.2, 3.05, 3.0)      # x, y, floor height, radius
BENCH = (-2.4, -3.6)

sc = None


# ------------------------------------------------------------------ materials
def rock_mat():
    m = bpy.data.materials.new("rock")
    m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes["Principled BSDF"]
    co = nt.nodes.new("ShaderNodeTexCoord")
    big = nt.nodes.new("ShaderNodeTexNoise")
    big.inputs["Scale"].default_value = 0.22
    big.inputs["Detail"].default_value = 5
    mid = nt.nodes.new("ShaderNodeTexNoise")
    mid.inputs["Scale"].default_value = 1.7
    mid.inputs["Detail"].default_value = 12
    mid.inputs["Roughness"].default_value = 0.65
    fine = nt.nodes.new("ShaderNodeTexNoise")
    fine.inputs["Scale"].default_value = 22
    fine.inputs["Detail"].default_value = 8
    for n in (big, mid, fine):
        nt.links.new(co.outputs["Object"], n.inputs["Vector"])
    # granite tone: speckle (fine) carries most of the contrast, so it reads as stone, not cloud
    spk = nt.nodes.new("ShaderNodeMath")
    spk.operation = "MULTIPLY"
    nt.links.new(mid.outputs["Fac"], spk.inputs[0])
    nt.links.new(fine.outputs["Fac"], spk.inputs[1])
    gray = nt.nodes.new("ShaderNodeValToRGB")
    gray.color_ramp.elements[0].position = 0.12
    gray.color_ramp.elements[0].color = (0.05, 0.052, 0.056, 1)
    gray.color_ramp.elements[1].position = 0.42
    gray.color_ramp.elements[1].color = (0.36, 0.36, 0.37, 1)
    nt.links.new(spk.outputs[0], gray.inputs["Fac"])
    mask = nt.nodes.new("ShaderNodeValToRGB")
    mask.color_ramp.elements[0].position = 0.6
    mask.color_ramp.elements[0].color = (0, 0, 0, 1)
    mask.color_ramp.elements[1].position = 0.66
    mask.color_ramp.elements[1].color = (1, 1, 1, 1)
    nt.links.new(big.outputs["Fac"], mask.inputs["Fac"])
    mix = nt.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    nt.links.new(mask.outputs["Color"], mix.inputs[0])
    nt.links.new(gray.outputs["Color"], mix.inputs[6])
    mix.inputs[7].default_value = (0.4, 0.17, 0.08, 1)
    # dark fracture lines
    vor = nt.nodes.new("ShaderNodeTexVoronoi")
    vor.feature = "DISTANCE_TO_EDGE"
    vor.inputs["Scale"].default_value = 0.75
    vor.inputs["Randomness"].default_value = 1.0
    nt.links.new(co.outputs["Object"], vor.inputs["Vector"])
    crack = nt.nodes.new("ShaderNodeValToRGB")
    crack.color_ramp.elements[0].position = 0.0
    crack.color_ramp.elements[0].color = (0.5, 0.5, 0.5, 1)
    crack.color_ramp.elements[1].position = 0.018
    crack.color_ramp.elements[1].color = (1, 1, 1, 1)
    nt.links.new(vor.outputs["Distance"], crack.inputs["Fac"])
    mul = nt.nodes.new("ShaderNodeMix")
    mul.data_type = "RGBA"
    mul.blend_type = "MULTIPLY"
    mul.inputs[0].default_value = 1.0
    nt.links.new(mix.outputs[2], mul.inputs[6])
    nt.links.new(crack.outputs["Color"], mul.inputs[7])
    nt.links.new(mul.outputs[2], b.inputs["Base Color"])
    b.inputs["Roughness"].default_value = 0.82
    # chiseled bump: facet cells + grain
    v2 = nt.nodes.new("ShaderNodeTexVoronoi")
    v2.inputs["Scale"].default_value = 4.5
    nt.links.new(co.outputs["Object"], v2.inputs["Vector"])
    add = nt.nodes.new("ShaderNodeMath")
    add.operation = "ADD"
    nt.links.new(v2.outputs["Distance"], add.inputs[0])
    nt.links.new(fine.outputs["Fac"], add.inputs[1])
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 1.0
    bump.inputs["Distance"].default_value = 0.025
    nt.links.new(add.outputs[0], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], b.inputs["Normal"])
    return m


def glass_mat():
    m = bpy.data.materials.new("glass")
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    mix = nt.nodes.new("ShaderNodeMixShader")
    fr = nt.nodes.new("ShaderNodeFresnel")
    fr.inputs["IOR"].default_value = 1.5
    tr = nt.nodes.new("ShaderNodeBsdfTransparent")
    tr.inputs["Color"].default_value = (0.93, 0.97, 0.98, 1)
    gl = nt.nodes.new("ShaderNodeBsdfGlossy")
    gl.inputs["Roughness"].default_value = 0.02
    nt.links.new(fr.outputs[0], mix.inputs[0])
    nt.links.new(tr.outputs[0], mix.inputs[1])
    nt.links.new(gl.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs[0])
    return m


def perf_mat():
    """White perforated sheet steel: a staggered grid of round-ish holes you can see up close."""
    m = h2.pmat("perforated_white", (0.86, 0.87, 0.88), 0.34, 0.3)
    nt = m.node_tree
    b = nt.nodes["Principled BSDF"]
    co = nt.nodes.new("ShaderNodeTexCoord")
    br = nt.nodes.new("ShaderNodeTexBrick")
    br.offset = 0.5
    br.inputs["Scale"].default_value = 1.0
    br.inputs["Brick Width"].default_value = 0.0115
    br.inputs["Row Height"].default_value = 0.0115
    br.inputs["Mortar Size"].default_value = 0.0048
    br.inputs["Mortar Smooth"].default_value = 0.35
    br.inputs["Color1"].default_value = (0.05, 0.052, 0.056, 1)      # hole: you look into the dark cabinet
    br.inputs["Color2"].default_value = (0.06, 0.062, 0.066, 1)
    br.inputs["Mortar"].default_value = (0.86, 0.87, 0.88, 1)        # sheet
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")                       # the brick pattern is 2D: feed it the panel's X and Z
    cmb = nt.nodes.new("ShaderNodeCombineXYZ")
    nt.links.new(co.outputs["Object"], sep.inputs[0])
    nt.links.new(sep.outputs["X"], cmb.inputs["X"])
    nt.links.new(sep.outputs["Z"], cmb.inputs["Y"])
    nt.links.new(cmb.outputs[0], br.inputs["Vector"])
    nt.links.new(br.outputs["Color"], b.inputs["Base Color"])
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.6
    bump.inputs["Distance"].default_value = 0.002
    nt.links.new(br.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], b.inputs["Normal"])
    return m


def floor_mat():
    m = h2.pmat("floor_white", (0.72, 0.73, 0.74), 0.1)
    nt = m.node_tree
    b = nt.nodes["Principled BSDF"]
    co = nt.nodes.new("ShaderNodeTexCoord")
    br = nt.nodes.new("ShaderNodeTexBrick")
    br.offset = 0.0
    br.inputs["Scale"].default_value = 1.0
    br.inputs["Mortar Size"].default_value = 0.003
    br.inputs["Brick Width"].default_value = 0.6
    br.inputs["Row Height"].default_value = 0.6
    br.inputs["Color1"].default_value = (0.7, 0.71, 0.72, 1)
    br.inputs["Color2"].default_value = (0.76, 0.77, 0.78, 1)
    br.inputs["Mortar"].default_value = (0.22, 0.22, 0.22, 1)
    nt.links.new(co.outputs["Object"], br.inputs["Vector"])
    nt.links.new(br.outputs["Color"], b.inputs["Base Color"])
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.2
    bump.invert = True
    nt.links.new(br.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], b.inputs["Normal"])
    t2 = nt.nodes.new("ShaderNodeTexNoise")
    t2.inputs["Scale"].default_value = 1.3
    t2.inputs["Detail"].default_value = 6
    mr = nt.nodes.new("ShaderNodeMapRange")
    mr.inputs["To Min"].default_value = 0.03
    mr.inputs["To Max"].default_value = 0.16
    nt.links.new(co.outputs["Object"], t2.inputs["Vector"])
    nt.links.new(t2.outputs["Fac"], mr.inputs["Value"])
    nt.links.new(mr.outputs["Result"], b.inputs["Roughness"])
    return m


# ------------------------------------------------------------------ cavern
def rock_offset(p):
    v = Vector(p)
    d = 0.5 * noise.fractal(v * 0.3, 1.0, 2.0, 4)                      # broad swells
    d += 0.42 * (noise.cell(v * 0.5) - 0.5)                            # blasted blocks: hard steps
    d += 0.26 * (noise.cell(v * 1.15 + Vector((7.1, 3.3, 1.7))) - 0.5)
    d += 0.12 * (noise.cell(v * 2.6 + Vector((1.3, 9.2, 4.4))) - 0.5)
    d += 0.05 * noise.noise(v * 6.0)
    return d


def cavern(coll, mat):
    nu, nv = 250, 110
    bmh = bmesh.new()
    rows = []
    for i in range(nu + 1):
        x = X_LO + (X_HI - X_LO) * i / nu
        ring = []
        for j in range(nv + 1):
            th = math.pi * j / nv
            c, s = math.cos(th), math.sin(th)
            y = YC + (WD / 2) * (abs(c) ** 0.75) * (1 if c >= 0 else -1)
            z = CEIL * (s ** 0.55)
            n = Vector((0, c, s * 0.9)).normalized()
            off = rock_offset((x, y, z))
            if z < 2.6 and c > 0:                     # keep the aisle behind the racks walkable
                off = max(-0.25, min(off, 0.45))
            p = Vector((x, y, z)) + n * off
            if j in (0, nv):
                p.z = -0.05
            ring.append(bmh.verts.new(p))
        rows.append(ring)
    for i in range(nu):
        for j in range(nv):
            bmh.faces.new((rows[i][j], rows[i][j + 1], rows[i + 1][j + 1], rows[i + 1][j]))
    # end caps
    for x, flip in ((X_LO, False), (X_HI, True)):
        ny, nz = 70, 36
        grid = []
        for a in range(ny + 1):
            col = []
            for bq in range(nz + 1):
                y = YC - WD / 2 - 0.8 + (WD + 1.6) * a / ny
                z = -0.05 + (CEIL + 1.0) * bq / nz
                off = rock_offset((x, y, z)) * 0.9
                col.append(bmh.verts.new((x + (off if not flip else -off), y, z)))
            grid.append(col)
        for a in range(ny):
            for bq in range(nz):
                f = (grid[a][bq], grid[a + 1][bq], grid[a + 1][bq + 1], grid[a][bq + 1])
                bmh.faces.new(f if flip else tuple(reversed(f)))
    me = bpy.data.meshes.new("cavern")
    bmh.to_mesh(me)
    bmh.free()
    me.materials.append(mat)
    o = bpy.data.objects.new("cavern", me)
    coll.objects.link(o)
    return o


# ------------------------------------------------------------------ white cabinets and doors
def door(coll, parent, hinge, rot, mats, width=RW, height=RH - 0.1):
    e = bm.empty("door", coll, parent, hinge)
    e.rotation_euler = (0, 0, rot)
    f = 0.035
    for x in (f / 2, width - f / 2):
        bm.box("door_stile", (f, 0.022, height), (x, 0, height / 2 + 0.05), mats["cab"], coll, e, 0.003)
    for z in (0.05 + f / 2, height + 0.05 - f / 2):
        bm.box("door_rail", (width, 0.022, f), (width / 2, 0, z), mats["cab"], coll, e, 0.003)
    bm.box("door_perf", (width - 2 * f, 0.003, height - 2 * f), (width / 2, 0, height / 2 + 0.05), mats["perf"], coll, e)
    bm.box("door_handle", (0.03, 0.03, 0.26), (width - 0.06, -0.02, 1.15), mats["cab"], coll, e, 0.008)
    bm.box("door_latch", (0.018, 0.012, 0.05), (width - 0.06, -0.037, 1.08), mats["chrome"], coll, e, 0.002)
    for z in (0.32, height / 2 + 0.05, height - 0.22):
        bm.cyl("door_hinge", 0.009, 0.075, (0.0, 0.006, z), mats["chrome"], coll, e, "Z", 10)
    bm.box("door_label", (0.085, 0.002, 0.028), (0.11, -0.0125, height - 0.1), mats["core"], coll, e)
    bm.box("door_label_txt", (0.06, 0.0015, 0.006), (0.105, -0.0138, height - 0.1), mats["cab"], coll, e)
    return e


def cabinet_source(coll, mats):
    """One closed white cabinet (the neighbours are instances of this)."""
    root = bm.empty("CAB", coll)
    for x in (0.012, RW - 0.012):
        bm.box("cab_side", (0.024, RD, RH), (x, RD / 2, RH / 2), mats["cab"], coll, root, 0.003)
    bm.box("cab_top", (RW, RD, 0.03), (RW / 2, RD / 2, RH - 0.015), mats["cab"], coll, root, 0.003)
    bm.box("cab_base", (RW, RD, 0.06), (RW / 2, RD / 2, 0.03), mats["cab"], coll, root, 0.003)
    bm.box("cab_core", (RW - 0.08, RD - 0.16, RH - 0.14), (RW / 2, RD / 2, RH / 2), mats["core"], coll, root)
    for y in (0.004, RD - 0.004):
        bm.box("cab_kick", (RW - 0.01, 0.014, 0.046), (RW / 2, y, 0.023), mats["core"], coll, root)
    bm.box("cab_brush", (RW - 0.14, 0.12, 0.012), (RW / 2, RD - 0.16, RH + 0.004), mats["core"], coll, root)
    rnd = random.Random(7)
    for k in range(34):                    # status lights glimmering behind the mesh door
        z = 0.2 + rnd.random() * (RH - 0.45)
        x = 0.08 + rnd.random() * (RW - 0.16)
        bm.box("cab_led", (0.005, 0.003, 0.005), (x, 0.078, z), mats["led_g"] if rnd.random() < 0.8 else mats["led_b"], coll, root)
    for k in range(27):
        bm.box("cab_line", (RW - 0.1, 0.004, 0.012), (RW / 2, 0.079, 0.16 + k * 0.074), mats["steel"], coll, root)
    door(coll, root, (0, -0.002, 0), 0.0, mats)
    door(coll, root, (RW, RD + 0.002, 0), math.pi, mats)
    return root


# ------------------------------------------------------------------ lights
def twin_tubes(coll, mats, a, b_, z, seg=3.0):
    """A hanging run of twin-tube fixtures from point a to b (x, y)."""
    ax, ay = a
    bx, by = b_
    L = math.hypot(bx - ax, by - ay)
    n = max(1, int(L / seg))
    ang = math.atan2(by - ay, bx - ax)
    for i in range(n + 1):
        t = i / n
        x, y = ax + (bx - ax) * t, ay + (by - ay) * t
        h = bm.box("lamp_house", (0.3, 0.34, 0.2), (x, y, z + 0.06), mats["cab"], coll, None, 0.03)
        h.rotation_euler = (0, 0, ang)
        bm.cyl("lamp_rod", 0.006, 3.2, (x, y, z + 1.75), mats["chrome"], coll, None, "Z", 8)
        if i < n:
            mx, my = x + (bx - ax) / n / 2, y + (by - ay) / n / 2
            for s in (-0.07, 0.07):
                ox, oy = -math.sin(ang) * s, math.cos(ang) * s
                tb = bm.cyl("lamp_tube", 0.02, L / n - 0.32, (mx + ox, my + oy, z), mats["tube"], coll, None, "X", 12)
                tb.rotation_euler = (0, math.pi / 2, ang)


# ------------------------------------------------------------------ suspended glass room + bridge
def wire_chair(coll, mats, loc, rot):
    me = bpy.data.meshes.new("chair")
    b = bmesh.new()
    bmesh.ops.create_icosphere(b, subdivisions=1, radius=0.33)
    for v in list(b.verts):
        if v.co.z > 0.12 and v.co.y < 0.05:
            b.verts.remove(v)
    b.to_mesh(me)
    b.free()
    me.materials.append(mats["chairwire"])
    o = bpy.data.objects.new("chair", me)
    o.location = (loc[0], loc[1], loc[2] + 0.5)
    o.rotation_euler = (0, 0, rot)
    w = o.modifiers.new("wire", "WIREFRAME")
    w.thickness = 0.016
    coll.objects.link(o)
    for a in range(4):
        an = rot + math.pi / 4 + a * math.pi / 2
        leg = bm.cyl("chair_leg", 0.008, 0.36, (loc[0] + 0.2 * math.cos(an), loc[1] + 0.2 * math.sin(an), loc[2] + 0.18),
                     mats["chairwire"], coll, None, "Z", 6)
        leg.rotation_euler = (0.12 * math.sin(an), -0.12 * math.cos(an), 0)


def glass_room(coll, mats):
    cx, cy, fz, r = POD
    disc = lambda name, rad, h, z, mat, segs=72: bm.cyl(name, rad, h, (cx, cy, z), mat, coll, None, "Z", segs)
    disc("pod_slab", r + 0.12, 0.34, fz - 0.17, mats["bronze"])
    disc("pod_under", r * 0.42, 0.04, fz - 0.36, mats["core"])
    disc("pod_floor", r, 0.02, fz + 0.01, mats["carpet"])
    disc("pod_ceiling", r + 0.05, 0.16, fz + 2.62, mats["cab"])
    n = 16
    for k in range(n):                      # mullions + glass panes
        a = 2 * math.pi * k / n
        bm.cyl("pod_mullion", 0.03, 2.5, (cx + r * math.cos(a), cy + r * math.sin(a), fz + 1.27), mats["chrome"], coll, None, "Z", 10)
        am = a + math.pi / n
        if abs(((am - math.pi * 1.5 + math.pi) % (2 * math.pi)) - math.pi) < math.pi / n * 1.1:
            continue                        # doorway to the bridge
        w = 2 * r * math.sin(math.pi / n)
        g = bm.box("pod_glass", (w, 0.012, 2.46), (cx + r * math.cos(math.pi / n) * math.cos(am), cy + r * math.cos(math.pi / n) * math.sin(am),
                                                    fz + 1.27), mats["glass"], coll)
        g.rotation_euler = (0, 0, am + math.pi / 2)
    for k in range(10):
        a = 2 * math.pi * k / 10
        bm.cyl("pod_spot", 0.04, 0.02, (cx + 2.2 * math.cos(a), cy + 2.2 * math.sin(a), fz + 2.53), mats["tube"], coll, None, "Z", 12)
    disc("pod_table", 1.0, 0.02, fz + 0.76, mats["glass"], 48)
    for k in range(6):
        a = 2 * math.pi * k / 6
        bm.cyl("pod_tleg", 0.02, 0.74, (cx + 0.6 * math.cos(a), cy + 0.6 * math.sin(a), fz + 0.38), mats["chrome"], coll, None, "Z", 8)
    for k in range(8):
        a = 2 * math.pi * k / 8 + 0.2
        wire_chair(coll, mats, (cx + 1.75 * math.cos(a), cy + 1.75 * math.sin(a), fz + 0.02), a + math.pi)
    bm.box("pod_cabinet", (1.6, 0.4, 0.75), (cx + 0.3, cy + r - 0.5, fz + 0.4), mats["cab"], coll, None, 0.01)
    bm.box("pod_tv", (1.1, 0.04, 0.62), (cx + 0.3, cy + r - 0.48, fz + 1.4), mats["tv"], coll, None, 0.005)
    for dx, dy in ((1.6, 1.6), (-1.6, 1.6), (1.6, -1.6), (-1.6, -1.6)):
        bm.cyl("pod_hanger", 0.03, CEIL - fz - 2.0, (cx + dx, cy + dy, fz + 2.7 + (CEIL - fz - 2.0) / 2), mats["chrome"], coll, None, "Z", 10)
    # glass bridge from the room to the far rock wall
    y0, y1, w, h = cy - r + 0.05, Y_FAR + 0.6, 1.7, 2.45
    L = y0 - y1
    ym = (y0 + y1) / 2
    bm.box("bridge_floor", (w, L, 0.06), (cx, ym, fz - 0.03), mats["glassfloor"], coll)
    bm.box("bridge_roof", (w, L, 0.012), (cx, ym, fz + h), mats["glass"], coll)
    for sx in (-w / 2, w / 2):
        bm.box("bridge_glass", (0.012, L, h), (cx + sx, ym, fz + h / 2), mats["glass"], coll)
        for z in (fz - 0.03, fz + h):
            bm.box("bridge_beam", (0.07, L, 0.07), (cx + sx, ym, z), mats["chrome"], coll, None, 0.004)
    k = 0
    while y1 + k * 2.2 <= y0:
        yy = y1 + k * 2.2
        for sx in (-w / 2, w / 2):
            bm.box("bridge_post", (0.07, 0.07, h), (cx + sx, yy, fz + h / 2), mats["chrome"], coll, None, 0.004)
            bm.cyl("bridge_hanger", 0.02, 2.4, (cx + sx, yy, fz + h + 1.2), mats["chrome"], coll, None, "Z", 8)
        bm.box("bridge_cross", (w, 0.07, 0.07), (cx, yy, fz + h), mats["chrome"], coll, None, 0.004)
        k += 1


# ------------------------------------------------------------------ hall
def build_hall(hall, cab_coll, m, cm, mats):
    def inst(loc, rotz=0.0):
        e = bpy.data.objects.new("cabinst", None)
        e.instance_type = "COLLECTION"
        e.instance_collection = cab_coll
        e.location = loc
        e.rotation_euler = (0, 0, rotz)
        hall.objects.link(e)

    cavern(hall, mats["rock"])
    bm.box("floor", (X_HI - X_LO + 2, WD + 2, 0.04), ((X_LO + X_HI) / 2, YC, -0.02), mats["floor"], hall)
    xs0, xs1 = ROW[0] * RW, (ROW[-1] + 1) * RW
    for k in ROW:
        x = k * RW
        if k != 0:
            inst((x, 0, 0))
        bm.box("placard", (0.2, 0.004, 0.07), (x + RW / 2, -0.03, RH + 0.05), cm["plate"], hall, None, 0.002)
        h2.text("ptxt", f"R{12 + k:02d}", 0.05, (x + RW / 2, -0.033, RH + 0.05), (math.pi / 2, 0, 0), cm["white"], hall)
    # light strips along the top of the row (they wash the rock, as in the photos)
    for y in (0.1, RD - 0.1):
        bm.box("row_strip", (xs1 - xs0, 0.05, 0.03), ((xs0 + xs1) / 2, y, RH + 0.14), mats["tube"], hall)
        bm.box("row_strip_body", (xs1 - xs0, 0.09, 0.05), ((xs0 + xs1) / 2, y, RH + 0.1), mats["cab"], hall)
    # in-row CDU at the west end, coolant mains above the row
    cx = xs0 - 0.46
    bm.box("cdu", (0.85, RD, RH), (cx, RD / 2, RH / 2), mats["cab"], hall, None, 0.006)
    bm.box("cdu_screen", (0.26, 0.006, 0.16), (cx, -0.004, 1.55), cm["screen"], hall, None, 0.002)
    bm.box("cdu_vent", (0.6, 0.006, 0.9), (cx, -0.004, 0.65), mats["perf"], hall)
    for i, band in enumerate((cm["pipe_b"], cm["pipe_r"])):
        y = RD - 0.22 - 0.2 * i
        z = RH + 0.36 + 0.14 * i
        bm.cyl("main", 0.06, xs1 - cx, ((cx + xs1) / 2, y, z), cm["pipe"], hall, None, "X", 32)
        bm.cyl("riser", 0.05, z - RH, (cx - 0.15 + 0.3 * i, y, RH + (z - RH) / 2), band, hall, None, "Z", 20)
        x = cx
        while x < xs1:
            bm.cyl("band", 0.062, 0.1, (x, y, z), band, hall, None, "X", 32)
            x += 1.86
        for k in ROW:
            mx = k * RW + (0.065 if i == 0 else RW - 0.065)
            bm.tube("branch", [(mx, y, z - 0.05), (mx, (y + RD - 0.07) / 2, RH + 0.2), (mx, RD - 0.07, RH - 0.05)], 0.018, band, hall)
    # slim white tray above the row fronts that takes R12's fiber
    bm.box("raceway", (xs1 - xs0, 0.1, 0.07), ((xs0 + xs1) / 2, -0.16, RH + 0.26), mats["cab"], hall, None, 0.006)
    for k in range(0, 21, 3):
        bm.cyl("raceway_rod", 0.006, 3.0, (xs0 + k * RW + 0.3, -0.16, RH + 1.8), mats["chrome"], hall, None, "Z", 8)

    # hanging twin-tube lights: front of the row, the rock aisle behind it, and across the hall
    twin_tubes(hall, mats, (xs0 - 1.5, -1.7), (xs1 + 1.5, -1.7), 3.25)
    twin_tubes(hall, mats, (xs0 - 1.0, 1.95), (xs1 + 1.0, 1.95), 3.05)
    twin_tubes(hall, mats, (-7.5, -5.2), (13.5, -5.2), 3.6)
    twin_tubes(hall, mats, (-7.5, -12.0), (0.5, -12.0), 3.4)
    # two enclosed pods of white cabinets across the hall + a dark cabinet group
    for bx in (-8.5, -2.6):
        for k in range(8):
            inst((bx + k * RW, -14.6, 0))
            inst((bx + (k + 1) * RW, -11.4, 0), math.pi)
        bm.box("pod_roof", (8 * RW + 0.1, 2.1 + 0.1, 0.04), (bx + 4 * RW, -13.05, RH + 0.02), mats["cab"], hall)
        for ex in (bx - 0.02, bx + 8 * RW + 0.02):
            bm.box("pod_end", (0.04, 2.1, RH), (ex, -13.05, RH / 2), mats["perf"], hall)
        bm.box("pod_strip", (8 * RW, 0.05, 0.03), (bx + 4 * RW, -11.42, RH + 0.1), mats["tube"], hall)
    for k in range(3):
        bm.box("dark_cab", (0.8, 1.0, 1.9), (10.5 + k * 0.84, -12.6, 0.95), mats["darkcab"], hall, None, 0.01)
        bm.box("dark_cab_grille", (0.7, 0.01, 0.5), (10.5 + k * 0.84, -12.095, 0.4), mats["core"], hall)
    for k, (gx, gy) in enumerate(((-9.3, -6.0), (15.4, -3.0))):       # red gas cylinders
        bm.cyl("cylinder", 0.13, 1.35, (gx, gy, 0.7), cm["firered"], hall, None, "Z", 24)
        bm.cyl("cylinder_cap", 0.05, 0.14, (gx, gy, 1.45), mats["chrome"], hall, None, "Z", 12)
    for gx in range(-4, 12, 3):                                      # floor grilles in front of the row
        bm.box("grille", (0.56, 0.56, 0.004), (gx * 0.6 + 0.3, -0.9, 0.002), mats["grille"], hall)
    glass_room(hall, mats)
    # accent light on the rock at the east end
    for loc, tgt, col, pw in (((14.5, -9.0, 0.6), (17.0, -13.0, 3.5), (1.0, 0.28, 0.08), 2600),
                              ((-9.5, -15.0, 0.5), (-11.0, -17.0, 4.0), (1.0, 0.4, 0.15), 1500)):
        l = bpy.data.lights.new("accent", "SPOT")
        l.energy = pw
        l.color = col
        l.spot_size = 1.5
        l.spot_blend = 0.8
        o = bpy.data.objects.new("accent", l)
        hall.objects.link(o)
        o.location = loc
        o.rotation_euler = (Vector(tgt) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    # tool cases on the open floor
    for k in range(3):
        bm.box("toolcase", (0.5, 0.36, 0.2), (7.4, -3.3, 0.1 + k * 0.21), mats["darkcab"], hall, None, 0.014)
        for sx in (-0.15, 0.15):
            bm.box("toolcase_latch", (0.03, 0.006, 0.05), (7.4 + sx, -3.483, 0.12 + k * 0.21), mats["chrome"], hall, None, 0.002)


def bench(coll, m, cm, mats):
    """Rolling ESD bench that holds the open tray."""
    bx, by = BENCH
    c = bm.empty("BENCH", coll)
    bm.box("bench_top", (1.15, 1.25, 0.03), (bx, by, 0.9), m["steel"], coll, c, 0.004)
    bm.box("bench_mat", (1.05, 1.15, 0.004), (bx, by, 0.917), cm["esd"], coll, c)
    bm.box("bench_shelf", (1.1, 1.2, 0.02), (bx, by, 0.28), m["steel"], coll, c, 0.004)
    for sx in (-0.52, 0.52):
        for sy in (-0.57, 0.57):
            bm.cyl("bench_leg", 0.016, 0.88, (bx + sx, by + sy, 0.46), m["steel"], coll, c, "Z", 12)
            bm.cyl("bench_wheel", 0.045, 0.03, (bx + sx, by + sy, 0.045), m["black"], coll, c, "X", 18)
    bm.box("laptop_base", (0.3, 0.21, 0.014), (bx + 0.36, by - 0.42, 0.926), m["dark"], coll, c, 0.003)
    lid = bm.box("laptop_lid", (0.3, 0.01, 0.2), (bx + 0.36, by - 0.31, 1.03), m["dark"], coll, c, 0.003)
    lid.rotation_euler = (math.radians(-14), 0, 0)
    s2 = bm.box("laptop_screen", (0.28, 0.002, 0.18), (bx + 0.36, by - 0.317, 1.03), cm["screen"], coll, c)
    s2.rotation_euler = (math.radians(-14), 0, 0)
    return (bx - TW / 2 - 0.12, by - TD / 2 + 0.08, 0.92)


# ------------------------------------------------------------------ build
def build():
    global sc
    bm.reset()
    bm.MATS.clear()
    h2.ID_MATS.clear()
    sc = bpy.context.scene
    h2.sc = sc
    m = bm.M()
    cm = h2.materials_extra()
    mats = dict(
        rock=rock_mat(), glass=glass_mat(), perf=perf_mat(), floor=floor_mat(),
        cab=h2.pmat("cabinet_white", (0.84, 0.85, 0.86), 0.32, 0.25), core=h2.pmat("core_dark", (0.01, 0.011, 0.012), 0.6),
        chrome=h2.pmat("chrome", (0.75, 0.76, 0.78), 0.18, 1.0), tube=h2.pmat("tube", (1.0, 0.985, 0.96), 0.4, 0.0, 34.0),
        bronze=h2.pmat("bronze", (0.09, 0.07, 0.055), 0.32, 0.9), carpet=h2.pmat("carpet", (0.2, 0.17, 0.15), 0.95),
        chairwire=h2.pmat("chairwire", (0.02, 0.02, 0.022), 0.4, 0.8), tv=h2.pmat("tv", (0.01, 0.01, 0.012), 0.08),
        glassfloor=h2.pmat("glassfloor", (0.45, 0.6, 0.62), 0.03, 0.0, 0.0, 0.35),
        darkcab=h2.pmat("darkcab", (0.03, 0.032, 0.035), 0.4, 0.5), grille=h2.pmat("grille", (0.12, 0.125, 0.13), 0.45, 0.8),
        led_g=m["led_g"], led_b=m["led_b"], steel=m["steel"])
    # R12 keeps its gear; only the enclosure turns white
    fb = m["frame"].node_tree.nodes["Principled BSDF"]
    fb.inputs["Base Color"].default_value = (0.84, 0.85, 0.86, 1)
    fb.inputs["Metallic"].default_value = 0.25
    fb.inputs["Roughness"].default_value = 0.32
    c_r12 = h2.col("r12")
    c_cab = h2.col("cab")
    c_hall = h2.col("hall")
    c_tray = h2.col("tray")
    r12 = bm.build_rack(c_r12, m)
    h2.detail_rack(r12, c_r12, m, cm, None)
    door(c_r12, r12, (0, -0.002, 0), math.radians(-105), mats)        # front door, open
    door(c_r12, r12, (RW, RD + 0.002, 0), math.pi - math.radians(105), mats)   # rear door, open
    cabinet_source(c_cab, mats)
    build_hall(c_hall, c_cab, m, cm, mats)
    spot = bench(c_hall, m, cm, mats)
    tray, _ = bm.build_tray(c_tray, m, "TRAY")
    h2.detail_tray(tray, c_tray, m, cm)
    lid = bpy.data.objects.get("PART_lid")
    for o in list(lid.children_recursive) + [lid]:
        bpy.data.objects.remove(o)
    tray.location = spot

    def excl(lc):
        for ch in lc.children:
            if ch.collection == c_cab:
                ch.exclude = True
            excl(ch)
    excl(bpy.context.view_layer.layer_collection)
    g = mats["grille"].node_tree                 # vent tiles: a grid of square holes
    gco = g.nodes.new("ShaderNodeTexCoord")
    gbr = g.nodes.new("ShaderNodeTexBrick")
    gbr.offset = 0.0
    gbr.inputs["Scale"].default_value = 1.0
    gbr.inputs["Brick Width"].default_value = 0.022
    gbr.inputs["Row Height"].default_value = 0.022
    gbr.inputs["Mortar Size"].default_value = 0.007
    gbr.inputs["Color1"].default_value = (0.006, 0.006, 0.008, 1)
    gbr.inputs["Color2"].default_value = (0.008, 0.008, 0.01, 1)
    gbr.inputs["Mortar"].default_value = (0.5, 0.51, 0.53, 1)
    g.links.new(gco.outputs["Object"], gbr.inputs["Vector"])
    g.links.new(gbr.outputs["Color"], g.nodes["Principled BSDF"].inputs["Base Color"])
    h2.enrich()
    return dict(r12=c_r12, hall=c_hall, tray=c_tray, rack=r12, trayroot=tray, cm=cm, spot=spot)


HERO = {
    "front": ((RW / 2, -1.9, 1.55), "In front of R12"),
    "rear": ((RW / 2, RD + 0.85, 1.55), "Rock aisle, behind R12"),
    "hall": ((8.7, -5.0, 1.55), "Main floor, by the glass room"),
}


def walk_stations():
    """Viewpoints about one step apart, so the arrow keys can walk the hall."""
    S = {}

    def add(name, x, y, title):
        S[name] = ((round(x, 2), round(y, 2), 1.55), title)

    xs = [-7.4 + 1.4 * i for i in range(13)]
    for i, x in enumerate(xs):
        add(f"f{i:02d}", x, -1.9, "Along the row")
        if x < 8.2:
            add(f"r{i:02d}", x, RD + 0.85, "Rock aisle")
    for x, tag in ((-7.4, "w"), (8.0, "e")):
        add(f"{tag}0", x, -0.6, "End of the row")
        add(f"{tag}1", x, 0.7, "End of the row")
    for i, x in enumerate((-4.6, 1.0, 5.2, 9.4)):
        add(f"c{i}", x, -3.45, "Main floor")
    for i in range(13):
        x = -5.3 + 1.4 * i
        if abs(x - 8.7) > 0.2:
            add(f"m{i:02d}", x, -5.0, "Main floor")
    for i, x in enumerate((1.7, 8.7)):
        add(f"n{i}", x, -6.4, "Main floor")
    for i in range(6):
        add(f"p{i}", 1.4 + 1.4 * i, -7.9, "Under the glass room")
    add("q0", 5.6, -9.3, "Under the glass bridge")
    add("q1", 5.6, -10.7, "Under the glass bridge")
    return S


STATIONS = dict(HERO)
STATIONS.update(walk_stations())


def setup(samples, w, h):
    h2.cycles(samples, w, h)
    sc.cycles.max_bounces = 10
    sc.cycles.transparent_max_bounces = 16
    sc.view_settings.exposure = 0.1
    scr = bpy.data.materials.get("screen")
    if scr:
        sb = scr.node_tree.nodes["Principled BSDF"]
        sb.inputs["Base Color"].default_value = (0.02, 0.1, 0.16, 1)
        sb.inputs["Emission Color"].default_value = (0.05, 0.3, 0.45, 1)
        sb.inputs["Emission Strength"].default_value = 1.4
    h2.world(0.015, (0.5, 0.55, 0.65))


def shot_test(S):
    setup(64, 1280, 720)
    for name, loc, tgt, lens in (("hall", (11.5, -5.0, 1.65), (2.0, -4.5, 2.0), 17),
                                 ("front", (RW / 2 + 1.4, -2.7, 1.55), (RW / 2 - 0.2, 0, 1.25), 22),
                                 ("rear", (-3.2, 1.95, 1.6), (4.0, 1.7, 1.5), 20),
                                 ("bench", (BENCH[0] - 0.75, BENCH[1] - 0.95, 1.62), (BENCH[0], BENCH[1], 0.95), 38)):
        h2.camera(loc, tgt, lens)
        h2.save(os.path.join(REN, f"v3_{name}.jpg"))


def pano_camera(loc):
    return h2.camera(loc, (loc[0] + 5, loc[1], loc[2]), 18, True)


def shot_panos(S, samples, only=None):
    """Beauty for every station (hero ones at 8K), then the ID layer for every station."""
    h2.leds_off(S["r12"])
    names = [n for n in STATIONS if not only or n in only]
    for name in names:
        hero = name in HERO
        setup(samples if hero else 48, *((8192, 4096) if hero else (4096, 2048)))
        pano_camera(STATIONS[name][0])
        h2.save(os.path.join(IMG, f"pano_{name}.jpg"), "JPEG", 90)
    h2.id_pass(h2.rack_id)
    for name in names:
        hero = name in HERO
        sc.render.resolution_x, sc.render.resolution_y = (4096, 2048) if hero else (2048, 1024)
        pano_camera(STATIONS[name][0])
        h2.save(os.path.join(IMG, f"pano_{name}_id.png"), "PNG")


def tray_cams(S):
    sx, sy, sz = S["spot"]
    cx, cy = sx + TW / 2, sy + TD / 2
    cams = []
    for k in range(h2.TRAY_FRAMES):
        a = -math.pi / 2 + k * 2 * math.pi / h2.TRAY_FRAMES
        cams.append(((cx + 1.22 * math.cos(a), cy + 1.22 * math.sin(a), sz + 0.9), (cx, cy, sz + 0.012), 42))
    cams.append(((cx, cy, sz + 1.3), (cx, cy, sz), 40))        # straight down, front of the tray on the left
    return cams, (cx, cy, sz)


def tray_camera(k, loc, tgt, lens, dof=True):
    c = h2.camera(loc, tgt, lens)
    if k == h2.TRAY_FRAMES:
        c.rotation_euler = (0, 0, math.pi / 2)
    if dof:
        c.data.dof.use_dof = True
        c.data.dof.focus_distance = (Vector(loc) - Vector(tgt)).length
        c.data.dof.aperture_fstop = 7.1
    return c


def shot_tray(S, samples):
    cams, (cx, cy, sz) = tray_cams(S)
    for ob in bpy.data.objects:                    # the laptop would block some angles
        if ob.name.startswith("laptop"):
            ob.hide_render = True
    l = bpy.data.lights.new("task", "AREA")       # soft fill over the bench
    l.size = 1.4
    l.energy = 45
    o = bpy.data.objects.new("task", l)
    sc.collection.objects.link(o)
    o.location = (cx, cy, sz + 1.9)
    setup(samples, 1920, 1080)
    sc.view_settings.exposure = -0.25
    for k, (loc, tgt, lens) in enumerate(cams):
        tray_camera(k, loc, tgt, lens)
        h2.save(os.path.join(IMG, f"tray_{k:02d}.jpg"), "JPEG", 90)
    h2.id_pass(h2.tray_id)
    for k, (loc, tgt, lens) in enumerate(cams):
        sc.render.resolution_x, sc.render.resolution_y = 1920, 1080
        tray_camera(k, loc, tgt, lens, False)
        h2.save(os.path.join(IMG, f"tray_{k:02d}_id.png"), "PNG")


WALK_RES, WALK_SPP = (6144, 3072), 64
TRAY_RES = (3840, 2160)
DONE_FILE = os.path.join(REN, "final_done.txt")


def done_set():
    try:
        with open(DONE_FILE) as f:
            return set(f.read().split())
    except OSError:
        return set()


def mark_done(key):
    with open(DONE_FILE, "a") as f:
        f.write(key + "\n")


def station_order():
    """Hero views first, then outward from R12, so the nearest viewpoints are ready first."""
    walk = [n for n in STATIONS if n not in HERO]
    walk.sort(key=lambda n: math.hypot(STATIONS[n][0][0] - RW / 2, STATIONS[n][0][1] + 1.9))
    return list(HERO) + walk


def shot_final_panos(S, samples, which="all"):
    """Beauty only (the ID layers come from the 'ids' job). Skips views that are already done, so it can resume."""
    h2.leds_off(S["r12"])
    done = done_set()
    for name in station_order():
        key = f"pano_{name}"
        hero = name in HERO
        if key in done or (which == "hero" and not hero) or (which == "walk" and hero):
            continue
        setup(samples if hero else WALK_SPP, *((8192, 4096) if hero else WALK_RES))
        pano_camera(STATIONS[name][0])
        h2.save(os.path.join(IMG, f"{key}.jpg"), "JPEG", 92)
        mark_done(key)


def shot_final_tray(S, samples):
    cams, (cx, cy, sz) = tray_cams(S)
    for ob in bpy.data.objects:
        if ob.name.startswith("laptop"):
            ob.hide_render = True
    l = bpy.data.lights.new("task", "AREA")
    l.size = 1.4
    l.energy = 45
    o = bpy.data.objects.new("task", l)
    sc.collection.objects.link(o)
    o.location = (cx, cy, sz + 1.9)
    done = done_set()
    for k, (loc, tgt, lens) in enumerate(cams):
        key = f"tray_{k:02d}"
        if key in done:
            continue
        setup(samples, *TRAY_RES)
        sc.view_settings.exposure = -0.25
        tray_camera(k, loc, tgt, lens)
        h2.save(os.path.join(IMG, f"{key}.jpg"), "JPEG", 92)
        mark_done(key)


def shot_ids(kind):
    """Only the ID layers (fast). kind: panos | tray"""
    def run(S):
        setup(1, 4096, 2048)
        if kind == "panos":
            h2.id_pass(h2.rack_id)
            for name in STATIONS:
                sc.render.resolution_x, sc.render.resolution_y = (4096, 2048) if name in HERO else (3072, 1536)
                pano_camera(STATIONS[name][0])
                h2.save(os.path.join(IMG, f"pano_{name}_id.png"), "PNG")
        else:
            cams, _ = tray_cams(S)
            h2.id_pass(h2.tray_id)
            for k, (loc, tgt, lens) in enumerate(cams):
                sc.render.resolution_x, sc.render.resolution_y = TRAY_RES
                tray_camera(k, loc, tgt, lens, False)
                h2.save(os.path.join(IMG, f"tray_{k:02d}_id.png"), "PNG")
    return run


def shot_fly(S, samples, n):
    setup(samples, 1600, 900)
    c = h2.camera((14.5, -6.5, 1.75), (5.0, -6.0, 2.4), 20)
    tgt = bpy.data.objects.new("tgt", None)
    sc.collection.objects.link(tgt)
    con = c.constraints.new("TRACK_TO")
    con.target = tgt
    con.track_axis = "TRACK_NEGATIVE_Z"
    con.up_axis = "UP_Y"
    keys = ((1, (14.5, -6.5, 1.75), (5.0, -6.5, 2.6)), (int(n * 0.55), (6.0, -4.2, 1.65), (0.6, -0.5, 1.5)),
            (n, (RW / 2 + 0.9, -2.3, 1.52), (RW / 2 - 0.1, 0.0, 1.22)))
    for f, loc, t in keys:
        c.location = loc
        c.keyframe_insert("location", frame=f)
        tgt.location = t
        tgt.keyframe_insert("location", frame=f)
    sc.frame_start, sc.frame_end = 1, n
    sc.render.image_settings.file_format = "JPEG"
    sc.render.image_settings.quality = 92
    os.makedirs(os.path.join(REN, "fly3"), exist_ok=True)
    sc.render.filepath = os.path.join(REN, "fly3", "f_")
    bpy.ops.render.render(animation=True)


def shot_traytest(S):
    cams, _ = tray_cams(S)
    setup(48, 960, 540)
    sc.view_settings.exposure = -0.25
    for k in (0, 5, h2.TRAY_FRAMES):
        loc, tgt, lens = cams[k]
        tray_camera(k, loc, tgt, lens)
        h2.save(os.path.join(REN, f"v3_tray_{k:02d}.jpg"))


def manifest():
    data = {"stations": {k: {"title": v[1], "pos": v[0], "hero": k in HERO} for k, v in STATIONS.items()},
            "tray_frames": h2.TRAY_FRAMES + 1, "tray_top": h2.TRAY_FRAMES, "tray_ids": h2.TRAY_ID,
            "plan": {"row": [ROW[0] * RW, 0.0, (ROW[-1] + 1) * RW, RD], "r12": [0.0, 0.0, RW, RD], "pod": [POD[0], POD[1], POD[3]],
                     "bench": [BENCH[0], BENCH[1]], "wall_y": Y_WALL}}
    with open(os.path.join(IMG, "manifest.json"), "w") as f:
        json.dump(data, f, indent=1)


def main():
    what = sys.argv[1] if len(sys.argv) > 1 else "test"
    samples = int(sys.argv[2]) if len(sys.argv) > 2 else 128
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 180
    jobs = {"test": [shot_test], "panos": [lambda S: shot_panos(S, samples)], "tray": [lambda S: shot_tray(S, samples)],
            "fly": [lambda S: shot_fly(S, samples, n)],
            "walkall": [lambda S: shot_panos(S, samples), lambda S: shot_tray(S, samples)],
            "walktest": [lambda S: shot_panos(S, 32, ("f03", "p2", "r07"))],
            "final": [lambda S: shot_final_panos(S, samples, "hero"), lambda S: shot_final_tray(S, samples),
                      lambda S: shot_final_panos(S, samples, "walk")], "traytest": [lambda S: shot_traytest(S)],
            "trayfly": [lambda S: shot_tray(S, samples), lambda S: shot_fly(S, 48, n)], "ids": [shot_ids("panos"), shot_ids("tray")], "idsp": [shot_ids("panos")], "idst": [shot_ids("tray")],
            "all": [lambda S: shot_panos(S, samples), lambda S: shot_tray(S, samples), lambda S: shot_fly(S, 64, n)]}[what]
    for job in jobs:
        S = build()
        job(S)
    manifest()
    print("DONE", what, flush=True)


if __name__ == "__main__":
    main()
