"""`tech` = your hands on the hardware. Each command is one physical action at the rack."""
import argparse
import os
import sys
import time
import zipfile

import core

AREAS = ["leak-sensors", "busbar", "osfp", "hmc", "bf3", "fans", "drives", "pdb", "leds"]
FRUS = ["bmc", "hmc", "pdb", "bf3", "fan", "cmos-battery", "osfp-header", "osfp-cable", "m2-riser",
        "nvme", "backplane", "control-panel", "lom", "ipex"]
TRANSFER = ["handles", "rails", "drives-internal", "drives-front"]
FW_TIME = {"bmc": ("10-15 min", 3), "bios": ("about 15 min", 3), "bianca": ("45 min to 1.5 h", 5),
           "bf3": ("about 10 min", 3)}


def say(msg):
    print(msg)


def need(cond, msg):
    if not cond:
        print(msg, file=sys.stderr)
        raise SystemExit(1)


def get_ct(st, name):
    ct = core.ct_by_name(st, name)
    need(ct is not None, f"No tray called {name}. Trays: CT01-CT18 (rack R12), H01-H03 (hospital).")
    return ct


def need_open(ct):
    need(ct["location"] == "bench", f"{ct['name']} is still in the rack. Pull it to the bench first (tech pull {ct['name']}).")
    need(ct["lid"] == "open", f"The {ct['name']} lid is closed. Open it first (tech open {ct['name']}).")


# ---------------------------------------------------------------- service tags
def cmd_spots(st, a):
    allspots = sorted({s for v in core.SPOTS.values() for s in v} | set(core.DECOY_SPOTS))
    say("Places you can look for a label:\n  " + "\n  ".join(allspots))
    say("\nItems: RACK, CT01-CT18, SW1-SW9, CC1-CC4 (cable cartridges), PT1-PT8 (power trays),\n"
        "       INV1-INV2 (power inverters), CAP1 (power capacitance tray)")


def tag_target(st, item):
    item = item.upper()
    if item == "RACK":
        return core.SPOTS["rack"], st["rack_tag"], "Service Tag"
    if item in st["cts"]:
        return core.SPOTS["ct"], st["cts"][item]["tag"], "Service Tag"
    if item in st["switches"]:
        sw = st["switches"][item]
        return core.SPOTS[sw["model"]], sw["tag"], "Service Tag"
    if item in st["carts"]:
        return core.SPOTS["cart"], st["carts"][item]["sn"], "NVIDIA SN"
    if item in st["power"]:
        return (core.SPOTS["cap"] if item == "CAP1" else core.SPOTS["power"]), st["power"][item]["tag"], "Service Tag"
    return None, None, None


def cmd_tag(st, a):
    spots, tag, label = tag_target(st, a.item)
    need(spots is not None, f"Unknown item {a.item}. Run: tech spots")
    core.act(st, "tag_look", item=a.item.upper(), spot=a.spot, ok=a.spot in spots)
    if a.spot in spots:
        say(f"{a.item.upper()}: label found at {a.spot}.  {label}: {tag}")
    else:
        say(f"No {a.item.upper()} label at {a.spot}. Look somewhere else.")


def cmd_look(st, a):
    item = a.item.upper()
    if item in st["switches"]:
        sw = st["switches"][item]
        say(f"{item}: NVLink switch tray, model {sw['model']}, slot {sw.get('slot')}, status LED: "
            + {"online": "green", "offline": "AMBER (switch offline)", "ztp_failed": "AMBER blinking (ZTP failed)",
               "removed": "(not installed)", "boxed": "(in its shipping box)"}.get(sw["state"], sw["state"])
            + ("   <- primary (switch 1)" if item == "SW1" else ""))
        return
    if item == "RACK":
        say(f"Rack {st['rack']}: 18 compute trays, 9 NVLink switch trays, 4 cable cartridges, power shelves "
            f"at the back right by the busbar. Fabric: {st['fabric']}.")
        return
    ct = get_ct(st, item)
    core.act(st, "look", ct=ct["name"])
    p = ct["power"] == "on"
    drives = "flashing AMBER" if (p and ct.get("out0") == "die" and core.blocked(ct) == "leak") else ("green" if p else "off")
    say(f"{ct['name']} ({ct['tag']}): location {ct['location']} ({ct['rack']} slot {ct['slot']}), lid {ct['lid']}\n"
        f"  power LED: {'green' if p else 'off'}   drive LEDs: {drives}   USB stick: {'inserted' if ct['usb'] else 'none'}\n"
        f"  in a running job: {'yes' if ct['in_job'] else 'no'}")


# ---------------------------------------------------------------- moving trays
def cmd_power_button(st, a):
    ct = get_ct(st, a.ct)
    need(core.reachable(ct) or ct["bmc_state"] == "dead", f"{ct['name']} is not in a rack.")
    if ct["power"] == "on":
        if a.hold:
            if ct["in_job"]:
                core.violation(st, f"Held the power button on {ct['name']} during a running job (hard power off). "
                                   "This breaks the NVLink fabric; the job needs a manual restart.", ct["name"])
            ct["in_job"] = False
            core.power_off(ct)
            core.act(st, "hard_off", ct=ct["name"], via="button")
            say(f"{ct['name']}: held the power button 5 s. Tray is off (hard power off).")
        else:
            core.act(st, "graceful", ct=ct["name"], was_in_job=ct["in_job"], via="button")
            ct["in_job"] = False
            core.power_off(ct)
            say(f"{ct['name']}: short press. OS shut down (ACPI). Tray is off.")
    else:
        if ct["bmc_state"] == "needs_fix":
            core.violation(st, f"Powered on {ct['name']} before running fixBMC.sh on the new BMC", ct["name"])
        if ct["bmc_state"] == "dead":
            say(f"{ct['name']}: nothing happens. The BMC is not responding.")
            return
        core.power_on(ct)
        say(f"{ct['name']}: power button pressed. Tray powering on.")


def cmd_pull(st, a):
    ct = get_ct(st, a.ct)
    need(ct["location"] == "rack", f"{ct['name']} is already out of the rack ({ct['location']}).")
    if ct["power"] == "on":
        core.violation(st, f"Pulled {ct['name']} out of the rack while it was powered on. In a running rack this "
                           "breaks the NVLink fabric (even if the tray is not in the job).", ct["name"])
        core.power_off(ct)
    ct["location"] = "bench"
    ct["in_job"] = False
    if ct["sol"]["active"]:
        ct["sol"].update(active=False, stale=False, pid=0)
    core.act(st, "pull", ct=ct["name"])
    say(f"{ct['name']} pulled from {ct['rack']} slot {ct['slot']} and placed on the bench.")


def cmd_insert(st, a):
    ct = get_ct(st, a.ct)
    need(ct["location"] == "bench", f"{ct['name']} is not on the bench.")
    need(ct["lid"] == "closed", f"Close the lid first (tech close {ct['name']}).")
    ct["location"] = "rack"
    core.act(st, "insert", ct=ct["name"], rack=ct["rack"])
    say(f"{ct['name']} inserted into {ct['rack']} slot {ct['slot']}. Standby power on; BMC up. Host is off.")


def cmd_open(st, a):
    ct = get_ct(st, a.ct)
    need(ct["location"] == "bench", f"Pull {ct['name']} to the bench before you open it.")
    ct["lid"] = "open"
    core.act(st, "open", ct=ct["name"])
    say(f"{ct['name']} lid open. Wear your ESD strap.")


def cmd_close(st, a):
    ct = get_ct(st, a.ct)
    ct["lid"] = "closed"
    core.act(st, "close", ct=ct["name"])
    say(f"{ct['name']} lid closed.")


def cmd_move(st, a):
    ct = get_ct(st, a.ct)
    need(ct["location"] == "bench", f"Pull {ct['name']} out before you move it.")
    dest = a.dest.lower()
    need(dest in ("hospital", "production"), "Destination: hospital or production")
    ct["rack"] = core.HOSP if dest == "hospital" else ct["home"]
    core.act(st, "move", ct=ct["name"], dest=dest)
    say(f"{ct['name']} is now assigned to {ct['rack']}. Insert it there with: tech insert {ct['name']}")


# ---------------------------------------------------------------- inspection and repair
def cmd_inspect(st, a):
    ct = get_ct(st, a.ct)
    area = a.area
    core.act(st, "inspect", ct=ct["name"], area=area)
    if area == "leds":
        return cmd_look(st, argparse.Namespace(item=ct["name"]))
    need_open(ct)
    if area == "leak-sensors":
        for n, m in core.LEAK_SENSORS:
            cause = ct["leak"][m]
            fix = ct["leak_fix"][m]
            if cause == "contact" and "ziptie" not in fix:
                d = "sensor cable is resting ON the cold plate" + ("" if "clean" in fix else "; sensor surface is dirty")
            elif cause == "dirty" and "clean" not in fix:
                d = "sensor surface is dirty"
            elif cause == "coolant":
                d = "wet residue around the sensor"
            else:
                d = "looks normal"
            say(f"  {m} ({n}): {d}")
    elif area == "busbar":
        if ct["busbar_fault"]:
            say("  Internal busbar screws: several look under-torqued (gap under the screw heads).")
        else:
            say("  Internal busbar screws: all seated and torqued.")
    elif area == "osfp":
        for p, o in ct["osfp"].items():
            notes = []
            if not o["foam"]:
                notes.append("foam pad is out of place")
            if not o["tension"]:
                notes.append("tension bar is loose (not torqued down)")
            if not o["pins"]:
                notes.append("BENT PINS on the OSFP header cable")
            if not o["seated"]:
                notes.append("cable not fully seated in the mezz connector")
            say(f"  Mezz port {p}: " + ("; ".join(notes) if notes else "cable seated, power cable connected, looks good"))
    elif area == "hmc":
        say("  HMC card and slimline cables: " + ("cables look partly unseated" if ct["hmc_fault"] else "seated"))
    elif area == "bf3":
        say("  BlueField-3: " + ("card present, but the PCIe link LED is off" if not ct["bf3_present"] else "seated, link LED on"))
    elif area == "fans":
        f = ct.get("fan_fail")
        say("  Fans: " + (f"fan {f} does not spin when you nudge it (failed)" if f else "all fans spin freely"))
    elif area == "pdb":
        say("  PDB: no burn marks. Gather logs: the HMC log shows PDB errors when there are any.")
    elif area == "drives":
        say("  Drives: front NVMe slots 0-3 populated. Internal M.2 boot drive on the riser.")


def cmd_uv(st, a):
    ct = get_ct(st, a.ct)
    need_open(ct)
    core.act(st, "uv", ct=ct["name"])
    wet = any(v == "coolant" for v in ct["leak"].values())
    say("UV light check: " + ("bright fluorescent residue near the manifold. COOLANT PRESENT." if wet
                              else "no fluorescence anywhere. No coolant."))


def cmd_clean(st, a):
    ct = get_ct(st, a.ct)
    need_open(ct)
    need(a.sensor in ct["leak"], "Sensor names: M0_0 M0_1 M1_0 M1_1")
    ct["leak_fix"][a.sensor].append("clean")
    core.act(st, "clean", ct=ct["name"], sensor=a.sensor)
    say(f"Cleaned leak sensor {a.sensor} with IPA wipe.")


def cmd_ziptie(st, a):
    ct = get_ct(st, a.ct)
    need_open(ct)
    need(a.sensor in ct["leak"], "Sensor names: M0_0 M0_1 M1_0 M1_1")
    ct["leak_fix"][a.sensor].append("ziptie")
    core.act(st, "ziptie", ct=ct["name"], sensor=a.sensor)
    say(f"Zip-tied the {a.sensor} sensor cable so it no longer touches the cold plate.")


def cmd_loosen(st, a):
    ct = get_ct(st, a.ct)
    need_open(ct)
    need(a.target == "busbar", "Only the busbar screws are loosened in this lab.")
    ct["busbar_log"] = ["loosen-all"]
    core.act(st, "loosen", ct=ct["name"], target="busbar")
    say("Loosened all the internal busbar screws.")


def cmd_torque(st, a):
    ct = get_ct(st, a.ct)
    need_open(ct)
    core.act(st, "torque", ct=ct["name"], target=a.target, section=a.section, port=a.port, inlb=a.inlb)
    if a.target == "busbar":
        need(a.section in ("back", "front", "middle"), "Busbar sections: back, front, middle (--section)")
        need(a.inlb is not None, "Give the torque value in inch-pounds (--inlb N)")
        ct["busbar_log"].append(f"{a.section}@{a.inlb}")
        say(f"Torqued busbar {a.section} screws to {a.inlb} in-lb.")
        if ct["busbar_log"][:1] == ["loosen-all"] and ct["busbar_log"][1:] == ["back@20", "front@20", "middle@20"]:
            ct["busbar_fault"] = False
    elif a.target == "tension-bar":
        need(a.port in ct["osfp"], "Give the mezz port (--port 1-4)")
        ct["osfp"][a.port]["tension"] = True
        say(f"Tension bar on mezz port {a.port} torqued down.")
    else:
        need(False, "Torque targets: busbar (--section, --inlb) or tension-bar (--port)")


def cmd_reseat(st, a):
    ct = get_ct(st, a.ct)
    part = a.part
    if part == "usb":
        need(False, "Use: tech usb <CT> insert|remove")
    need_open(ct)
    core.act(st, "reseat", ct=ct["name"], part=part, port=a.port)
    if part in ("hmc-slimline-cables", "hmc-card"):
        if part not in ct["hmc_reseat"]:
            ct["hmc_reseat"].append(part)
        if {"hmc-slimline-cables", "hmc-card"} <= set(ct["hmc_reseat"]):
            ct["hmc_fault"] = False
        say(f"Reseated the {part}.")
    elif part == "osfp-cable":
        need(a.port in ct["osfp"], "Give the mezz port (--port 1-4)")
        ct["osfp"][a.port]["seated"] = True
        say(f"Reseated the OSFP cable on mezz port {a.port}.")
    elif part == "foam-pad":
        need(a.port in ct["osfp"], "Give the mezz port (--port 1-4)")
        ct["osfp"][a.port]["foam"] = True
        say(f"Put the foam pad on mezz port {a.port} back in the correct location.")
    elif part == "bf3":
        say("Reseated the BlueField-3. " + ("No change: the card itself is faulty." if not ct["bf3_present"] else ""))
    else:
        say(f"Reseated {part}.")


def cmd_replace(st, a):
    ct = get_ct(st, a.ct)
    need_open(ct)
    fru = a.fru
    need(fru in FRUS, "FRUs: " + ", ".join(FRUS))
    case = st["cases"].get(ct["name"])
    have_wo = case and case.get("part") == fru
    spare = st["spares"].get(fru, 0) > 0
    need(have_wo or spare,
         f"No {fru} on site for {ct['name']}. Open a support case first so a part ships (tech case ...).")
    if not have_wo and spare:
        st["spares"][fru] -= 1
    core.act(st, "replace", ct=ct["name"], fru=fru, port=a.port, wo=case.get("wo") if case else None)
    if fru == "bf3":
        ct["bf3_present"] = True
        ct["fw"]["bf3"] = core.BF3_OK
        ct["hmc"] = [e for e in ct["hmc"] if "BlueField" not in e["Message"]]
    elif fru == "fan":
        ct["fan_fail"] = None
    elif fru == "osfp-cable":
        need(a.port in ct["osfp"], "Give the mezz port (--port 1-4)")
        ct["osfp"][a.port].update(pins=True, seated=True)
    elif fru == "bmc":
        ct["bmc_state"] = "needs_fix"
        ct["fw"]["bmc"] = core.PKG["1.2.5"]["bmc"]
    elif fru == "hmc":
        ct["hmc_fault"] = False
    say(f"Replaced the {fru} in {ct['name']}." + (f" (work order {case['wo']})" if have_wo else ""))


def cmd_run(st, a):
    ct = get_ct(st, a.ct)
    need(a.script == "fixBMC.sh", "Scripts in this lab: fixBMC.sh")
    need(ct["location"] == "rack", f"Insert {ct['name']} first so the BMC has standby power.")
    core.act(st, "fixbmc", ct=ct["name"], power=ct["power"])
    if ct["power"] == "on":
        say("fixBMC.sh: ERROR host is powered on. Run it with the CT powered off.")
        return
    if ct["bmc_state"] == "needs_fix":
        ct["bmc_state"] = "ok"
        say("fixBMC.sh: programming board identity and FRU data on the new BMC ... done. Safe to power on.")
    else:
        say("fixBMC.sh: BMC identity already correct. Nothing to do.")


def cmd_usb(st, a):
    ct = get_ct(st, a.ct)
    ct["usb"] = a.action == "insert"
    core.act(st, "usb", ct=ct["name"], action=a.action)
    say(f"Support Live Image USB stick {'inserted into' if ct['usb'] else 'removed from'} {ct['name']}.")


# ---------------------------------------------------------------- firmware
def cmd_fwupdate(st, a):
    ct = get_ct(st, a.ct)
    comp, ver = a.component, a.version
    need(comp in ("bmc", "bios", "bianca", "bf3"), "Components: bmc, bios, bianca, bf3")
    need(core.reachable(ct), f"{ct['name']} must be in a rack with a working BMC to update firmware.")
    known = {"bmc": [core.SITE_BMC] + [p["bmc"] for p in core.PKG.values()],
             "bios": [p["bios"] for p in core.PKG.values()],
             "bianca": [p["bianca"] for p in core.PKG.values()],
             "bf3": ["1.2.0", core.BF3_OK]}[comp]
    need(ver in known, f"No {comp} image {ver} in the site firmware repo. Images: {', '.join(known)}  (see: dclab matrix)")
    cur = ct["fw"][comp]
    on = ct["power"] == "on"
    core.act(st, "fwupdate", ct=ct["name"], comp=comp, frm=cur, to=ver, power=ct["power"],
             pkg=core.package_of(ct))
    if on:
        core.violation(st, f"Updated {comp} on {ct['name']} while the CT was powered on. Power it off for each update.",
                       ct["name"])
    if comp in core.FW_ORDER:
        if core.package_of(ct) == "1.3.6" and core.vt(ver) < core.vt(cur):
            core.violation(st, f"Tried to downgrade {comp} on {ct['name']} from a 1.3.6 package. 1.3.6 cannot be "
                               "downgraded.", ct["name"])
            say(f"Update FAILED: image {ver} rejected by ERoT (version policy).")
            return
        idx = core.FW_ORDER.index(comp)
        for earlier in core.FW_ORDER[:idx]:
            if core.vt(ct["fw"][earlier]) < core.vt(core.SITE[earlier]):
                core.violation(st, f"Updated {comp} on {ct['name']} before {earlier}. Order is BMC, then BIOS, then "
                                   "Bianca.", ct["name"])
                break
    real, lab = FW_TIME[comp]
    print(f"Updating {comp} on {ct['name']}: {cur} -> {ver}   (real time {real}; lab time {lab} s) ", end="", flush=True)
    for _ in range(lab):
        time.sleep(1)
        print(".", end="", flush=True)
    ct["fw"][comp] = ver
    print(" done.")


# ---------------------------------------------------------------- support / RMA
def read_attachment(path):
    if path.endswith(".zip"):
        try:
            with zipfile.ZipFile(path) as z:
                return "\n".join(z.read(n).decode("utf-8", "replace") for n in z.namelist())
        except (zipfile.BadZipFile, OSError):
            return ""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def cmd_case(st, a):
    ct = get_ct(st, a.ct)
    files = a.attach or []
    texts = []
    for f in files:
        need(os.path.exists(f), f"Attachment not found: {f}")
        texts.append(read_attachment(f))
    blob = "\n".join(texts)
    core.act(st, "case", ct=ct["name"], files=[os.path.abspath(f) for f in files], size=len(blob))
    rule = ct.get("support")
    say(f"Support case opened for {ct['name']} ({ct['tag']}). Attachments: {', '.join(files) or 'none'}")
    if not rule:
        say("Support: thanks. Please collect logs and follow the troubleshooting steps for this symptom first.")
        return
    if not files or not all(k.lower() in blob.lower() for k in rule["needs"]):
        say("Support: the logs you sent do not show the fault. Attach the HMC event log (or the ezBMC zip) for this "
            "tray, collected from its BMC.")
        return
    st["wo_seq"] += 1
    wo = f"WO-{st['wo_seq']}"
    st["cases"][ct["name"]] = {"wo": wo, "part": rule["part"], "t": time.time()}
    say(f"Support: {rule['reply']}\nSupport: Part Only work order {wo} opened for: {rule['part']}.")


def cmd_receive(st, a):
    ct = get_ct(st, a.ct)
    case = st["cases"].get(ct["name"])
    need(case is not None, f"No work order for {ct['name']}. Nothing is shipping yet.")
    if case["part"] != "ct":
        say(f"Received {case['part']} for {case['wo']}. Install it with: tech replace {ct['name']} {case['part']}")
        return
    need("new" not in case, "Replacement tray already received.")
    tag = core.svc_tag("replacement" + ct["tag"])
    case["new"] = tag
    case["moved"] = []
    core.act(st, "receive", ct=ct["name"], new=tag, wo=case["wo"])
    say(f"Replacement compute tray received for {case['wo']}. New service tag: {tag}.\n"
        "It arrived without handles, rails or drives.")


def cmd_transfer(st, a):
    ct = get_ct(st, a.ct)
    case = st["cases"].get(ct["name"])
    need(case and case.get("new"), "Receive the replacement tray first (tech receive ...).")
    need(ct["location"] == "bench", f"Pull {ct['name']} to the bench first.")
    need(a.item in TRANSFER, "Transfer items: " + ", ".join(TRANSFER))
    if a.item not in case["moved"]:
        case["moved"].append(a.item)
    core.act(st, "transfer", ct=ct["name"], item=a.item)
    say(f"Moved {a.item} from {ct['tag']} to the replacement {case['new']}.")


def cmd_swap_form(st, a):
    core.act(st, "swap_form", old=a.old, new=a.new, wo=a.wo)
    st["swap_form"] = {"old": a.old.upper(), "new": a.new.upper(), "wo": a.wo.upper()}
    say(f"Swap form submitted: old {a.old.upper()} -> new {a.new.upper()} on {a.wo.upper()}.")


def cmd_hospital(st, a):
    say(f"Hospital rack {core.HOSP}:")
    for ct in st["cts"].values():
        if ct["rack"] == core.HOSP:
            say(f"  {ct['name']:<5} {ct['tag']}  {ct['location']:<6} power {ct['power']:<3}  "
                + ("healthy spare" if ct["name"].startswith("H") else "under repair"))


# ---------------------------------------------------------------- NVLink switches
def cmd_switch(st, a):
    name = a.sw.upper()
    sws = st["switches"]
    need(name in sws, f"Switch trays: SW1-SW9{', SWNEW' if 'SWNEW' in sws else ''}")
    sw = sws[name]
    core.act(st, "switch", sw=name, action=a.action, slot=a.slot)
    if a.action == "status":
        return cmd_look(st, argparse.Namespace(item=name))
    if a.action == "factory-reset":
        sw["reset"] = True
        say(f"{name}: factory reset complete. Startup config erased; ZTP will run on first boot.")
    elif a.action == "remove":
        need(sw["state"] != "removed", f"{name} is already out.")
        if any(s["state"] == "online" for k, s in sws.items() if k != name) and sw["state"] == "online":
            core.violation(st, f"Pulled online switch {name} from a production rack. One NVLink switch offline "
                               "halts production on the whole rack.")
        sw["state"] = "removed"
        say(f"{name} removed from slot {sw['slot']}.")
    elif a.action == "install":
        need(a.slot, "Give the slot (--slot N)")
        busy = [k for k, s in sws.items() if s.get("slot") == a.slot and s["state"] not in ("removed", "boxed") and k != name]
        need(not busy, f"Slot {a.slot} still holds {busy[0] if busy else ''}. Remove it first.")
        sw["slot"] = a.slot
        if not sw["reset"]:
            sw["state"] = "ztp_failed"
            core.violation(st, f"Installed {name} without a factory reset. ZTP failed.")
            say(f"{name} in slot {a.slot}: booting ... ZTP FAILED (switch already has a startup config).")
            return
        sw["state"] = "online"
        if all(s["state"] == "online" for s in sws.values() if s["state"] not in ("removed", "boxed")):
            st["fabric"] = "ok"
        say(f"{name} in slot {a.slot}: booting ... ZTP pulled config from switch 1 (primary) ... online.")


def build():
    p = argparse.ArgumentParser(prog="tech", description="Physical actions at the rack. Each one is logged and graded.")
    s = p.add_subparsers(dest="cmd", metavar="<action>")

    def sp(name, fn, help_):
        q = s.add_parser(name, help=help_)
        q.set_defaults(fn=fn)
        return q

    sp("spots", cmd_spots, "list the label spots and item names")
    q = sp("tag", cmd_tag, "read a service tag: tech tag <ITEM> <SPOT>")
    q.add_argument("item"); q.add_argument("spot")
    q = sp("look", cmd_look, "look at a tray, switch or the rack (LEDs, location)")
    q.add_argument("item")
    q = sp("power-button", cmd_power_button, "press the tray power button (--hold = hard off)")
    q.add_argument("ct"); q.add_argument("--hold", action="store_true")
    for name, fn, h in (("pull", cmd_pull, "pull a tray out of the rack onto the bench"),
                        ("insert", cmd_insert, "insert a tray from the bench into its rack"),
                        ("open", cmd_open, "open the tray lid (on the bench)"),
                        ("close", cmd_close, "close the tray lid")):
        sp(name, fn, h).add_argument("ct")
    q = sp("move", cmd_move, "assign a pulled tray to the hospital rack or back to production")
    q.add_argument("ct"); q.add_argument("dest")
    q = sp("inspect", cmd_inspect, "inspect an area inside an open tray: " + ", ".join(AREAS))
    q.add_argument("ct"); q.add_argument("area", choices=AREAS)
    sp("uv", cmd_uv, "UV-light check for coolant inside an open tray").add_argument("ct")
    for name, fn, h in (("clean", cmd_clean, "clean a leak sensor (M0_0 M0_1 M1_0 M1_1)"),
                        ("ziptie", cmd_ziptie, "zip-tie a leak sensor away from the cold plate")):
        q = sp(name, fn, h)
        q.add_argument("ct"); q.add_argument("sensor")
    q = sp("loosen", cmd_loosen, "loosen all screws on a part (busbar)")
    q.add_argument("ct"); q.add_argument("target")
    q = sp("torque", cmd_torque, "torque screws: busbar (--section, --inlb) or tension-bar (--port)")
    q.add_argument("ct"); q.add_argument("target")
    q.add_argument("--section"); q.add_argument("--port"); q.add_argument("--inlb", type=int)
    q = sp("reseat", cmd_reseat, "reseat: hmc-slimline-cables, hmc-card, osfp-cable --port N, foam-pad --port N, bf3")
    q.add_argument("ct"); q.add_argument("part"); q.add_argument("--port")
    q = sp("replace", cmd_replace, "replace a FRU: " + ", ".join(FRUS))
    q.add_argument("ct"); q.add_argument("fru"); q.add_argument("--port")
    q = sp("run", cmd_run, "run a service script against a tray's BMC (fixBMC.sh)")
    q.add_argument("ct"); q.add_argument("script")
    q = sp("usb", cmd_usb, "insert or remove the Support Live Image USB stick")
    q.add_argument("ct"); q.add_argument("action", choices=["insert", "remove"])
    q = sp("fwupdate", cmd_fwupdate, "update firmware: tech fwupdate <CT> <bmc|bios|bianca|bf3> <version>")
    q.add_argument("ct"); q.add_argument("component"); q.add_argument("version")
    q = sp("case", cmd_case, "open a support case and attach logs: tech case <CT> --attach FILE [FILE...]")
    q.add_argument("ct"); q.add_argument("--attach", nargs="+")
    sp("receive", cmd_receive, "receive the replacement part or tray for a work order").add_argument("ct")
    q = sp("transfer", cmd_transfer, "move parts to the replacement tray: " + ", ".join(TRANSFER))
    q.add_argument("ct"); q.add_argument("item")
    q = sp("swap-form", cmd_swap_form, "submit the swap form")
    q.add_argument("--old", required=True); q.add_argument("--new", required=True); q.add_argument("--wo", required=True)
    sp("hospital", cmd_hospital, "list trays in the hospital rack")
    q = sp("switch", cmd_switch, "NVLink switch tray: status | factory-reset | remove | install --slot N")
    q.add_argument("sw"); q.add_argument("action", choices=["status", "factory-reset", "remove", "install"])
    q.add_argument("--slot", type=int)
    return p


def main(argv):
    p = build()
    a = p.parse_args(argv)
    if not getattr(a, "fn", None):
        p.print_help()
        return 1
    with core.rack() as st:
        a.fn(st, a)
    return 0
