"""Data hall v2: a bright, liquid-cooled 2026 AI hall around rack R12, path-traced with Cycles.

    python hall2.py test                 quick 1280x720 stills to judge the look
    python hall2.py panos [samples]      360 beauty + ID layers for the stations (front, rear, aisle)
    python hall2.py tray [samples]       tray orbit frames + ID layers
    python hall2.py fly [samples] [n]    fly-through frames
    python hall2.py all

Every interactive part of R12 and of the tray gets an ID colour in a second render, so the web app
can tell which part a pixel belongs to. Output goes to ../lab/web/img (+ manifest.json).
"""
import json
import math
import os
import sys

import bpy  # noqa: E402
from mathutils import Vector  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_models as bm  # noqa: E402

IMG = os.path.join(HERE, "..", "lab", "web", "img")
REN = os.path.join(HERE, "renders")
os.makedirs(IMG, exist_ok=True)
os.makedirs(REN, exist_ok=True)

RW, RD, RH, OU, TW, TD, TH = bm.RW, bm.RD, bm.RH, bm.OU, bm.TW, bm.TD, bm.TH
AISLE = 2.6                    # cold aisle width
HOT = 1.5                      # hot aisle width
ROW = range(-9, 12)            # rack positions in a row (0 = R12)
X0 = (RW - TW) / 2

# tray part groups (must match parts.js `nodes`)
TRAY_GROUPS = {
    "bf3": ["bf3", "bf3_front"], "osfp": ["osfp_front", "osfp_header"], "lom": ["lom"], "bmcport": ["bmc_port"],
    "tag": ["luggage_tag"], "serial": ["serial_usb"], "dp": ["displayport"], "nvme": ["nvme", "nvme_inside"],
    "cpanel": ["control_panel"], "fio": ["front_io"], "cmos": ["cmos"], "backplane": ["backplane"], "m2": ["m2"],
    "hmc": ["hmc"], "slimline": ["slimline"], "tpm": ["tpm"], "fans": ["fans"], "interposer": ["interposer_bmc"],
    "pdb": ["pdb"], "ipex": ["ipex"], "busbar": ["busbar"], "bianca": ["bianca0", "bianca1"],
    "gpu": ["gpus", "gpus1", "coldplate00", "coldplate01", "coldplate10", "coldplate11"], "cpu": ["cpu_mem", "cpu_mem1"],
    "mezz": ["cx_mezz", "cx_mezz1"], "manifold": ["manifold", "manifold1"], "leak00": ["leak_M0_0"],
    "leak01": ["leak_M0_1"], "leak10": ["leak_M1_0"], "leak11": ["leak_M1_1"], "rails": ["rails", "rails_r"],
    "handles": ["handles"],
}
TRAY_ID = {g: i + 1 for i, g in enumerate(TRAY_GROUPS)}
TRAY_ID.update({"busbar_back": 201, "busbar_front": 202, "busbar_middle": 203})
NODE2G = {n: g for g, ns in TRAY_GROUPS.items() for n in ns}

sc = None
M = None


# ------------------------------------------------------------------ small helpers
def col(name, parent=None):
    c = bpy.data.collections.new(name)
    (parent or sc.collection).children.link(c)
    return c


def pmat(name, color, rough=0.5, metallic=0.0, emit=0.0, alpha=1.0, coat=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*color, 1)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metallic
    if emit:
        b.inputs["Emission Color"].default_value = (*color, 1)
        b.inputs["Emission Strength"].default_value = emit
    if coat:
        b.inputs["Coat Weight"].default_value = coat
        b.inputs["Coat Roughness"].default_value = 0.08
    if alpha < 1:
        b.inputs["Alpha"].default_value = alpha
        b.inputs["Transmission Weight"].default_value = 1 - alpha
    return m


def text(name, body, size, loc, rot, material, coll, extrude=0.001, align="CENTER"):
    cu = bpy.data.curves.new(name, "FONT")
    cu.body = body
    cu.size = size
    cu.extrude = extrude
    cu.align_x = align
    cu.align_y = "CENTER"
    cu.materials.append(material)
    o = bpy.data.objects.new(name, cu)
    o.location = loc
    o.rotation_euler = rot
    coll.objects.link(o)
    return o


def root_of(o):
    while o.parent:
        o = o.parent
    return o


def chain(o):
    out = []
    while o:
        out.append(o.name.split(".")[0])
        o = o.parent
    return out


# ------------------------------------------------------------------ rack detail
def detail_rack(rack, coll, m, cm, placard=None):
    """Front fiber and DAC runs, side cable managers, rear coolant hoses, optional placard."""
    kids = {c.name.split(".")[0]: c for c in rack.children}
    d = bm.empty("DETAIL", coll, rack)
    for x in (0.03, RW - 0.03):
        bm.box("cablemgr", (0.05, 0.045, RH - 0.2), (x, -0.028, RH / 2), m["black"], coll, d, 0.004)
    # vertical bundles rising into the raceway
    for x, mat in ((0.034, cm["purple"]), (RW - 0.034, cm["aqua"])):
        bm.tube("bundle", [(x, -0.062, 0.45), (x, -0.066, 1.4), (x, -0.07, RH - 0.05), (x, -0.1, RH + 0.14), (x, -0.16, RH + 0.2)],
                0.011, mat, coll, d)
    for name, o in kids.items():
        z = o.location.z
        if name.startswith("CT"):
            for i in range(4):          # OSFP -> right manager (aqua fiber)
                px = X0 + 0.385 + i * 0.03
                bm.tube("fib", [(px, 0.04, z + 0.022), (px + 0.004, -0.03 - 0.004 * i, z + 0.022),
                                (RW - 0.075, -0.05 - 0.004 * i, z + 0.026), (RW - 0.04, -0.062, z + 0.07)],
                        0.0026, cm["aqua"], coll, d)
            for i in range(2):          # BF3 -> left manager (purple DAC)
                px = X0 + 0.062 + i * 0.032
                bm.tube("dac", [(px, 0.04, z + 0.03), (px - 0.004, -0.032 - 0.005 * i, z + 0.03),
                                (0.08, -0.05 - 0.005 * i, z + 0.034), (0.04, -0.062, z + 0.08)],
                        0.0034, cm["purple"], coll, d)
            bm.tube("cat6", [(X0 + 0.086, 0.04, z + 0.012), (X0 + 0.08, -0.028, z + 0.012), (0.085, -0.044, z + 0.014),
                             (0.045, -0.058, z + 0.05)], 0.0024, cm["blue"], coll, d)
            # rear coolant hoses (supply left, return right)
            for x, tx, mat in ((0.065, X0 + 0.11, cm["hose_b"]), (RW - 0.065, X0 + TW - 0.11, cm["hose_r"])):
                bm.tube("hose", [(x, RD - 0.115, z + 0.024), ((x + tx) / 2, RD - 0.16, z + 0.03), (tx, RD - 0.2, z + 0.024)],
                        0.0075, mat, coll, d)
        elif name.startswith("SW"):
            for i in range(2):
                px = X0 + 0.44 + i * 0.03
                bm.tube("swfib", [(px, 0.04, z + 0.022), (px, -0.03, z + 0.022), (RW - 0.08, -0.048, z + 0.026),
                                  (RW - 0.04, -0.06, z + 0.06)], 0.0024, cm["yellow"], coll, d)
    # top-of-rack management switches (2U) so the rack is full to the top
    for k in range(2):
        z = 0.085 + OU * 41 + k * OU
        bm.box("tor", (TW, 0.5, TH), (RW / 2, 0.31, z + TH / 2), m["dark"], coll, d)
        bm.box("torface", (TW, 0.006, TH), (RW / 2, 0.056, z + TH / 2), m["black"], coll, d, 0.0015)
        for i in range(24):
            bm.box("torport", (0.012, 0.004, 0.011), (X0 + 0.04 + i * 0.019, 0.052, z + TH * 0.5), m["port"], coll, d)
            if i % 3 == 0:
                bm.box("torled", (0.003, 0.002, 0.003), (X0 + 0.04 + i * 0.019, 0.051, z + TH * 0.86), m["led_g"], coll, d)
    if placard:
        bm.box("placard", (0.2, 0.004, 0.07), (RW / 2, -0.004, RH - 0.06), cm["plate"], coll, d, 0.002)
        text("placard_txt", placard, 0.05, (RW / 2, -0.0075, RH - 0.06), (math.pi / 2, 0, 0), cm["white"], coll)


def detail_tray(root, coll, m, cm):
    """Small components that make the open tray read as real hardware."""
    d = bm.empty("TDETAIL", coll, root)
    for idx, x0 in enumerate((0.02, 0.02 + 0.245 + 0.025)):
        w, dd, y0 = 0.245, 0.33, 0.425
        for g in range(2):
            gx = x0 + w * (0.27 + 0.46 * g)
            gy = y0 + dd * 0.66
            for k in range(6):          # VRM inductors each side of a GPU
                for s in (-1, 1):
                    bm.box("vrm", (0.011, 0.011, 0.007), (gx + s * 0.056, gy - 0.036 + k * 0.0145, 0.0115), cm["ferrite"], coll, d, 0.001)
            for k in range(10):         # MLCC field below the GPU
                bm.box("mlcc", (0.004, 0.002, 0.002), (gx - 0.03 + k * 0.0066, gy - 0.056, 0.009), cm["mlcc"], coll, d)
        for k in range(5):
            bm.box("vrmc", (0.011, 0.011, 0.007), (x0 + w * 0.5 - 0.03 + k * 0.015, y0 + dd * 0.26 - 0.046, 0.0115), cm["ferrite"], coll, d, 0.001)
        for sx in (0.012, w - 0.012):
            for sy in (0.012, dd * 0.5, dd - 0.012):
                bm.cyl("standoff", 0.003, 0.004, (x0 + sx, y0 + sy, 0.01), m["zinc"], coll, d, "Z", 8)
    for loc in ((0.27, 0.335, 0.0345), (0.075, 0.145, 0.036), (0.482, 0.14, 0.0318)):   # stickers
        bm.box("sticker", (0.03, 0.014, 0.0004), loc, cm["white"], coll, d)
    for k in range(6):
        bm.cyl("cap", 0.004, 0.011, (0.36 + k * 0.012, 0.295, 0.0145), m["dark"], coll, d, "Z", 10)
    for x in (0.2, 0.34):               # PDB power leads to the Bianca boards
        bm.tube("pwr", [(x, 0.39, 0.016), (x, 0.42, 0.022), (x + (0.06 if x > 0.27 else -0.06), 0.47, 0.014)], 0.0045, cm["hose_r"], coll, d)
        bm.tube("pwr", [(x + 0.012, 0.39, 0.016), (x + 0.012, 0.42, 0.022), (x + 0.012 + (0.06 if x > 0.27 else -0.06), 0.47, 0.014)],
                0.0045, m["black"], coll, d)


# ------------------------------------------------------------------ hall
def build_hall(hall, n_coll, m, cm):
    rw = RW
    xs = [k * rw for k in ROW]
    x_lo, x_hi = xs[0] - 0.9, xs[-1] + rw + 0.4

    def inst(loc, rotz=0.0):
        e = bpy.data.objects.new("rackinst", None)
        e.instance_type = "COLLECTION"
        e.instance_collection = n_coll
        e.location = loc
        e.rotation_euler = (0, 0, rotz)
        hall.objects.link(e)

    yb = -AISLE                    # row B fronts
    yc = RD + HOT                  # row C rears
    for i, k in enumerate(ROW):
        x = k * rw
        if k != 0:
            inst((x, 0, 0))
            lab = f"R{12 + k:02d}"
            bm.box("placard", (0.2, 0.004, 0.07), (x + rw / 2, -0.004, RH - 0.06), cm["plate"], hall, None, 0.002)
            text("ptxt", lab, 0.05, (x + rw / 2, -0.0075, RH - 0.06), (math.pi / 2, 0, 0), cm["white"], hall)
        inst((x + rw, yb, 0), math.pi)
        inst((x + rw, yc + RD, 0), math.pi)
        bm.box("placard", (0.2, 0.004, 0.07), (x + rw / 2, yb + 0.004, RH - 0.06), cm["plate"], hall, None, 0.002)
        text("ptxt", f"Q{12 + k:02d}", 0.05, (x + rw / 2, yb + 0.0075, RH - 0.06), (math.pi / 2, 0, math.pi), cm["white"], hall)

    # in-row CDUs at the west end of each row
    for y, rot in ((0, 0), (yb - RD, 0), (yc, 0)):
        cx = x_lo + 0.45
        bm.box("cdu", (0.85, RD, RH), (cx, y + RD / 2, RH / 2), cm["cdu"], hall, None, 0.006)
        fy = y - 0.004 if y == 0 else (y + RD + 0.004 if y < 0 else y - 0.004)
        bm.box("cdu_screen", (0.26, 0.006, 0.16), (cx, fy, 1.55), cm["screen"], hall, None, 0.002)
        bm.box("cdu_vent", (0.6, 0.006, 0.9), (cx, fy, 0.65), m["dark"], hall, None, 0.002)
        for dx, mat in ((-0.2, cm["pipe_b"]), (0.2, cm["pipe_r"])):
            bm.cyl("cdu_riser", 0.055, 0.75, (cx + dx, y + RD - 0.25, RH + 0.37), mat, hall, None, "Z", 24)

    # floor: polished tiles + safety tape
    L = x_hi - x_lo + 8
    fl = bm.box("floor", (L, 16, 0.02), ((x_lo + x_hi) / 2, 0, -0.01), cm["floor"], hall)
    for y in (-0.1, yb + 0.1, RD + 0.08, yc - 0.08):
        bm.box("tape", (x_hi - x_lo, 0.05, 0.0006), ((x_lo + x_hi) / 2, y, 0.0004), cm["tape"], hall)
    text("floor_txt", "COLD AISLE  C", 0.16, (3.2, -AISLE / 2, 0.001), (0, 0, 0), cm["floortext"], hall, 0.0003)
    text("floor_txt2", "HOT AISLE  C / D   AUTHORIZED PERSONNEL", 0.1, (3.2, RD + HOT / 2, 0.001), (0, 0, 0), cm["floortext"], hall, 0.0003)

    # ceiling + continuous linear LED fixtures
    bm.box("ceiling", (L, 16, 0.05), ((x_lo + x_hi) / 2, 0, 3.72), cm["ceiling"], hall)
    for y in (-AISLE / 2, RD + HOT / 2, yb - RD - 0.9, yc + RD + 0.9):
        x = x_lo - 2
        while x < x_hi + 2:
            bm.box("led_fixture", (2.3, 0.1, 0.03), (x + 1.15, y, 3.42), cm["fixture"], hall)
            bm.box("led_body", (2.36, 0.16, 0.05), (x + 1.15, y, 3.455), cm["plate"], hall)
            x += 2.5
    x = x_lo - 1                              # hot aisle: pendant line below the coolant mains
    while x < x_hi + 1:
        bm.box("led_fixture", (1.8, 0.08, 0.02), (x + 0.9, RD + HOT / 2, 2.6), cm["fixture"], hall)
        bm.box("led_body", (1.86, 0.12, 0.04), (x + 0.9, RD + HOT / 2, 2.63), cm["plate"], hall)
        x += 2.0
    for x in (x_lo - 2.5, x_hi + 2.5):      # end walls with an accent stripe
        bm.box("wall", (0.1, 16, 3.8), (x, 0, 1.9), cm["wall"], hall)
        bm.box("stripe", (0.11, 16, 0.12), (x, 0, 1.15), cm["accent"], hall)
    for y in (-7.6, 7.6):
        bm.box("wall", (L, 0.1, 3.8), ((x_lo + x_hi) / 2, y, 1.9), cm["wall"], hall)
    ex = x_hi + 2.44                         # exit door + sign on the east wall
    bm.box("door", (0.04, 1.0, 2.1), (ex, -AISLE / 2, 1.05), cm["door"], hall, None, 0.004)
    bm.box("exit", (0.03, 0.34, 0.14), (ex, -AISLE / 2, 2.32), cm["exit"], hall, None, 0.003)

    # overhead: fiber raceway, ladder tray, power busway with tap boxes, coolant mains, sprinkler line
    for y in (-0.16, yb + 0.16):
        bm.box("raceway", (x_hi - x_lo, 0.11, 0.1), ((x_lo + x_hi) / 2, y, RH + 0.26), cm["raceway"], hall, None, 0.006)
    for y in (0.5, yb - 0.5, yc + 0.6):
        for dy in (-0.15, 0.15):
            bm.box("ladder_rail", (x_hi - x_lo, 0.012, 0.05), ((x_lo + x_hi) / 2, y + dy, RH + 0.52), m["zinc"], hall)
        x = x_lo
        while x < x_hi:
            bm.box("rung", (0.012, 0.3, 0.012), (x, y, RH + 0.5), m["zinc"], hall)
            x += 0.3
        bm.box("cable_mass", (x_hi - x_lo, 0.2, 0.05), ((x_lo + x_hi) / 2, y, RH + 0.545), cm["cablemass"], hall, None, 0.01)
    for y in (0.86, yb - 0.86, yc + 0.24):
        bm.box("busway", (x_hi - x_lo, 0.11, 0.09), ((x_lo + x_hi) / 2, y, RH + 0.78), cm["busway"], hall, None, 0.004)
        for k in ROW:
            x = k * rw + rw / 2
            bm.box("tap", (0.2, 0.16, 0.2), (x, y, RH + 0.66), cm["tapbox"], hall, None, 0.006)
            bm.box("tap_led", (0.012, 0.004, 0.012), (x - 0.06, y - 0.082 if y > yb else y + 0.082, RH + 0.7), m["led_g"], hall)
            bm.tube("whip", [(x + 0.05, y, RH + 0.56), (x + 0.07, y - 0.02, RH + 0.3), (x + 0.06, y - 0.03, RH + 0.02)],
                    0.011, m["black"], hall)
    for row_y, sgn in ((RD, 1), (yc, -1)):                 # one supply + return pair per row
        for i, band in enumerate((cm["pipe_b"], cm["pipe_r"])):
            y = row_y + sgn * (0.2 + 0.2 * i)
            z = 2.86 + 0.16 * i
            bm.cyl("main", 0.075, x_hi - x_lo + 1.5, ((x_lo + x_hi) / 2, y, z), cm["pipe"], hall, None, "X", 36)
            x = x_lo
            while x < x_hi:
                bm.cyl("band", 0.077, 0.12, (x, y, z), band, hall, None, "X", 36)
                x += 1.86
            for k in ROW:
                left = (i == 0) == (sgn == 1)
                mx = k * rw + (0.065 if left else RW - 0.065)
                ry = row_y - sgn * 0.07
                bm.tube("branch", [(mx, y, z - 0.06), (mx, (y + ry) / 2, 2.66), (mx, ry, 2.5), (mx, ry, RH - 0.12)], 0.02, band, hall)
    bm.cyl("sprinkler", 0.018, x_hi - x_lo + 2, ((x_lo + x_hi) / 2, -AISLE / 2 + 0.5, 3.55), cm["firered"], hall, None, "X", 16)

    # service cart with a laptop, next to R12
    cx, cy = -1.25, -1.15
    c = bm.empty("CART", hall)
    bm.box("cart_top", (0.75, 0.5, 0.025), (cx, cy, 0.92), m["steel"], hall, c, 0.004)
    bm.box("cart_mat", (0.68, 0.44, 0.004), (cx, cy, 0.935), cm["esd"], hall, c)
    bm.box("cart_shelf", (0.75, 0.5, 0.02), (cx, cy, 0.3), m["steel"], hall, c, 0.004)
    for sx in (-0.35, 0.35):
        for sy in (-0.23, 0.23):
            bm.cyl("cart_leg", 0.014, 0.9, (cx + sx, cy + sy, 0.47), m["steel"], hall, c, "Z", 12)
            bm.cyl("cart_wheel", 0.04, 0.025, (cx + sx, cy + sy, 0.04), m["black"], hall, c, "X", 18)
    bm.box("laptop_base", (0.32, 0.22, 0.014), (cx - 0.12, cy, 0.944), m["dark"], hall, c, 0.003)
    scr = bm.box("laptop_lid", (0.32, 0.01, 0.21), (cx - 0.12, cy + 0.125, 1.05), m["dark"], hall, c, 0.003)
    scr.rotation_euler = (math.radians(-12), 0, 0)
    s2 = bm.box("laptop_screen", (0.295, 0.002, 0.185), (cx - 0.12, cy + 0.118, 1.05), cm["screen"], hall, c)
    s2.rotation_euler = (math.radians(-12), 0, 0)
    bm.box("toolcase", (0.3, 0.2, 0.12), (cx + 0.2, cy, 0.37), cm["accent"], hall, c, 0.01)


def materials_extra():
    return dict(
        aqua=pmat("fiber_aqua", (0.0, 0.42, 0.5), 0.32), purple=pmat("dac_purple", (0.2, 0.05, 0.36), 0.35),
        blue=pmat("cat6_blue", (0.02, 0.16, 0.7), 0.4), yellow=pmat("fiber_yellow", (0.95, 0.7, 0.02), 0.35),
        hose_b=pmat("hose_blue", (0.01, 0.05, 0.22), 0.55), hose_r=pmat("hose_red", (0.3, 0.01, 0.01), 0.55),
        plate=pmat("placard", (0.03, 0.032, 0.036), 0.4, 0.6), white=pmat("white_print", (0.92, 0.92, 0.9), 0.5),
        ferrite=pmat("ferrite", (0.07, 0.07, 0.075), 0.6), mlcc=pmat("mlcc", (0.55, 0.42, 0.25), 0.5),
        cdu=pmat("cdu_white", (0.82, 0.83, 0.85), 0.35, 0.2), screen=pmat("screen", (0.05, 0.5, 0.75), 0.2, 0.0, 2.2),
        floor=pmat("floor_tile", (0.56, 0.57, 0.59), 0.14), tape=pmat("tape_yellow", (0.95, 0.72, 0.02), 0.45),
        floortext=pmat("floor_text", (0.9, 0.9, 0.9), 0.5), ceiling=pmat("ceiling_white", (0.78, 0.78, 0.78), 0.9),
        fixture=pmat("fixture", (1.0, 0.98, 0.95), 0.5, 0.0, 30.0), wall=pmat("wall_white", (0.74, 0.75, 0.76), 0.6),
        accent=pmat("accent_blue", (0.02, 0.12, 0.45), 0.4), door=pmat("door", (0.3, 0.31, 0.33), 0.4, 0.6),
        exit=pmat("exit_sign", (0.05, 0.9, 0.25), 0.4, 0.0, 6.0), raceway=pmat("raceway_yellow", (0.93, 0.68, 0.02), 0.4),
        cablemass=pmat("cable_mass", (0.02, 0.05, 0.12), 0.6), busway=pmat("busway", (0.55, 0.56, 0.58), 0.35, 0.8),
        tapbox=pmat("tapbox", (0.12, 0.125, 0.13), 0.45, 0.4), pipe=pmat("pipe_insul", (0.8, 0.81, 0.82), 0.45, 0.3),
        pipe_b=pmat("pipe_blue", (0.03, 0.2, 0.75), 0.35, 0.2), pipe_r=pmat("pipe_red", (0.75, 0.05, 0.04), 0.35, 0.2),
        firered=pmat("fire_red", (0.7, 0.03, 0.02), 0.35, 0.3), esd=pmat("esd_mat", (0.02, 0.09, 0.2), 0.7),
    )


def enrich():
    """Surface detail for Cycles: fingerprints on metal, traces on boards, uneven floor gloss."""
    for mt in bpy.data.materials:
        if not mt.use_nodes:
            continue
        nt = mt.node_tree
        b = nt.nodes.get("Principled BSDF")
        if b is None:
            continue
        n = mt.name
        if n in ("steel", "aluminum", "zinc", "dark_metal", "rack_frame", "copper", "busway", "cdu_white", "cabinet_white", "chrome"):
            tex = nt.nodes.new("ShaderNodeTexNoise")
            tex.inputs["Scale"].default_value = 260
            tex.inputs["Detail"].default_value = 9
            bump = nt.nodes.new("ShaderNodeBump")
            bump.inputs["Strength"].default_value = 0.03
            nt.links.new(tex.outputs["Fac"], bump.inputs["Height"])
            nt.links.new(bump.outputs["Normal"], b.inputs["Normal"])
            t2 = nt.nodes.new("ShaderNodeTexNoise")
            t2.inputs["Scale"].default_value = 9
            mr = nt.nodes.new("ShaderNodeMapRange")
            base = b.inputs["Roughness"].default_value
            mr.inputs["To Min"].default_value = max(0.05, base - 0.1)
            mr.inputs["To Max"].default_value = min(1.0, base + 0.14)
            nt.links.new(t2.outputs["Fac"], mr.inputs["Value"])
            nt.links.new(mr.outputs["Result"], b.inputs["Roughness"])
        if n in ("pcb", "pcb_black"):
            if n == "pcb":
                b.inputs["Base Color"].default_value = (0.004, 0.05, 0.022, 1)
            br = nt.nodes.new("ShaderNodeTexBrick")
            br.inputs["Scale"].default_value = 420
            br.inputs["Mortar Size"].default_value = 0.08
            bump = nt.nodes.new("ShaderNodeBump")
            bump.inputs["Strength"].default_value = 0.12
            nt.links.new(br.outputs["Fac"], bump.inputs["Height"])
            nt.links.new(bump.outputs["Normal"], b.inputs["Normal"])
            b.inputs["Coat Weight"].default_value = 0.6
            b.inputs["Coat Roughness"].default_value = 0.12
        if n == "floor_tile":
            co = nt.nodes.new("ShaderNodeTexCoord")
            br = nt.nodes.new("ShaderNodeTexBrick")
            br.offset = 0.0
            br.inputs["Scale"].default_value = 1.0
            br.inputs["Mortar Size"].default_value = 0.003
            br.inputs["Brick Width"].default_value = 0.6
            br.inputs["Row Height"].default_value = 0.6
            br.inputs["Color1"].default_value = (0.54, 0.55, 0.57, 1)
            br.inputs["Color2"].default_value = (0.6, 0.61, 0.63, 1)
            br.inputs["Mortar"].default_value = (0.1, 0.1, 0.1, 1)
            nt.links.new(co.outputs["Object"], br.inputs["Vector"])
            nt.links.new(br.outputs["Color"], b.inputs["Base Color"])
            bump = nt.nodes.new("ShaderNodeBump")
            bump.inputs["Strength"].default_value = 0.25
            bump.invert = True
            nt.links.new(br.outputs["Fac"], bump.inputs["Height"])
            nt.links.new(bump.outputs["Normal"], b.inputs["Normal"])
            t2 = nt.nodes.new("ShaderNodeTexNoise")
            t2.inputs["Scale"].default_value = 1.6
            t2.inputs["Detail"].default_value = 6
            mr = nt.nodes.new("ShaderNodeMapRange")
            mr.inputs["To Min"].default_value = 0.04
            mr.inputs["To Max"].default_value = 0.17
            nt.links.new(co.outputs["Object"], t2.inputs["Vector"])
            nt.links.new(t2.outputs["Fac"], mr.inputs["Value"])
            nt.links.new(mr.outputs["Result"], b.inputs["Roughness"])


# ------------------------------------------------------------------ build everything
def build():
    global sc, M
    bm.reset()
    bm.MATS.clear()
    sc = bpy.context.scene
    M = bm.M()
    cm = materials_extra()
    c_r12 = col("r12")
    c_n = col("rack_n")
    c_hall = col("hall")
    c_tray = col("tray")
    r12 = bm.build_rack(c_r12, M)
    detail_rack(r12, c_r12, M, cm, "R12")
    rn = bm.build_rack(c_n, M)
    rn.name = "RACKN"
    detail_rack(rn, c_n, M, cm)
    for o in list(c_n.all_objects):          # neighbours carry no quiz stickers
        if o.name.startswith("TAG_"):
            bpy.data.objects.remove(o)
    build_hall(c_hall, c_n, M, cm)
    tray, _ = bm.build_tray(c_tray, M, "TRAY")
    detail_tray(tray, c_tray, M, cm)
    lid = bpy.data.objects.get("PART_lid")
    for o in list(lid.children_recursive) + [lid]:
        bpy.data.objects.remove(o)
    # hide the source of the neighbour instances, keep the instances
    def excl(lc):
        for ch in lc.children:
            if ch.collection == c_n:
                ch.exclude = True
            excl(ch)
    excl(bpy.context.view_layer.layer_collection)
    enrich()
    return dict(r12=c_r12, n=c_n, hall=c_hall, tray=c_tray, rack=r12, trayroot=tray, cm=cm)


def cycles(samples, w, h, denoise=True):
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
    sc.cycles.use_denoising = denoise
    if denoise:
        try:
            sc.cycles.denoiser = "OPTIX"
        except Exception:
            pass
    sc.cycles.max_bounces = 8
    sc.cycles.filter_width = 1.5
    sc.render.resolution_x, sc.render.resolution_y = w, h
    sc.render.resolution_percentage = 100
    sc.view_settings.view_transform = "AgX"
    sc.view_settings.look = "AgX - Medium High Contrast"
    sc.view_settings.exposure = 0.0


def world(strength, color=(0.6, 0.65, 0.7)):
    w = sc.world or bpy.data.worlds.new("w")
    w.use_nodes = True
    sc.world = w
    bg = w.node_tree.nodes["Background"]
    bg.inputs[0].default_value = (*color, 1)
    bg.inputs[1].default_value = strength


def camera(loc, target, lens=24, pano=False):
    c = bpy.data.cameras.new("cam")
    c.lens = lens
    if pano:
        c.type = "PANO"
        c.panorama_type = "EQUIRECTANGULAR"
    o = bpy.data.objects.new("cam", c)
    sc.collection.objects.link(o)
    o.location = loc
    d = Vector(target) - Vector(loc)
    o.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    sc.camera = o
    return o


def save(path, fmt="JPEG", q=92):
    sc.render.image_settings.file_format = fmt
    if fmt == "JPEG":
        sc.render.image_settings.quality = q
    else:
        sc.render.image_settings.color_mode = "RGB"
        sc.render.image_settings.compression = 60
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)
    print("rendered", os.path.basename(path), flush=True)


# ------------------------------------------------------------------ ID pass
ID_MATS = {}


def id_mat(i):
    if i not in ID_MATS:
        mt = bpy.data.materials.new(f"ID{i}")
        mt.use_nodes = True
        nt = mt.node_tree
        nt.nodes.clear()
        e = nt.nodes.new("ShaderNodeEmission")
        e.inputs["Color"].default_value = (i / 255.0, 0, 0, 1)
        o = nt.nodes.new("ShaderNodeOutputMaterial")
        nt.links.new(e.outputs[0], o.inputs[0])
        ID_MATS[i] = mt
    return ID_MATS[i]


def rack_id(o):
    ch = chain(o)
    top = ch[-2] if len(ch) >= 2 and ch[-1] == "RACK" else None
    if not top:
        return 0
    name = ch[0]
    if top.startswith("CT"):
        n = int(top[2:4])
        if "PART_luggage_tag" in ch:
            return 100 + n
        if name.startswith("LED_power"):
            return 140 + n
        if name.startswith("LED_drive"):
            return 160 + n
        return n
    if top.startswith("SW"):
        n = int(top[2])
        if "PART_luggage_tag" in ch:
            return 120 + n
        if name.startswith("LED_status"):
            return 180 + n
        return 18 + n
    if top.startswith("PT"):
        return 27 + int(top[2])
    if top.startswith("INV"):
        return 35 + int(top[3])
    if top.startswith("CAP"):
        return 38
    if top.startswith("CC"):
        return 38 + int(top[2])
    if top.startswith("PART_rack_busbar"):
        return 43
    if top.startswith("PART_rack_manifold"):
        return 44
    if top.startswith("PART_rack_frame"):
        return 45
    if top.startswith("TAG_rack_back"):
        return 46
    if top.startswith("TAG_rack_top"):
        return 47
    if top.startswith("TAG_rack_front"):
        return 48
    if top.startswith("TAG_cartridge"):
        return 49
    if top.startswith("TAG_power"):
        return 50
    return 0


def tray_id(o):
    ch = chain(o)
    if ch[-1] != "TRAY":
        return 0
    if ch[0].startswith("busbar_screw_"):
        return TRAY_ID["busbar_" + ch[0].split("_")[2].rstrip("01")]
    for n in ch:
        if n.startswith("PART_"):
            g = NODE2G.get(n[5:])
            if g:
                return TRAY_ID[g]
    return 0


def id_pass(fn):
    """Swap every material for a flat ID colour; returns a function that restores them."""
    saved = []
    for o in bpy.data.objects:
        if o.type not in ("MESH", "CURVE", "FONT") or not o.data.materials:
            continue
        saved.append((o.data, list(o.data.materials)))
    done = set()
    for o in bpy.data.objects:
        if o.type not in ("MESH", "CURVE", "FONT"):
            continue
        key = o.data.name
        i = fn(o)
        if key in done and i == 0:
            continue
        if i and o.data.users > 1:
            o.data = o.data.copy()          # linked duplicates need their own ID
        mt = id_mat(i)
        o.data.materials.clear()
        o.data.materials.append(mt)
        done.add(key)
    sc.cycles.samples = 1
    sc.cycles.use_denoising = False
    sc.cycles.filter_width = 0.01
    sc.cycles.max_bounces = 0
    sc.view_settings.view_transform = "Raw"
    sc.view_settings.look = "None"
    sc.view_settings.exposure = 0.0
    sc.render.dither_intensity = 0.0      # dithering would nudge ID values
    for o in bpy.data.objects:
        if o.type == "LIGHT":
            o.hide_render = True
    world(0.0, (0, 0, 0))
    return saved


def leds_off(coll):
    """R12's own LEDs are dark in the beauty render: the web app lights them from live lab state."""
    off = bm.MATS["led_off"]
    for o in coll.all_objects:
        if o.type == "MESH" and o.name.startswith("LED_"):
            o.data = o.data.copy()
            o.data.materials.clear()
            o.data.materials.append(off)


STATIONS = {
    "front": ((RW / 2, -1.85, 1.5), "Cold aisle, facing R12"),
    "rear": ((RW / 2, RD + 1.05, 1.45), "Hot aisle, behind R12"),
    "aisle": ((5.2, -AISLE / 2, 1.62), "Cold aisle C entrance"),
}


def hall_visible(S, tray_on=False):
    for o in S["tray"].all_objects:
        o.hide_render = not tray_on


# ------------------------------------------------------------------ shots
def shot_test(S):
    hall_visible(S)
    cycles(48, 1280, 720)
    world(0.02)
    for name, loc, tgt, lens in (("front", (RW / 2 + 0.9, -2.2, 1.55), (RW / 2, 0, 1.2), 20),
                                 ("aisle", (5.2, -AISLE / 2, 1.62), (0, -AISLE / 2 + 0.3, 1.3), 24),
                                 ("rear", (RW / 2 + 0.2, RD + 1.2, 1.45), (RW / 2, RD, 1.2), 16)):
        camera(loc, tgt, lens)
        save(os.path.join(REN, f"v2_{name}.jpg"))


def shot_panos(S, samples):
    hall_visible(S)
    leds_off(S["r12"])
    world(0.02)
    for name, (loc, _) in STATIONS.items():
        cycles(samples, 8192, 4096)
        camera(loc, (loc[0] + 5, loc[1], loc[2]), 18, True)
        save(os.path.join(IMG, f"pano_{name}.jpg"), "JPEG", 90)
    saved = id_pass(rack_id)
    for name, (loc, _) in STATIONS.items():
        sc.render.resolution_x, sc.render.resolution_y = 4096, 2048
        camera(loc, (loc[0] + 5, loc[1], loc[2]), 18, True)
        save(os.path.join(IMG, f"pano_{name}_id.png"), "PNG")
    return saved


TRAY_FRAMES = 24


def shot_tray(S, samples):
    """Tray on an ESD bench, lit by the hall: an orbit of frames plus one from straight above."""
    for c in ("r12", "hall"):
        for o in S[c].all_objects:
            o.hide_render = True
    for o in S["tray"].all_objects:
        o.hide_render = False
    cx, cy = TW / 2, TD / 2
    bm.box("bench_top", (1.5, 1.7, 0.04), (cx, cy, -0.022), bm.MATS["steel"], sc.collection)
    bm.box("bench_mat", (1.25, 1.45, 0.004), (cx, cy, -0.001), S["cm"]["esd"], sc.collection)
    for i, (x, y, z, p) in enumerate(((cx, cy, 1.9, 900), (cx - 1.4, cy - 0.6, 1.2, 260), (cx + 1.5, cy + 0.9, 1.0, 220))):
        l = bpy.data.lights.new("bench_light", "AREA")
        l.size = 1.6 if i == 0 else 0.9
        l.energy = p
        l.color = (1, 1, 1) if i == 0 else ((0.78, 0.87, 1.0) if i == 1 else (1.0, 0.86, 0.7))
        o = bpy.data.objects.new("bench_light", l)
        sc.collection.objects.link(o)
        o.location = (x, y, z)
        o.rotation_euler = (Vector((cx, cy, 0)) - Vector((x, y, z))).to_track_quat("-Z", "Y").to_euler()
    world(0.35, (0.5, 0.55, 0.62))
    cams = []
    for k in range(TRAY_FRAMES):
        a = -math.pi / 2 + k * 2 * math.pi / TRAY_FRAMES
        cams.append(((cx + 1.02 * math.cos(a), cy + 1.02 * math.sin(a), 0.78), (cx, cy, 0.01), 50))
    cams.append(((cx, cy - 0.001, 1.42), (cx, cy, 0.0), 50))
    cycles(samples, 1920, 1080)
    sc.view_settings.exposure = -0.4
    for k, (loc, tgt, lens) in enumerate(cams):
        camera(loc, tgt, lens)
        save(os.path.join(IMG, f"tray_{k:02d}.jpg"), "JPEG", 90)
    saved = id_pass(tray_id)
    for k, (loc, tgt, lens) in enumerate(cams):
        sc.render.resolution_x, sc.render.resolution_y = 1920, 1080
        camera(loc, tgt, lens)
        save(os.path.join(IMG, f"tray_{k:02d}_id.png"), "PNG")
    return saved


def shot_fly(S, samples, n):
    hall_visible(S)
    cycles(samples, 1920, 1080)
    world(0.02)
    c = camera((7.2, -AISLE / 2, 1.7), (0, -AISLE / 2 + 0.2, 1.35), 22)
    tgt = bpy.data.objects.new("tgt", None)
    sc.collection.objects.link(tgt)
    con = c.constraints.new("TRACK_TO")
    con.target = tgt
    con.track_axis = "TRACK_NEGATIVE_Z"
    con.up_axis = "UP_Y"
    keys = ((1, (7.2, -AISLE / 2, 1.7), (0.0, -AISLE / 2 + 0.2, 1.35)),
            (int(n * 0.6), (2.6, -AISLE / 2 - 0.2, 1.6), (0.31, -0.2, 1.3)),
            (n, (RW / 2 + 0.55, -1.75, 1.5), (RW / 2, 0.0, 1.22)))
    for f, loc, t in keys:
        c.location = loc
        c.keyframe_insert("location", frame=f)
        tgt.location = t
        tgt.keyframe_insert("location", frame=f)
    sc.frame_start, sc.frame_end = 1, n
    sc.render.image_settings.file_format = "JPEG"
    sc.render.image_settings.quality = 92
    os.makedirs(os.path.join(REN, "fly2"), exist_ok=True)
    sc.render.filepath = os.path.join(REN, "fly2", "f_")
    bpy.ops.render.render(animation=True)


def manifest():
    data = {"stations": {k: {"title": v[1], "pos": v[0]} for k, v in STATIONS.items()}, "tray_frames": TRAY_FRAMES + 1,
            "tray_top": TRAY_FRAMES, "tray_ids": TRAY_ID}
    with open(os.path.join(IMG, "manifest.json"), "w") as f:
        json.dump(data, f, indent=1)


def main():
    what = sys.argv[1] if len(sys.argv) > 1 else "test"
    samples = int(sys.argv[2]) if len(sys.argv) > 2 else 128
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 180
    # each pass rebuilds the scene: an ID pass rewrites every material
    jobs = {"test": [shot_test], "panos": [lambda S: shot_panos(S, samples)], "tray": [lambda S: shot_tray(S, samples)],
            "fly": [lambda S: shot_fly(S, samples, n)],
            "all": [lambda S: shot_panos(S, samples), lambda S: shot_tray(S, samples), lambda S: shot_fly(S, 64, n)]}[what]
    for job in jobs:
        S = build()
        job(S)
    manifest()
    print("DONE", what, flush=True)


if __name__ == "__main__":
    main()
