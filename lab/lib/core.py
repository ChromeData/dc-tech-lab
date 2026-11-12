"""Shared rack model for the DC tech lab.

Every lab tool (ipmitool, tech, ezbmc, dclab, bmcd) reads and writes one JSON
state file, so a change made with one tool shows up in all the others.
"""
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import time

LAB = os.environ.get("DCLAB_HOME") or os.path.join(os.path.expanduser("~"), "dclab")
STATE_DIR = os.path.join(LAB, "state")
STATE = os.path.join(STATE_DIR, "rack.json")
LOCK = os.path.join(STATE_DIR, "rack.lock")
WORK = os.path.join(LAB, "work")
REDFISH_LOG = os.path.join(STATE_DIR, "redfish.log")


def _site():
    """Whose site this is, and its site code. Kept out of the repo: lab/site.local, line 1 = name, line 2 = code."""
    try:
        with open(os.path.join(LAB, "site.local"), encoding="utf-8") as f:
            lines = [x.strip() for x in f.read().splitlines() if x.strip()]
    except OSError:
        lines = []
    return (lines[0] if lines else "the site"), (lines[1] if len(lines) > 1 else "DC1")


SITE_NAME, SITE_CODE = _site()
SITE_NAME = os.environ.get("DCLAB_SITE") or SITE_NAME

RACK = f"{SITE_CODE}-DH2-R12"     # production rack
HOSP = f"{SITE_CODE}-DH2-H01"     # hospital rack (holds spare / under-repair trays)
SITE_PKG = "1.3.6"             # from the class slide: the package in all data halls
SITE_BMC = "26.01.10001500"    # ... but BMC 26.01.10001500
LEAK_FIX_BMC = "25.09.30001500"  # slide: BMC must be above this before trusting a leak alarm
LEAK_LO, LEAK_HI = 1.70, 1.75   # slide: leak sensors are OK between 1.70 and 1.75 V
LEAK_SENSORS = [("Ch0LeaDet0ColPla", "M0_0"), ("Cha0LeaDete0Mani", "M0_1"),
                ("Ch0LeaDet1ColPla", "M1_0"), ("Cha0LeaDete1Mani", "M1_1")]
FW_ORDER = ["bmc", "bios", "bianca"]   # slide: update order BMC -> BIOS -> Bianca, CT powered off
# Lab placeholder builds. Only "1.3.6" and the BMC build 26.01.10001500 come from the slides.
PKG = {
    "1.2.5": {"bmc": "25.06.20000800", "bios": "1.2.5.41", "bianca": "1.2.5.18"},
    "1.3.6": {"bmc": "25.10.30002100", "bios": "1.3.6.12", "bianca": "1.3.6.07"},
}
SITE = {"bmc": SITE_BMC, "bios": PKG["1.3.6"]["bios"], "bianca": PKG["1.3.6"]["bianca"]}
BF3_OK = "1.3.4"
BOOT_DIE_AFTER = 6.0      # a blocked tray shows some POST, then powers off
STALE_SOL = 180           # slide: a dropped SOL session hangs 3-5 min unless deactivated
CREDS = ("admin", "admin")

SPOTS = {
    "rack": ["rack-back-right-corner", "rack-top-center", "rack-front-right-corner"],
    "ct": ["luggage-tag-near-bmc-port"],
    "N5200": ["luggage-tag-bottom-right"],
    "N5600": ["luggage-tag-right-side"],
    "cart": ["left-side-middle", "left-side-top", "left-side-bottom"],
    "power": ["back-right-near-busbar"],
    "cap": ["back-right-near-busbar", "right-side"],
}
DECOY_SPOTS = ["front-panel-pull-tab", "bottom-of-chassis", "psu-label", "left-side-near-busbar",
               "top-of-lid", "rear-fan-bay"]


def vt(v):
    return tuple(int(x) for x in re.findall(r"\d+", str(v or "0")))


def _h(seed):
    return int(hashlib.sha1(("dclab:" + seed).encode()).hexdigest(), 16)


def svc_tag(seed):
    al = "0123456789BCDFGHJKLMNPQRSTVWXZ"
    h, s = _h(seed), ""
    for _ in range(7):
        s += al[h % len(al)]
        h //= len(al)
    return s


def nv_sn(seed):
    return "1" + str(_h(seed))[:12]


def mac(seed):
    h = _h(seed)
    return "B8:3F:D2:" + ":".join(f"{(h >> (8 * i)) & 0xFF:02X}" for i in range(3))


def new_ct(name, ip, rack=RACK, slot=0):
    return {
        "name": name, "tag": svc_tag(rack + name), "bmc_ip": ip, "rack": rack, "home": rack,
        "slot": slot, "location": "rack", "lid": "closed",
        "power": "on", "power_t": time.time() - 3600, "boot_id": 1, "fail_logged": 0,
        "out0": "pxe", "override": None, "legs": [], "in_job": rack == RACK,
        "fw": dict(SITE, bf3=BF3_OK, hmc="GB200Nvl-1.3.6-02", cx7="28.44.1036"),
        "leak": {m: None for _, m in LEAK_SENSORS},
        "leak_fix": {m: [] for _, m in LEAK_SENSORS},
        "busbar_fault": False, "busbar_log": [],
        "hmc_fault": False, "hmc_reseat": [],
        "bf3_present": True, "pxe_target": True, "fan_fail": None,
        "osfp": {p: {"seated": True, "foam": True, "tension": True, "pins": True} for p in "1234"},
        "gpu_xid": [], "remap_fail": None,
        "bmc_state": "ok",  # ok | dead | needs_fix
        "sol": {"active": False, "t": 0, "pid": 0, "sticky": False, "stale": False},
        "usb": False, "seen": [], "sel": [], "hmc": [], "mac": mac(rack + name),
        "support": None,
    }


def new_rack():
    st = {"rack": RACK, "rack_tag": svc_tag("rack" + RACK), "ticket": None, "started": time.time(),
          "cts": {}, "switches": {}, "carts": {}, "power": {}, "actions": [], "cases": {},
          "wo_seq": 41200, "spares": {"fan": 2, "osfp-cable": 2, "cmos-battery": 4}, "fabric": "ok",
          "swap_form": None}
    for n in range(1, 19):
        name = f"CT{n:02d}"
        st["cts"][name] = new_ct(name, f"192.168.8.{10 + n}", RACK, n)
    for n in range(1, 4):
        name = f"H{n:02d}"
        st["cts"][name] = new_ct(name, f"192.168.9.{10 + n}", HOSP, n)
    for n in range(1, 10):
        st["switches"][f"SW{n}"] = {"tag": svc_tag(RACK + f"SW{n}"), "model": "N5200",
                                    "state": "online", "slot": n, "reset": True}
    for n in range(1, 5):
        st["carts"][f"CC{n}"] = {"sn": nv_sn(RACK + f"CC{n}")}
    for n in range(1, 9):
        st["power"][f"PT{n}"] = {"tag": svc_tag(RACK + f"PT{n}")}
    for k in ("INV1", "INV2", "CAP1"):
        st["power"][k] = {"tag": svc_tag(RACK + k)}
    return st


# ---------------------------------------------------------------- state I/O
def load():
    try:
        with open(STATE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def save(st):
    tmp = f"{STATE}.tmp{os.getpid()}"
    with open(tmp, "w") as f:
        json.dump(st, f, indent=1)
    os.replace(tmp, STATE)


@contextlib.contextmanager
def rack(write=True):
    os.makedirs(STATE_DIR, exist_ok=True)
    if write or not os.path.exists(LOCK):
        lk = open(LOCK, "a+")
    else:
        lk = open(LOCK, "r")
    with lk:
        fcntl.flock(lk, fcntl.LOCK_EX if write else fcntl.LOCK_SH)
        st = load()
        if st is None:
            st = new_rack()
            if write:
                save(st)
        for ct in st["cts"].values():
            settle(ct)
        yield st
        if write:
            save(st)


def act(st, kind, **kw):
    st["actions"].append({"t": time.time(), "k": kind, **kw})


def violation(st, msg, ct=None):
    act(st, "violation", ct=ct, msg=msg)


def workdir(st=None):
    st = st or load()
    t = (st or {}).get("ticket") or "sandbox"
    d = os.path.join(WORK, t)
    os.makedirs(d, exist_ok=True)
    return d


def ct_by_ip(st, ip):
    for ct in st["cts"].values():
        if ct["bmc_ip"] == ip:
            return ct
    return None


def ct_by_name(st, name):
    name = (name or "").upper()
    if name in st["cts"]:
        return st["cts"][name]
    for ct in st["cts"].values():
        if ct["tag"] == name:
            return ct
    return None


def stamp(t=None):
    return dt.datetime.fromtimestamp(t or time.time())


# ---------------------------------------------------------------- health model
def leak_value(ct, m):
    cause = ct["leak"][m]
    fix = ct["leak_fix"][m]
    if cause is None:
        return 1.72
    if cause == "falsealarm":
        return 0.66 if vt(ct["fw"]["bmc"]) <= vt(LEAK_FIX_BMC) else 1.72
    if cause == "contact":
        return 1.72 if "ziptie" in fix else 0.66
    if cause == "dirty":
        return 1.72 if "clean" in fix else 0.66
    if cause == "coolant":
        return 0.41
    return 1.72


def leak_crit(ct):
    out = []
    for n, m in LEAK_SENSORS:
        v = leak_value(ct, m)
        if not (LEAK_LO <= v <= LEAK_HI):
            out.append((n, m, v))
    return out


def blocked(ct):
    if leak_crit(ct):
        return "leak"
    if ct["busbar_fault"]:
        return "busbar"
    if ct["hmc_fault"]:
        return "hmc"
    return None


def port_ok(ct, p):
    o = ct["osfp"][p]
    return o["seated"] and o["foam"] and o["tension"] and o["pins"]


def pxe_ok(ct):
    return ct["bf3_present"] and vt(ct["fw"]["bf3"]) >= (1, 3) and ct["pxe_target"]


def first_outcome(ct):
    if blocked(ct):
        return "die"
    return "pxe" if pxe_ok(ct) else "shell"


def reachable(ct):
    return ct["location"] == "rack" and ct["bmc_state"] != "dead"


def package_of(ct):
    fw = ct["fw"]
    for pkg, comp in PKG.items():
        if fw["bios"] == comp["bios"] and fw["bianca"] == comp["bianca"]:
            return pkg
    return "mixed"


def settle(ct, now=None):
    now = now or time.time()
    if ct["power"] == "on" and ct.get("out0") == "die" and now - ct["power_t"] >= BOOT_DIE_AFTER:
        if ct["fail_logged"] < ct["boot_id"]:
            add_sel(ct, "Power Unit", "Pwr Unit Status", 0x70, "Power off/down",
                    t=ct["power_t"] + BOOT_DIE_AFTER, discrete=True)
            ct["fail_logged"] = ct["boot_id"]
        ct["power"] = "off"
        ct["power_t"] = ct["power_t"] + BOOT_DIE_AFTER
    s = ct["sol"]
    if s["active"] and not s.get("sticky"):
        alive = False
        if s.get("pid"):
            try:
                os.kill(s["pid"], 0)
                alive = True
            except (ProcessLookupError, PermissionError):
                alive = False
        if not alive and not s.get("stale"):
            s["stale"], s["t"] = True, now
        if s.get("stale") and now - s["t"] > STALE_SOL:
            s.update(active=False, stale=False, pid=0)


def power_on(ct):
    ct["power"] = "on"
    ct["power_t"] = time.time()
    ct["boot_id"] += 1
    ct["legs"] = []
    ct["override"] = None
    ct["out0"] = first_outcome(ct)
    why = blocked(ct)
    if why == "leak":
        for n, m, v in leak_crit(ct):
            add_sel(ct, "Voltage", n, sensor_num(n), "Lower Critical going low", reading=v, thr=LEAK_LO)
    elif why == "busbar":
        add_sel(ct, "Voltage", "P54V_BUSBAR", sensor_num("P54V_BUSBAR"), "Lower Critical going low",
                reading=41.8, thr=48.0)
    elif why == "hmc":
        add_sel(ct, "Management Subsystem Health", "HMC_Status", sensor_num("HMC_Status"),
                "Transition to Critical from less severe", discrete=True)


def power_off(ct):
    ct["power"] = "off"
    ct["power_t"] = time.time()
    ct["legs"] = []


# ---------------------------------------------------------------- sensors
SENSOR_NUMS = {"Inlet Temp": 0x01, "CPU0 Temp": 0x02, "CPU1 Temp": 0x03,
               "GPU0 Temp": 0x10, "GPU1 Temp": 0x11, "GPU2 Temp": 0x12, "GPU3 Temp": 0x13,
               "Fan1": 0x20, "Fan2": 0x21, "Fan3": 0x22, "Fan4": 0x23, "Fan5": 0x24, "Fan6": 0x25,
               "P54V_BUSBAR": 0x30, "P12V_PDB": 0x31, "Ch0LeaDet0ColPla": 0x4A, "Cha0LeaDete0Mani": 0x4B,
               "Ch0LeaDet1ColPla": 0x4C, "Cha0LeaDete1Mani": 0x4D, "HMC_Status": 0x50, "Pwr Unit Status": 0x70}


def sensor_num(name):
    return SENSOR_NUMS.get(name, 0x7F)


def sensors(ct):
    on = ct["power"] == "on" and ct["location"] == "rack"
    out = []

    def add(name, kind, ent, val=None, unit="", st="ok", text=None):
        if val is None and text is None:
            out.append({"name": name, "kind": kind, "num": sensor_num(name), "ent": ent, "st": "ns",
                        "read": "No Reading", "short": "no reading", "val": None, "unit": unit})
            return
        if text is None:
            if unit == "Volts":
                text = f"{val:.2f} Volts"
            elif unit == "RPM":
                text = f"{int(val)} RPM"
            else:
                text = f"{int(val)} degrees C"
        out.append({"name": name, "kind": kind, "num": sensor_num(name), "ent": ent, "st": st,
                    "read": text, "short": text, "val": val, "unit": unit})

    add("Inlet Temp", "Temperature", "64.1", 24, "C")
    for i, v in enumerate((47, 49)):
        add(f"CPU{i} Temp", "Temperature", f"3.{i + 1}", v if on else None, "C")
    for i, v in enumerate((41, 43, 40, 44)):
        add(f"GPU{i} Temp", "Temperature", f"11.{i + 1}", v if on else None, "C")
    for i in range(1, 7):
        if not on:
            add(f"Fan{i}", "Fan", f"29.{i}", None, "RPM")
        elif ct.get("fan_fail") == i:
            add(f"Fan{i}", "Fan", f"29.{i}", 0, "RPM", "cr")
        else:
            add(f"Fan{i}", "Fan", f"29.{i}", 5880 + 120 * i, "RPM")
    if ct["busbar_fault"]:
        add("P54V_BUSBAR", "Voltage", "10.1", 41.80, "Volts", "cr")
    else:
        add("P54V_BUSBAR", "Voltage", "10.1", 54.12, "Volts")
    add("P12V_PDB", "Voltage", "10.2", 12.06 if on else None, "Volts")
    for n, m in LEAK_SENSORS:
        v = leak_value(ct, m)
        add(n, "Voltage", "7.1", v, "Volts", "ok" if LEAK_LO <= v <= LEAK_HI else "cr")
    if ct["hmc_fault"]:
        add("HMC_Status", "Management Subsystem Health", "21.1", text="Transition to Critical", st="cr")
    else:
        add("HMC_Status", "Management Subsystem Health", "21.1", text="Transition to OK", st="ok")
    return out


def fmt_sdr_elist(s):
    return f"{s['name']:<16} | {s['num']:02X}h | {s['st']:<3} | {s['ent']:>5} | {s['read']}"


def fmt_sdr_list(s):
    return f"{s['name']:<16} | {s['short']:<17} | {s['st']}"


# ---------------------------------------------------------------- SEL
def add_sel(ct, stype, sensor, num, desc, t=None, reading=None, thr=None, unit="Volts",
            discrete=False, direction="Asserted"):
    sel = ct["sel"]
    sel.append({"id": len(sel) + 1, "t": t or time.time(), "type": stype, "sensor": sensor, "num": num,
                "desc": desc, "dir": direction, "reading": reading, "thr": thr, "unit": unit,
                "discrete": discrete})


def fmt_sel(e, extended=False):
    d = stamp(e["t"])
    who = f"{e['type']} {e['sensor']}" if extended else f"{e['type']} #0x{e['num']:02x}"
    line = f"{e['id']:>4x} | {d:%m/%d/%Y} | {d:%H:%M:%S} | {who} | {e['desc']} | {e['dir']}"
    if extended and e.get("reading") is not None:
        line += f" | Reading {e['reading']:.2f} < Threshold {e['thr']:.2f} {e['unit']}"
    return line


def fmt_sel_verbose(e):
    d = stamp(e["t"])
    lines = [f"SEL Record ID          : {e['id']:04x}",
             " Record Type           : 02",
             f" Timestamp             : {d:%m/%d/%Y %H:%M:%S}",
             " Generator ID          : 0020",
             " EvM Revision          : 04",
             f" Sensor Type           : {e['type']}",
             f" Sensor Number         : {e['num']:02x}",
             f" Sensor ID             : {e['sensor']} (0x{e['num']:02x})",
             " Event Type            : " + ("Sensor-specific Discrete" if e.get("discrete") else "Threshold"),
             " Event Direction       : " + ("Assertion Event" if e["dir"] == "Asserted" else "Deassertion Event")]
    if e.get("reading") is not None:
        lines += [f" Trigger Reading       : {e['reading']:.3f}{e['unit']}",
                  f" Trigger Threshold     : {e['thr']:.3f}{e['unit']}"]
    lines += [f" Description           : {e['desc']}", ""]
    return "\n".join(lines)


# ---------------------------------------------------------------- HMC (Redfish) events
HMC_BASE = "/redfish/v1/Systems/HGX_Baseboard_0/LogServices/EventLog/Entries"


def add_hmc(ct, message, args, severity="Critical", msgid="ResourceEvent.1.0.ResourceErrorsDetected",
            resolution="Regarding XID documentation and further actions please refer to XID catalog for "
                       "NVIDIA Data Center Products.", t=None):
    n = len(ct["hmc"]) + 1
    ct["hmc"].append({"Id": str(n), "t": t or time.time(), "Message": message, "MessageArgs": args,
                      "MessageId": msgid, "Resolution": resolution, "Severity": severity})


def hmc_entries(ct):
    out = []
    for e in ct["hmc"]:
        out.append({
            "@odata.id": f"{HMC_BASE}/{e['Id']}",
            "@odata.type": "#LogEntry.v1_15_0.LogEntry",
            "Created": stamp(e["t"]).strftime("%Y-%m-%dT%H:%M:%S+00:00"),
            "EntryType": "Event", "Id": e["Id"], "Message": e["Message"], "MessageArgs": e["MessageArgs"],
            "MessageId": e["MessageId"], "Name": "System Event Log Entry", "Resolution": e["Resolution"],
            "Resolved": False, "Severity": e["Severity"]})
    return {"@odata.id": HMC_BASE, "@odata.type": "#LogEntryCollection.LogEntryCollection",
            "Members": out, "Members@odata.count": len(out), "Name": "System Event Log Entries"}


def xid_event(ct, gpu, xid, text, t=None):
    d = stamp(t)
    raw = f"[{d:%a %b %d %H:%M:%S %Y}][1][0] XID {xid} {text}"
    add_hmc(ct, f"The resource property GPU_{gpu} Driver Event Message has detected errors of type '{raw}'.",
            [f"GPU_{gpu} Driver Event Message", raw], t=t)


def fw_inventory(ct):
    fw = ct["fw"]
    inv = {
        "BMC_Firmware": ("BMC", fw["bmc"]),
        "BIOS_Firmware": ("BIOS", fw["bios"]),
        "Bianca_Firmware": ("Bianca (GB200 board)", fw["bianca"]),
        "HMC_Firmware": ("HMC", fw["hmc"]),
        "CX7_Firmware": ("ConnectX-7 Mezz", fw["cx7"]),
        "BF3_Firmware": ("BlueField-3", fw["bf3"] if ct["bf3_present"] else ""),
        "Package": ("Firmware package", package_of(ct)),
    }
    return inv
