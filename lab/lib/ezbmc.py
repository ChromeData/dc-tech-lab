"""Lab stand-in for ezBMC: one command gathers HMC, SEL, SDR and firmware into a zip.

The real ezBMC is a Dell field tool installed in WSL; its exact syntax may differ.
"""
import html
import json
import os
import sys
import time
import zipfile

import core

USAGE = "usage: ezbmc <BMC_IP>      (lab stand-in; real ezBMC syntax may differ)"


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(USAGE)
        return 0 if argv else 1
    ip = argv[-1]
    with core.rack() as st:
        ct = core.ct_by_ip(st, ip)
        core.act(st, "ezbmc", ip=ip, ct=ct["name"] if ct else None)
        if ct is None or not core.reachable(ct):
            print(f"ezBMC: cannot reach BMC at {ip}", file=sys.stderr)
            return 1
        sel = "\n".join(core.fmt_sel_verbose(e) for e in ct["sel"]) or "SEL has no entries"
        sdr = "\n".join(core.fmt_sdr_elist(s) for s in core.sensors(ct))
        hmc = json.dumps(core.hmc_entries(ct), indent=2) if not ct["hmc_fault"] else '{"error": "HMC not responding"}'
        fw = json.dumps({k: {"Name": n, "Version": v} for k, (n, v) in core.fw_inventory(ct).items()}, indent=2)
        tag = ct["tag"]
    print(f"ezBMC (dclab) -> {ip}  service tag {tag}   (real time: 3-5 min)")
    for step in ("HMC event log", "SEL", "SDR", "Firmware inventory"):
        time.sleep(0.6)
        print(f"  collecting {step} ... ok")
    out = os.path.join(os.path.expanduser("~"), "ezBMC_Logs")
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"{tag}_{time.strftime('%Y%m%d-%H%M%S')}.zip")
    viewer = ("<html><body><h1>ezBMC " + tag + "</h1>" +
              "".join(f"<h2>{t}</h2><pre>{html.escape(b)}</pre>" for t, b in
                      (("SEL", sel), ("SDR", sdr), ("HMC", hmc), ("Firmware", fw))) + "</body></html>")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{tag}-sel.txt", sel + "\n")
        z.writestr(f"{tag}-sdr.txt", sdr + "\n")
        z.writestr(f"{tag}-HMCevents.json", hmc + "\n")
        z.writestr(f"{tag}-firmware.json", fw + "\n")
        z.writestr("viewer.html", viewer)
    print(f"Saved {path}\n(open viewer.html inside the zip to see everything)")
    return 0
