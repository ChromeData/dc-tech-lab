"""GB200 NVL72 tickets. Every fact in TEACH comes from the class slides."""
import glob
import os
import time

import core
from ticketlib import (failed_boot_history, healthy, logs_first, logs_ok, no_viol, parked_at_shell, register,
                       resolution)

LOGCMDS = [
    "SEL:  ipmitool -I lanplus -H <BMC_IP> -U admin -P admin sel -v list | tee -a <ServiceTag>-sel.txt",
    "SDR:  ipmitool -I lanplus -H <BMC_IP> -U admin -P admin sdr elist | tee -a <ServiceTag>-sdr.txt",
    "HMC:  curl -k -u 'admin:admin' https://<BMC_IP>/redfish/v1/Systems/HGX_Baseboard_0/LogServices/EventLog/Entries"
    " | jq | tee -a <ServiceTag>-HMCevents.txt",
]
SHOW_LOGS = [
    "cd {wd}",
    "ipmitool -I lanplus -H {ip} -U admin -P admin sel -v list | tee -a {tag}-sel.txt",
    "ipmitool -I lanplus -H {ip} -U admin -P admin sdr elist | tee -a {tag}-sdr.txt",
    "curl -k -u 'admin:admin' https://{ip}/redfish/v1/Systems/HGX_Baseboard_0/LogServices/EventLog/Entries | jq | tee -a {tag}-HMCevents.txt",
]
IPMI = "ipmitool -I lanplus -H {ip} -U admin -P admin"


# ============================================================== 101 service tags
def s101(st):
    pass


def c101(x):
    kv = x.kv("tags.txt")
    st = x.st
    want = {"rack": st["rack_tag"], "ct07": st["cts"]["CT07"]["tag"], "sw1": st["switches"]["SW1"]["tag"],
            "cc2": st["carts"]["CC2"]["sn"], "pt3": st["power"]["PT3"]["tag"], "cap1": st["power"]["CAP1"]["tag"]}
    for k, v in want.items():
        x.c(f"tags.txt has the right value for {k.upper()}", kv.get(k, "").upper() == v)
    x.c("You found each label at the rack (tech tag), not by guessing",
        all(x.acts("tag_look", item=k.upper(), ok=True) for k in want))


register(
    tid="DCOPS-101", title="Find the service tags", track="GB200", ct="CT07",
    body="Support needs the service tags before they will open any case on rack R12.",
    teach=[
        "IR7000 rack tag: back of the rack in the right corner, or top center, or front right corner (newer racks).",
        "Compute tray (CT): on the luggage tag near the BMC port.",
        "NVLink switch: bottom of the luggage tag, bottom right (N5200) or right side (N5600).",
        "Cable cartridge: left side, in the middle and on the top and bottom. Use the NVIDIA SN.",
        "Power trays, power inverters, power capacitance tray: back right side near the bus bar "
        "(the capacitance tray can also be on the right side).",
    ],
    do=[
        "Run `tech spots` to see the spot names, and `tech look SW1` to see the switch model.",
        "Read each label with `tech tag <ITEM> <SPOT>` for: RACK, CT07, SW1, CC2, PT3, CAP1.",
        "Write {wd}/tags.txt with one line each, like  CT07=XXXXXXX",
    ],
    nudge="Each item type has its own spot. The switch spot depends on the model.",
    walk=["Rack: try the back right corner.", "CT07: the luggage tag by the BMC port.",
          "SW1 is an N5200: bottom right of the luggage tag.", "CC2: left side. It gives an NVIDIA SN.",
          "PT3 and CAP1: back right near the bus bar.", "Type the six values into tags.txt as NAME=value."],
    show=["tech tag RACK rack-back-right-corner", "tech tag CT07 luggage-tag-near-bmc-port",
          "tech tag SW1 luggage-tag-bottom-right", "tech tag CC2 left-side-middle",
          "tech tag PT3 back-right-near-busbar", "tech tag CAP1 back-right-near-busbar",
          "nano {wd}/tags.txt   # RACK=..  CT07=..  SW1=..  CC2=..  PT3=..  CAP1=.."],
    setup=s101, check=c101)


# ============================================================== 102 stuck at Shell>
def s102(st):
    ct = st["cts"]["CT03"]
    ct["pxe_target"] = False
    parked_at_shell(ct)
    ct["sol"].update(active=True, t=time.time(), pid=0, sticky=True, stale=True)


def c102(x):
    ct = x.ct("CT03")
    tag = ct["tag"]
    x.c("You cleared the stuck SOL session with `sol deactivate`", x.acts("sol_deactivate", ct="CT03"))
    rec = x.read(f"{tag}-sol.txt")
    x.c(f"{tag}-sol.txt holds the full POST (recorded with `script`)", "Service Tag" in rec and "Initializing Grace" in rec)
    x.c("The recording shows the tray reaching Shell>", "Shell>" in rec)
    x.c("You typed `exit` at Shell> to retry the boot", any(a["cmd"].strip().lower() == "exit"
                                                             for a in x.acts("sol_input", ct="CT03", mode="shell")))
    ex = x.acts("sol_exit", ct="CT03")
    x.c("You left SOL with ~. and no session is left open", bool(ex) and ex[-1]["clean"] and not ct["sol"]["active"])
    resolution(x, ("post",), ("complete", "passed", "finished", "success", "ok", "done", "normal"), ("pxe", "provision"))
    no_viol(x)


register(
    tid="DCOPS-102", title="CT03 is 'stuck' at Shell>", track="GB200", ct="CT03",
    body="NOC: CT03 ({tag}, BMC {ip}) is sitting at a Shell> prompt. Is the tray dead? The last tech "
         "unplugged their laptop without closing the console.",
    teach=[
        "Serial over LAN from WSL:  ipmitool -I lanplus -H <BMC_IP> -U admin -P admin sol activate",
        "To end a stuck session run the same command with `sol deactivate` in another window. A dropped "
        "session stays open 3 to 5 minutes unless you deactivate it.",
        "`script <file>.txt` records everything on screen to a file. Type `exit` to stop recording.",
        "SOL shows the complete POST and the Linux boot. F2 = BIOS, F11 = Boot Override Menu.",
        "If nothing is found to boot from PXE, the tray boots to an EFI shell. This is normal: the CT has "
        "completed POST. It does not rule out PXE issues. Type `exit` at Shell> to try the boot again.",
        "Leave SOL by typing  ~.  (tilde, then period) at the start of a line.",
    ],
    do=[
        "cd {wd}   (use two terminal windows for this ticket)",
        "Window 1: start recording to {tag}-sol.txt, then open SOL to CT03. It fails. Work out why and clear it.",
        "Window 2: power-cycle CT03 with ipmitool while window 1 watches the whole POST.",
        "At Shell>, type `exit` once and watch the retry.",
        "Leave SOL with ~. and stop the recording with `exit`.",
        "Write resolution.txt: did POST complete, what is the next step, and which team owns it?",
    ],
    nudge="The error says another session holds the console. Which SOL sub-command ends a session?",
    walk=["Start `script` with the service tag in the file name.", "Try `sol activate`; read the error.",
          "From window 2 run the same command with `sol deactivate`, then activate again in window 1.",
          "From window 2 run `chassis power cycle`. Watch POST scroll in window 1.",
          "Wait for Shell>, type exit, watch PXE fail again and land back at Shell>.",
          "Press Enter, then ~. to leave. Type exit to stop `script`.",
          "resolution.txt: POST completed; PXE found nothing to boot; hand to provisioning."],
    show=["cd {wd}", "script {tag}-sol.txt", IPMI + " sol activate        # fails: already active",
          "# window 2:", IPMI + " sol deactivate", "# window 1:", IPMI + " sol activate",
          "# window 2:", IPMI + " chassis power cycle", "# window 1 at Shell> :  exit   (wait for Shell> again)",
          "# window 1:  Enter, then  ~.   then  exit   (stops script)",
          "echo 'POST completed. EFI shell is normal when PXE finds no boot image. Next: provisioning team "
          "checks the PXE target for this MAC.' > resolution.txt"],
    setup=s102, check=c102)


# ============================================================== 103 log collection
def s103(st):
    ct = st["cts"]["CT11"]
    now = time.time()
    core.xid_event(ct, 3, 121, "C2C BUS ERROR: Link Idx: 7; STATUS_REG: 0x00000020", t=now - 7200)
    core.xid_event(ct, 3, 121, "C2C BUS ERROR: Link Idx: 7; STATUS_REG: 0x00000020", t=now - 7100)
    core.add_sel(ct, "System Event", "Boot Event", 0x60, "OEM System boot event", t=now - 86400, discrete=True)


def c103(x):
    ct = x.ct("CT11")
    logs_ok(x, ct)
    x.c("The HMC log you saved contains the GPU error", x.grep(f"{ct['tag']}-HMCevents.txt", r"XID 121"))
    zips = [z for z in glob.glob(os.path.expanduser(f"~/ezBMC_Logs/{ct['tag']}_*.zip"))
            if os.path.getmtime(z) >= x.st["started"]]
    x.c("ezBMC bundle for this tray is in ~/ezBMC_Logs", zips)
    resolution(x, ("gpu_3", "gpu 3", "gpu3"), ("121",))


register(
    tid="DCOPS-103", title="Collect logs on CT11", track="GB200", ct="CT11",
    body="Support asked for logs on CT11 ({tag}, BMC {ip}) after a job crashed. Nothing to fix yet. "
         "Collect everything and tell them which GPU logged an error.",
    teach=["Logs need to be collected whenever you work on a CT.",
           "BIOS POST output: captured from your SOL session."] + LOGCMDS + [
        "`tee -a` shows the output and appends it to the file. Name every file with the service tag.",
        "The HMC log shows PCI errors for the CX7/8 mezzanine, BlueField-3 and GPUs.",
        "ezBMC gathers all of it (HMC, SEL, SDR, firmware) in 3 to 5 minutes and makes a zip in the "
        "ezBMC_Logs folder in your WSL home directory. The zip has a viewer. Lab stand-in:  ezbmc <BMC_IP>",
    ],
    do=["cd {wd}", "Save the SEL, SDR and HMC logs for CT11, each named with the service tag.",
        "Run ezBMC against CT11.",
        "Read the HMC log. Write resolution.txt: which GPU, and which XID number?"],
    nudge="Three commands, three files, one name pattern: <ServiceTag>-sel.txt, -sdr.txt, -HMCevents.txt.",
    walk=["Find CT11's BMC IP and tag with `dclab rack`.", "Run the SEL command and pipe it to tee -a.",
          "Same for SDR.", "The HMC log is a curl to the Redfish EventLog URL, piped through jq, then tee -a.",
          "Run ezbmc with the BMC IP.", "Search the HMC file for XID."],
    show=SHOW_LOGS + ["ezbmc {ip}", "grep -i xid {tag}-HMCevents.txt",
                      "echo 'GPU_3 logged XID 121 (C2C bus error).' > resolution.txt"],
    setup=s103, check=c103)


# ============================================================== 104 leak alarm, old BMC
LEAK_TEACH = [
    "Leak errors will prevent power on. Drives flash amber, but the system powers off. The CT shows some "
    "boot, then stops.",
    "Leak sensors read OK between 1.70 and 1.75 volts.",
    "Sensor map: Ch0LeaDet0ColPla = M0_0, Cha0LeaDete0Mani = M0_1, Ch0LeaDet1ColPla = M1_0, "
    "Cha0LeaDete1Mani = M1_1.",
    "Remediation: verify the BMC revision (it needs to be above 25.09.30001500), check with a UV light "
    "(no coolant), clean the leak sensors. If a sensor is touching the cold plate, a zip tie can be used.",
]


def s104(st):
    ct = st["cts"]["CT07"]
    ct["fw"]["bmc"] = core.PKG["1.2.5"]["bmc"]
    ct["leak"]["M0_0"] = "falsealarm"
    failed_boot_history(ct)


def c104(x):
    ct = x.ct("CT07")
    logs_ok(x, ct)
    fw = x.acts("fwupdate", ct="CT07")
    logs_first(x, ct, fw, "the firmware change")
    x.c(f"BMC is on the site build {core.SITE_BMC}", ct["fw"]["bmc"] == core.SITE_BMC)
    x.c("The CT was powered off for the update", bool(fw) and all(a["power"] == "off" for a in fw))
    healthy(x, ct)
    resolution(x, ("ch0leadet0colpla", "m0_0"), ("0.66",), ("bmc",))
    no_viol(x)


register(
    tid="DCOPS-104", title="CT07 powers itself off (leak alarm)", track="GB200", ct="CT07",
    body="NOC: CT07 ({tag}, BMC {ip}) will not stay on. Drives flash amber, then the tray goes dark. "
         "The scheduler already drained it.",
    teach=LEAK_TEACH + [
        "Site firmware: see `dclab matrix`. The CT must be powered off for each update. A BMC update takes "
        "10 to 15 minutes.",
        "Read a firmware version from Redfish:  curl -sk -u admin:admin "
        "https://<BMC_IP>/redfish/v1/UpdateService/FirmwareInventory/BMC_Firmware | jq .Version",
        "Lab firmware tool:  tech fwupdate <CT> <bmc|bios|bianca|bf3> <version>",
    ],
    do=["cd {wd}", "Collect SEL, SDR and HMC logs first.",
        "Find the sensor that is out of range. Which position is it?",
        "Check the first item on the remediation list.",
        "Fix it, power the tray on, and confirm it stays on (SOL or power status after 10 s).",
        "Write resolution.txt: sensor name, reading, root cause, fix."],
    nudge="The remediation list starts with a version check, not with a screwdriver.",
    walk=["Collect the three logs.", "In the SDR file find the line with status cr.",
          "Read the BMC firmware version from Redfish (or `mc info`). Compare it with 25.09.30001500.",
          "Look up the site BMC build with `dclab matrix`.", "Confirm the tray is off, then update the BMC.",
          "Power on. Wait 10 seconds. Check power status and the SDR again."],
    show=SHOW_LOGS + ["grep ' cr ' {tag}-sdr.txt",
                      "curl -sk -u admin:admin https://{ip}/redfish/v1/UpdateService/FirmwareInventory/BMC_Firmware | jq .Version",
                      "dclab matrix", IPMI + " chassis power status",
                      "tech fwupdate CT07 bmc " + core.SITE_BMC, IPMI + " chassis power on",
                      "sleep 10; " + IPMI + " chassis power status",
                      IPMI + " sdr elist | tee -a {tag}-sdr.txt",
                      "echo 'Ch0LeaDet0ColPla (M0_0) read 0.66 V. BMC was below 25.09.30001500 (false leak "
                      "alarm). Updated BMC to " + core.SITE_BMC + " with the CT off. Sensor now 1.72 V.' > resolution.txt"],
    setup=s104, check=c104)


# ============================================================== 105 leak, sensor on cold plate
def s105(st):
    ct = st["cts"]["CT09"]
    ct["leak"]["M1_0"] = "contact"
    failed_boot_history(ct)


def c105(x):
    ct = x.ct("CT09")
    logs_ok(x, ct, ("sel", "sdr"))
    uv = x.acts("uv", ct="CT09")
    fix = x.acts("ziptie", ct="CT09") + x.acts("clean", ct="CT09")
    fix.sort(key=lambda a: a["t"])
    logs_first(x, ct, x.acts("pull", ct="CT09"), "you pulled the tray")
    x.c("UV light check done before you touched the sensor", x.before(x.first_t(uv), x.first_t(fix)))
    x.c("Sensor M1_0 cleaned", x.acts("clean", ct="CT09", sensor="M1_0"))
    x.c("Sensor M1_0 zip-tied off the cold plate", x.acts("ziptie", ct="CT09", sensor="M1_0"))
    sdr = x.read(f"{ct['tag']}-sdr.txt")
    x.c("SDR captured again after the fix (same file, tee -a) and M1_0 reads ok",
        any("Ch0LeaDet1ColPla" in l and "| cr" in l for l in sdr.splitlines())
        and any("Ch0LeaDet1ColPla" in l and "| ok" in l for l in sdr.splitlines()))
    x.c("No part was ordered (nothing to RMA)", not x.acts("case", ct="CT09") and not x.acts("replace", ct="CT09"))
    healthy(x, ct)
    resolution(x, ("cold plate", "zip"), ("m1_0", "ch0leadet1colpla"))
    no_viol(x)


register(
    tid="DCOPS-105", title="CT09 leak alarm, BMC already current", track="GB200", ct="CT09",
    body="CT09 ({tag}, BMC {ip}) shuts down with a leak alarm. Its BMC is already on the site build.",
    teach=LEAK_TEACH + [
        "Work inside a tray only on the bench:  tech pull <CT>, tech open <CT>, then tech close / tech insert.",
        "Lab hands:  tech uv <CT>,  tech inspect <CT> leak-sensors,  tech clean <CT> <M0_0..>,  "
        "tech ziptie <CT> <M0_0..>",
    ],
    do=["cd {wd}", "Collect SEL and SDR. Find the bad sensor and its position.",
        "Confirm the BMC revision is not the cause.",
        "Pull the tray, open it, and work down the remediation list in order.",
        "Close, insert, power on. Append a fresh SDR to the same file to prove the reading is ok.",
        "Write resolution.txt."],
    nudge="No coolant under UV means the sensor itself is the problem. Look at what it touches.",
    walk=["Logs first.", "BMC version: already above 25.09.30001500, so move on.",
          "Pull and open the tray.", "UV light before anything else.",
          "Inspect the leak sensors and find the one on the cold plate.",
          "Clean it, then zip-tie it.", "Close, insert, power on, wait 10 s, SDR again with tee -a."],
    show=["cd {wd}", IPMI + " sel -v list | tee -a {tag}-sel.txt", IPMI + " sdr elist | tee -a {tag}-sdr.txt",
          "curl -sk -u admin:admin https://{ip}/redfish/v1/UpdateService/FirmwareInventory/BMC_Firmware | jq .Version",
          "tech pull CT09", "tech open CT09", "tech uv CT09", "tech inspect CT09 leak-sensors",
          "tech clean CT09 M1_0", "tech ziptie CT09 M1_0", "tech close CT09", "tech insert CT09",
          IPMI + " chassis power on", "sleep 10; " + IPMI + " sdr elist | tee -a {tag}-sdr.txt",
          "echo 'Ch0LeaDet1ColPla (M1_0) read 0.66 V. No coolant under UV. Sensor was touching the cold "
          "plate. Cleaned it and zip-tied it clear. Now 1.72 V.' > resolution.txt"],
    setup=s105, check=c105)


# ============================================================== 106 busbar
NOPOWER_TEACH = [
    "Causes of no power: voltage errors, leak detection errors, HMC, PDB.",
    "Voltage errors can be caused by the internal busbar not being torqued down properly. Open the CT, get "
    "down to the busbar, loosen ALL the screws, and re-torque them to 20 in-lb in this order: back, front, "
    "middle.",
    "HMC: reseat the slimline cables and the card.",
    "PDB: inspect and gather logs. HMC logs will show errors.",
]


def s106(st):
    ct = st["cts"]["CT12"]
    ct["busbar_fault"] = True
    failed_boot_history(ct)


def c106(x):
    ct = x.ct("CT12")
    logs_ok(x, ct, ("sel", "sdr"))
    logs_first(x, ct, x.acts("pull", ct="CT12"), "you pulled the tray")
    x.c("Busbar: loosened all screws, then 20 in-lb back, front, middle",
        ct["busbar_log"] == ["loosen-all", "back@20", "front@20", "middle@20"])
    healthy(x, ct)
    resolution(x, ("busbar", "bus bar"), ("20",))
    no_viol(x)


register(
    tid="DCOPS-106", title="CT12 no power (voltage errors)", track="GB200", ct="CT12",
    body="CT12 ({tag}, BMC {ip}) will not power on. The SEL shows voltage events.",
    teach=NOPOWER_TEACH + ["Lab hands:  tech loosen <CT> busbar,  tech torque <CT> busbar --section "
                           "<back|front|middle> --inlb <N>"],
    do=["cd {wd}", "Collect SEL and SDR. Find which voltage is out of range.",
        "Pull and open the tray. Inspect the area that matches.", "Do the repair exactly as taught.",
        "Close, insert, power on, confirm.", "Write resolution.txt."],
    nudge="The order and the torque value both matter. Loosen everything first.",
    walk=["Logs first. The SDR shows P54V_BUSBAR critical.", "Pull, open, inspect the busbar.",
          "Loosen all the busbar screws.", "Torque back, then front, then middle. Use 20 in-lb each time.",
          "Close, insert, power on, check after 10 s."],
    show=["cd {wd}", IPMI + " sel -v list | tee -a {tag}-sel.txt", IPMI + " sdr elist | tee -a {tag}-sdr.txt",
          "tech pull CT12", "tech open CT12", "tech inspect CT12 busbar", "tech loosen CT12 busbar",
          "tech torque CT12 busbar --section back --inlb 20", "tech torque CT12 busbar --section front --inlb 20",
          "tech torque CT12 busbar --section middle --inlb 20", "tech close CT12", "tech insert CT12",
          IPMI + " chassis power on", "sleep 10; " + IPMI + " chassis power status",
          "echo 'P54V_BUSBAR low. Internal busbar was not torqued. Loosened all screws and re-torqued to 20 "
          "in-lb: back, front, middle.' > resolution.txt"],
    setup=s106, check=c106)


# ============================================================== 107 HMC
def s107(st):
    ct = st["cts"]["CT04"]
    ct["hmc_fault"] = True
    failed_boot_history(ct)


def c107(x):
    ct = x.ct("CT04")
    logs_ok(x, ct, ("sel", "sdr"))
    logs_first(x, ct, x.acts("pull", ct="CT04"), "you pulled the tray")
    x.c("Reseated the HMC slimline cables", x.acts("reseat", ct="CT04", part="hmc-slimline-cables"))
    x.c("Reseated the HMC card", x.acts("reseat", ct="CT04", part="hmc-card"))
    x.c(f"HMC log collected after the fix ({ct['tag']}-HMCevents.txt has entries)",
        x.grep(f"{ct['tag']}-HMCevents.txt", r'"Members"'))
    healthy(x, ct)
    resolution(x, ("hmc",), ("reseat", "slimline"))
    no_viol(x)


register(
    tid="DCOPS-107", title="CT04 no power (HMC)", track="GB200", ct="CT04",
    body="CT04 ({tag}, BMC {ip}) will not power on. Leak sensors and the busbar look fine.",
    teach=NOPOWER_TEACH + LOGCMDS[2:] + ["Lab hands:  tech reseat <CT> hmc-slimline-cables,  tech reseat <CT> hmc-card"],
    do=["cd {wd}", "Collect SEL and SDR. Try the HMC log too and read what comes back.",
        "Pull, open, and do the HMC repair.", "Close, insert, power on.",
        "Collect the HMC log again. This time it must have entries.", "Write resolution.txt."],
    nudge="When the HMC log command returns an error instead of entries, that error is your evidence.",
    walk=["Logs. The SDR shows HMC_Status critical.", "The Redfish HMC URL answers 503.",
          "Pull and open the tray.", "Reseat the slimline cables and the card.", "Close, insert, power on.",
          "Run the HMC log command again with tee -a."],
    show=["cd {wd}", IPMI + " sel -v list | tee -a {tag}-sel.txt", IPMI + " sdr elist | tee -a {tag}-sdr.txt",
          SHOW_LOGS[3], "tech pull CT04", "tech open CT04", "tech reseat CT04 hmc-slimline-cables",
          "tech reseat CT04 hmc-card", "tech close CT04", "tech insert CT04", IPMI + " chassis power on",
          "sleep 10; " + SHOW_LOGS[3],
          "echo 'HMC not responding (503, HMC_Status critical). Reseated the HMC slimline cables and card.' > resolution.txt"],
    setup=s107, check=c107)


# ============================================================== 108 CX-7 RoCE links
LIVE_TEACH = [
    "Support Live Image (bootable USB): the Valet script auto-runs (5 to 10 minutes) and collects "
    "mlxlink_info, which checks the state and health of the network ports.",
    "Tidbit: plug the USB drive in before you type `exit` at Shell> and the tray boots from USB. No restart "
    "needed. F11 during POST also opens the Boot Override Menu.",
    "In the live image:  mlxlink -d mlx5_0 ... mlx5_3 = ConnectX-7 mezz ports 1 to 4,  mlx5_4 = BlueField-3.",
    "Lab hands:  tech usb <CT> insert|remove.  Record your SOL session with `script` so the output is saved.",
]


def s108(st):
    ct = st["cts"]["CT14"]
    ct["pxe_target"] = False
    ct["osfp"]["3"].update(foam=False, tension=False)
    ct["osfp"]["4"].update(pins=False)
    parked_at_shell(ct)


def c108(x):
    ct = x.ct("CT14")
    v = x.acts("valet", ct="CT14")
    fixes = x.acts("reseat", ct="CT14") + x.acts("torque", ct="CT14") + x.acts("replace", ct="CT14")
    fixes.sort(key=lambda a: a["t"])
    x.c("Live image booted and Valet ran before the repair", x.before(x.first_t(v), x.first_t(fixes)))
    x.c(f"SOL session recorded in {ct['tag']}-sol.txt", x.grep(f"{ct['tag']}-sol.txt", r"Valet|mlxlink"))
    o3, o4 = ct["osfp"]["3"], ct["osfp"]["4"]
    x.c("Port 3: foam pad back in place and tension bar torqued", o3["foam"] and o3["tension"])
    x.c("Port 4: OSFP header cable with bent pins replaced", o4["pins"])
    x.c("Valet run after the repair shows all four ports Active",
        bool(v) and x.before(x.last_t(fixes), v[-1]["t"]) and all(s == "Active" for s in v[-1]["ports"].values()))
    resolution(x, ("foam",), ("tension",), ("pin",))
    no_viol(x)


register(
    tid="DCOPS-108", title="CT14 RoCE links down (ConnectX-7)", track="GB200", ct="CT14",
    body="Network team: two RoCE links on CT14 ({tag}, BMC {ip}) are down. The tray is drained and is "
         "sitting at Shell>.",
    teach=[
        "ConnectX-7/8 (RoCE) issues: OSFP cables to the mezz not seated properly. Causes: tension bar not "
        "torqued down correctly, foam pad not in the correct location, pins on the OSFP header cable are bent.",
        "Also check: OSFP cables connected to the wrong mezz port, and power cables properly connected at "
        "the OSFP header.",
    ] + LIVE_TEACH + [
        "Lab hands:  tech inspect <CT> osfp,  tech reseat <CT> foam-pad --port N,  tech torque <CT> "
        "tension-bar --port N,  tech replace <CT> osfp-cable --port N",
    ],
    do=["cd {wd}", "Record a SOL session to {tag}-sol.txt and boot the Support Live Image on CT14.",
        "Let Valet finish. Find which ports are down (mlxlink_info, or mlxlink -d).",
        "Shut the tray down cleanly from the live image, leave SOL, pull and open the tray.",
        "Inspect the OSFP area and repair every finding.",
        "Put the tray back, boot the live image again, and prove all four ports are Active.",
        "Write resolution.txt with what you found on each port."],
    nudge="Two ports are down for two different physical reasons. Inspect before you fix.",
    walk=["script, then sol activate. Press Enter to see Shell>.",
          "From window 2 insert the USB. In SOL type exit. Wait for the live image prompt.",
          "cat valet/mlxlink_info.txt. Ports 3 and 4 are Polling.", "poweroff, then Enter and ~. to leave SOL.",
          "Pull, open, inspect osfp.", "Port 3: foam pad and tension bar. Port 4: replace the cable.",
          "Close, insert, power on with SOL open. At Shell> type exit to boot the USB again."],
    show=["cd {wd}", "script {tag}-sol.txt", IPMI + " sol activate", "# window 2:  tech usb CT14 insert",
          "# SOL: press Enter, then at Shell> type  exit", "# live image:  cat valet/mlxlink_info.txt",
          "# live image:  mlxlink -d mlx5_2      then  poweroff      then Enter and ~.",
          "tech pull CT14", "tech open CT14", "tech inspect CT14 osfp", "tech reseat CT14 foam-pad --port 3",
          "tech torque CT14 tension-bar --port 3", "tech replace CT14 osfp-cable --port 4", "tech close CT14",
          "tech insert CT14", IPMI + " sol activate", "# window 2:  " + IPMI + " chassis power on",
          "# SOL at Shell> :  exit    -> Valet runs again, all ports Active.  poweroff is not needed now.",
          "# leave with Enter ~.  then  exit  to stop script",
          "echo 'Port 3: foam pad out of place and tension bar loose. Port 4: bent pins on the OSFP header "
          "cable, replaced. All four ports Active after.' > resolution.txt"],
    setup=s108, check=c108)


# ============================================================== 109 BF3 PXE, card visible
BF3_TEACH = [
    "BlueField-3 issue: PXE boot fails.",
    "If the port shows connected in the BIOS and in the mlxlink_info output in Valet: update the BF3 "
    "firmware to v1.3 or above.",
    "If the BF3 does not show up in the BIOS or in mlxlink_info in Valet: pull the HMC log and let support "
    "check for PCI errors. They will provide replacement parts or a new POA (plan of action).",
]


def s109(st):
    ct = st["cts"]["CT16"]
    ct["fw"]["bf3"] = "1.2.0"
    parked_at_shell(ct)


def c109(x):
    ct = x.ct("CT16")
    seen = [s["m"] for s in ct["seen"]]
    x.c("You confirmed the BF3 is visible (BIOS with F2, or Valet mlxlink_info)",
        "bios_view" in seen or any(a.get("bf3") for a in x.acts("valet", ct="CT16")))
    x.c("You read the BF3 firmware version from Redfish", x.redfish("CT16", "BF3_Firmware"))
    fw = x.acts("fwupdate", ct="CT16", comp="bf3")
    x.c("BF3 firmware is v1.3 or above", core.vt(ct["fw"]["bf3"]) >= (1, 3))
    x.c("The CT was powered off for the update", bool(fw) and all(a["power"] == "off" for a in fw))
    x.c("You watched PXE succeed over SOL", "pxe_ok" in seen)
    resolution(x, ("1.3",), ("bf3", "bluefield"))
    no_viol(x)


register(
    tid="DCOPS-109", title="CT16 PXE boot fails", track="GB200", ct="CT16",
    body="Provisioning: CT16 ({tag}, BMC {ip}) never PXE boots. It ends at Shell> every time.",
    teach=BF3_TEACH + [
        "Read it from Redfish:  curl -sk -u admin:admin "
        "https://<BMC_IP>/redfish/v1/UpdateService/FirmwareInventory/BF3_Firmware | jq",
        "The CT must be powered off for each firmware update.  tech fwupdate <CT> bf3 <version>",
        "F2 during POST opens BIOS setup, which lists the PCIe devices (over SOL you can also type ESC then 2).",
    ],
    do=["cd {wd}", "Find out whether the BF3 is visible: BIOS (F2 during POST) or Valet mlxlink_info.",
        "Read the BF3 firmware version from Redfish.", "Apply the matching fix from the two cases you were taught.",
        "Power on with SOL open and watch PXE succeed.", "Write resolution.txt."],
    nudge="The card is there. So the question is its version.",
    walk=["Open SOL in window 1. Power-cycle from window 2. Press F2 when the prompt shows.",
          "BIOS lists the BlueField-3 as Present. ESC to continue.", "Query BF3_Firmware in Redfish with curl and jq.",
          "Soft power off, update bf3 to the version in `dclab matrix`.", "Power on with SOL open."],
    show=["cd {wd}", IPMI + " sol activate", "# window 2:  " + IPMI + " chassis power cycle",
          "# SOL: press F2 at the prompt, read the PCIe list, ESC",
          "curl -sk -u admin:admin https://{ip}/redfish/v1/UpdateService/FirmwareInventory/BF3_Firmware | jq",
          IPMI + " chassis power soft", "tech fwupdate CT16 bf3 " + core.BF3_OK, IPMI + " chassis power on",
          "# SOL shows PXE download and the provisioning hand-off. Leave with Enter ~.",
          "echo 'BF3 present in BIOS but on firmware 1.2.0. Updated BF3 to " + core.BF3_OK + " (v1.3 or above) "
          "with the CT off. PXE now boots.' > resolution.txt"],
    setup=s109, check=c109)


# ============================================================== 110 BF3 missing
def s110(st):
    ct = st["cts"]["CT17"]
    ct["bf3_present"] = False
    core.add_hmc(ct, "The resource property BlueField3_0 PCIe link has detected errors of type 'PCIe link "
                     "training failure: link down on Root Port 0006:00:00.0'.",
                 ["BlueField3_0 PCIe link", "PCIe link training failure: link down on Root Port 0006:00:00.0"],
                 resolution="Collect logs and contact support.", t=time.time() - 3000)
    ct["support"] = {"needs": ["BlueField3", "PCIe"], "part": "bf3",
                     "reply": "PCI errors confirmed on the BlueField-3 (link training failure). Replace the card."}
    parked_at_shell(ct)


def c110(x):
    ct = x.ct("CT17")
    seen = [s["m"] for s in ct["seen"]]
    x.c("You confirmed the BF3 is missing (BIOS with F2, or Valet mlxlink_info)",
        "bios_view" in seen or bool(x.acts("valet", ct="CT17")))
    x.c(f"HMC log saved in {ct['tag']}-HMCevents.txt with the PCI error", x.grep(f"{ct['tag']}-HMCevents.txt", "PCIe"))
    case = x.st["cases"].get("CT17")
    x.c("Support case opened with the HMC log attached; work order received", case is not None)
    rep = x.acts("replace", ct="CT17", fru="bf3")
    x.c("BF3 replaced only after support sent the part", bool(rep) and case is not None and rep[0]["t"] > case["t"])
    x.c("No firmware update tried on a card that was not there",
        not [a for a in x.acts("fwupdate", ct="CT17", comp="bf3") if not rep or a["t"] < rep[0]["t"]])
    x.c("CT17 is on and can PXE boot", ct["power"] == "on" and ct["location"] == "rack" and core.pxe_ok(ct))
    resolution(x, ("hmc",), ("pci",), ("support", "work order", "wo-", "poa"))
    no_viol(x)


register(
    tid="DCOPS-110", title="CT17 PXE boot fails (again?)", track="GB200", ct="CT17",
    body="Provisioning: CT17 ({tag}, BMC {ip}) never PXE boots either. Same symptom as CT16.",
    teach=BF3_TEACH + LOGCMDS[2:] + [
        "Lab support desk:  tech case <CT> --attach <file> [more files]   then follow their answer.  "
        "tech receive <CT>,  tech replace <CT> bf3",
    ],
    do=["cd {wd}", "Check whether the BF3 is visible in BIOS or in Valet mlxlink_info.",
        "Do what the matching case says. Save the log named with the service tag.",
        "Follow the support answer.", "Power on and confirm PXE boots.", "Write resolution.txt."],
    nudge="Same symptom, different case. If the card is not there, firmware is not the fix.",
    walk=["SOL + power cycle + F2: BlueField-3 shows Not Detected.", "Pull the HMC log with curl | jq | tee -a.",
          "Open a support case and attach that file.", "Support opens a Part Only work order.",
          "Soft off, pull, open, replace the BF3, close, insert, power on."],
    show=["cd {wd}", IPMI + " sol activate", "# window 2:  " + IPMI + " chassis power cycle   (F2 in SOL, then ESC, then Enter ~.)",
          SHOW_LOGS[3], "tech case CT17 --attach {tag}-HMCevents.txt", "tech receive CT17",
          IPMI + " chassis power soft", "tech pull CT17", "tech open CT17", "tech replace CT17 bf3",
          "tech close CT17", "tech insert CT17", IPMI + " chassis power on",
          "echo 'BF3 not detected in BIOS. HMC log shows a PCIe link training failure. Support opened a "
          "Part Only work order; replaced the BF3. PXE boots.' > resolution.txt"],
    setup=s110, check=c110)


# ============================================================== 111 CT swap and RMA
def s111(st):
    ct = st["cts"]["CT05"]
    now = time.time()
    txt = "C2C BUS ERROR: Link Idx: 7; STATUS_REG: 0x00000020"
    for ago in (9000, 5400, 1800):
        core.xid_event(ct, 3, 121, txt, t=now - ago)
    core.add_hmc(ct, "The resource property GPU_3 Row Remapping has detected errors of type 'Row remapping "
                     "failure: no spare rows left'.", ["GPU_3 Row Remapping", "Row remapping failure"], t=now - 1700)
    ct["gpu_xid"] = [{"gpu": 3, "xid": 121, "text": txt}]
    ct["remap_fail"] = 3
    ct["support"] = {"needs": ["XID 121"], "part": "ct",
                     "reply": "All POAs are exhausted on this tray (Bianca board / GPU fault). A replacement "
                              "compute tray ships today."}


def c111(x):
    ct = x.ct("CT05")
    g = x.acts("graceful", ct="CT05")
    t_logs = x.first_t(x.acts("ezbmc", ct="CT05")) or x.first_t(x.ipmi("CT05", "sel", "sdr"))
    hm = x.redfish("CT05", "EventLog")
    if hm and (t_logs is None or hm[0]["t"] < t_logs):
        t_logs = hm[0]["t"]
    x.c("Logs collected before the tray was shut down", x.before(t_logs, x.first_t(g)))
    x.c("Graceful (ACPI) shutdown used on a tray in a production job", bool(g))
    x.c("Tray moved from the production rack to the hospital", ct["rack"] == core.HOSP)
    case = x.st["cases"].get("CT05") or {}
    x.c("Support opened a Part Only work order for a replacement CT", case.get("part") == "ct")
    x.c("Replacement tray received", bool(case.get("new")))
    for item in ("handles", "rails", "drives-internal", "drives-front"):
        x.c(f"Moved to the replacement: {item}", item in case.get("moved", []))
    sf = x.st.get("swap_form") or {}
    x.c("Swap form submitted with the old tag, new tag and work order",
        sf.get("old") == ct["tag"] and sf.get("new") == case.get("new") and sf.get("wo") == case.get("wo"))
    resolution(x, ("xid", "ecc", "remap", "bianca", "gpu"), ("hospital",), ("swap",))
    no_viol(x)


register(
    tid="DCOPS-111", title="CT05 GPU fault: CT swap and RMA", track="GB200", ct="CT05",
    body="CT05 ({tag}, BMC {ip}) keeps logging GPU errors and is IN A RUNNING JOB. Support says every "
         "troubleshooting step is done and the issue persists. Healthy trays are in the hospital rack.",
    teach=[
        "Sometimes we cannot fix the CT: issues with the Bianca board (GPUs, memory, CPUs, CX7/8 mezz) "
        "after all troubleshooting steps are done and the issue persists.",
        "If the CT is in production AND there are healthy CTs in the hospital, move the CT from the "
        "production rack to the hospital for any following POAs or to be replaced.",
        "Support opens a 'Part Only' work order and gets a replacement CT shipped in.",
        "When the replacement CT arrives, move these parts from the defective CT to the replacement: "
        "handles, rails, drives (internal drive only and the front drives). Then submit the swap form.",
        "Hard powering off or pulling a CT in a rack that is running production breaks the NVLink fabric "
        "and may need a manual job restart. Do a graceful shutdown: ACPI shutdown in the BMC power options "
        "(IPMI: chassis power soft).",
        "The NVIDIA bug report checks GPU health at a snapshot level: remapped rows and ECC errors.",
        "Lab hands:  tech move <CT> hospital,  tech case,  tech receive,  tech transfer <CT> <item>,  "
        "tech swap-form --old <tag> --new <tag> --wo <WO>",
    ],
    do=["cd {wd}", "Collect logs (ezBMC or the three files) while the tray is still up.",
        "Shut the tray down the right way for a production rack.",
        "Pull it and move it to the hospital rack (insert it there).",
        "Open a support case with your logs. Receive what they ship.",
        "Pull the tray in the hospital and move every required part to the replacement.",
        "Submit the swap form.", "Write resolution.txt."],
    nudge="Production rack: the shutdown method is the whole point. Then it is a parts-transfer checklist.",
    walk=["ezbmc first.", "chassis power soft, then confirm it is off.", "tech pull, tech move ... hospital, tech insert.",
          "tech case with the ezBMC zip (or the HMC log).", "tech receive: note the new service tag.",
          "tech pull again, then four transfers.", "tech swap-form with old tag, new tag, work order."],
    show=["cd {wd}", "ezbmc {ip}", IPMI + " chassis power soft", IPMI + " chassis power status",
          "tech pull CT05", "tech move CT05 hospital", "tech insert CT05",
          "tech case CT05 --attach ~/ezBMC_Logs/{tag}_*.zip", "tech receive CT05", "tech pull CT05",
          "tech transfer CT05 handles", "tech transfer CT05 rails", "tech transfer CT05 drives-internal",
          "tech transfer CT05 drives-front", "tech swap-form --old {tag} --new <NEW_TAG> --wo <WO-number>",
          "echo 'GPU_3 XID 121 and row remap failure, all POAs done. Graceful shutdown, moved to hospital, "
          "Part Only WO, moved handles, rails and drives to the replacement, swap form submitted.' > resolution.txt"],
    setup=s111, check=c111)


# ============================================================== 112 firmware compliance
def s112(st):
    ct = st["cts"]["CT02"]
    ct["fw"].update(core.PKG["1.2.5"])
    ct["in_job"] = False


def c112(x):
    ct = x.ct("CT02")
    fw = x.acts("fwupdate", ct="CT02")
    for comp in core.FW_ORDER:
        x.c(f"CT02 {comp} is on the site build {core.SITE[comp]}", ct["fw"][comp] == core.SITE[comp])
    x.c("CT02 was powered off for every update", bool(fw) and all(a["power"] == "off" for a in fw))
    order = [a["comp"] for a in fw if a["to"] == core.SITE.get(a["comp"])]
    x.c("Update order was BMC, then BIOS, then Bianca", order[:3] == core.FW_ORDER)
    x.c("CT08 was left alone (no downgrade attempt)", not x.acts("fwupdate", ct="CT08"))
    healthy(x, ct)
    resolution(x, ("downgrade",), ("cannot", "can't", "can not", "not possible", "never", "not allowed", "no "))
    no_viol(x)


register(
    tid="DCOPS-112", title="CT02 firmware out of matrix (+ a request)", track="GB200", ct="CT02",
    body="CT02 ({tag}, BMC {ip}) came back from the hospital on old firmware. Bring it to the site "
         "matrix. Comment from eng-jlee: 'While you are there, downgrade CT08 to 1.2.5 so we can repro a bug.'",
    teach=[
        f"Firmware matrix at {core.SITE_NAME} (GB200): 1.3.6 in all data halls, but BMC 26.01.10001500.",
        "Standard firmware matrix (GB200): once a CT is on the 1.3.6 package it CAN NOT be downgraded.",
        "There is an order to updating CT firmware: BMC (10 to 15 min), then BIOS (roughly 15 min), then "
        "Bianca (45 min to 1 h 30 min).",
        "The CT should be powered off for each update.",
        "`dclab matrix` shows the builds.  tech fwupdate <CT> <bmc|bios|bianca> <version>",
    ],
    do=["cd {wd}", "Read CT02's current versions (Redfish firmware inventory).",
        "Update CT02 to the site matrix, in the right order and power state.", "Power CT02 back on.",
        "Decide what to do about the CT08 request.", "Write resolution.txt with your answer to eng-jlee and why."],
    nudge="Site matrix is not the standard matrix: check the BMC build. And one request must be refused.",
    walk=["List FirmwareInventory members with curl | jq.", "Soft power off CT02.",
          "bmc to the SITE build, then bios, then bianca.", "Power on.",
          "CT08 is on 1.3.6, so it cannot be downgraded. Say so."],
    show=["cd {wd}", "for f in BMC BIOS Bianca; do curl -sk -u admin:admin https://{ip}/redfish/v1/UpdateService/FirmwareInventory/${f}_Firmware | jq -r '.Id+\" \"+.Version'; done",
          "dclab matrix", IPMI + " chassis power soft", "tech fwupdate CT02 bmc " + core.SITE["bmc"],
          "tech fwupdate CT02 bios " + core.SITE["bios"], "tech fwupdate CT02 bianca " + core.SITE["bianca"],
          IPMI + " chassis power on",
          "echo 'CT02 updated to site matrix: BMC, BIOS, Bianca, powered off each time. CT08 is on 1.3.6 "
          "and cannot be downgraded, so that request is declined.' > resolution.txt"],
    setup=s112, check=c112)


# ============================================================== 113 fan swap in a live rack
def s113(st):
    ct = st["cts"]["CT10"]
    ct["fan_fail"] = 3
    core.add_sel(ct, "Fan", "Fan3", core.sensor_num("Fan3"), "Lower Critical going low", reading=0.0, thr=1000.0,
                 unit="RPM", t=time.time() - 1200)


def c113(x):
    ct = x.ct("CT10")
    g = x.acts("graceful", ct="CT10")
    logs_ok(x, ct, ("sel", "sdr"))
    logs_first(x, ct, g, "the shutdown")
    x.c("Graceful (ACPI) shutdown used; no hard power off", bool(g) and g[0].get("was_in_job"))
    st_checks = [a for a in x.ipmi("CT10", "chassis power status", "power status") if g and a["t"] > g[0]["t"]]
    x.c("Power state confirmed off before you pulled the tray",
        bool(st_checks) and x.before(st_checks[0]["t"], x.first_t(x.acts("pull", ct="CT10"))))
    x.c("Fan replaced", x.acts("replace", ct="CT10", fru="fan") and ct["fan_fail"] is None)
    healthy(x, ct)
    resolution(x, ("graceful", "acpi", "soft"), ("nvlink", "fabric"))
    no_viol(x)


register(
    tid="DCOPS-113", title="CT10 fan failed, rack is running a job", track="GB200", ct="CT10",
    body="CT10 ({tag}, BMC {ip}) has a failed fan. Rack R12 is running a production job and CT10 is part of it.",
    teach=[
        "Hard powering off (holding down the power button) or pulling a CT in a rack that is running "
        "production will break the NVLink network fabric and might require a manual restart of the job.",
        "Even when the CT is not part of the running job, it still belongs to the internal fabric.",
        "A graceful shutdown of the CT should be done: ACPI shutdown in the GB200 power options in the BMC. "
        "With IPMI that is `chassis power soft`.",
        "Fans are a FRU part for the compute tray.  tech replace <CT> fan",
    ],
    do=["cd {wd}", "Collect SEL and SDR and find the failed fan.", "Shut CT10 down the right way.",
        "Confirm it is off before you touch it.", "Pull, open, replace the fan, close, insert, power on.",
        "Write resolution.txt: which shutdown you used and why."],
    nudge="There are three ways to turn a tray off. Only one is safe in a running rack.",
    walk=["Logs first: Fan3 reads 0 RPM.", "chassis power soft.", "chassis power status until it says off.",
          "tech pull, open, replace fan, close, insert.", "chassis power on."],
    show=["cd {wd}", IPMI + " sel -v list | tee -a {tag}-sel.txt", IPMI + " sdr elist | tee -a {tag}-sdr.txt",
          IPMI + " chassis power soft", IPMI + " chassis power status", "tech pull CT10", "tech open CT10",
          "tech replace CT10 fan", "tech close CT10", "tech insert CT10", IPMI + " chassis power on",
          "echo 'Fan3 failed. Used a graceful ACPI shutdown (chassis power soft) because a hard power off or "
          "pulling a live CT breaks the NVLink fabric and the job. Replaced the fan.' > resolution.txt"],
    setup=s113, check=c113)


# ============================================================== 114 BMC FRU
def s114(st):
    ct = st["cts"]["CT13"]
    ct["bmc_state"] = "dead"
    ct["in_job"] = False
    ct["power"] = "off"
    ct["power_t"] = time.time() - 4000
    st["spares"]["bmc"] = 1


def c114(x):
    ct = x.ct("CT13")
    x.c("BMC replaced", x.acts("replace", ct="CT13", fru="bmc"))
    fx = [a for a in x.acts("fixbmc", ct="CT13") if a["power"] == "off"]
    on = [a for a in x.ipmi("CT13", "chassis power on", "power on")] + x.acts("power_button", ct="CT13")
    x.c("fixBMC.sh run before the CT was powered on", bool(fx) and ct["bmc_state"] == "ok")
    fw = x.acts("fwupdate", ct="CT13", comp="bmc")
    x.c(f"New BMC brought to the site build {core.SITE_BMC}", ct["fw"]["bmc"] == core.SITE_BMC)
    x.c("The CT was powered off for the BMC update", bool(fw) and all(a["power"] == "off" for a in fw))
    healthy(x, ct)
    resolution(x, ("fixbmc",), ("before",))
    no_viol(x)


register(
    tid="DCOPS-114", title="CT13 BMC is dead (FRU replacement)", track="GB200", ct="CT13",
    body="CT13 ({tag}, BMC {ip}) is off and its BMC does not answer. A spare BMC is on site.",
    teach=[
        "FRU parts for the compute tray: the whole CT, M.2 riser/drive, NVMe drives, backplane, control "
        "panel, OSFP headers, LOM, BMC, HMC, PDB / PDB heatsink, IPEX (GB200 only), BlueField-3, fans, "
        "various cables, CMOS battery.",
        "BMC: the fixBMC.sh script needs to be run before powering on the CT.",
        "A spare can ship with old firmware. Bring it to the site matrix (BMC update: CT powered off).",
        "Lab hands:  tech replace <CT> bmc,  tech run <CT> fixBMC.sh",
    ],
    do=["cd {wd}", "Prove the BMC is unreachable (run any ipmitool command and read the error).",
        "Pull, open, replace the BMC, close, insert.", "Do the step that must come before power-on.",
        "Check the new BMC's firmware and fix it if needed.", "Power on and confirm.", "Write resolution.txt."],
    nudge="A new BMC does not know which tray it is in yet. One script fixes that, and timing matters.",
    walk=["ipmitool fails with 'Unable to establish IPMI v2 / RMCP+ session'.", "Pull, open, replace bmc, close, insert.",
          "Run fixBMC.sh while the host is still off.", "Read BMC_Firmware in Redfish; it is an old build.",
          "Update the BMC to the site build, then power on."],
    show=["cd {wd}", IPMI + " chassis power status", "tech pull CT13", "tech open CT13", "tech replace CT13 bmc",
          "tech close CT13", "tech insert CT13", "tech run CT13 fixBMC.sh",
          "curl -sk -u admin:admin https://{ip}/redfish/v1/UpdateService/FirmwareInventory/BMC_Firmware | jq .Version",
          "tech fwupdate CT13 bmc " + core.SITE_BMC, IPMI + " chassis power on",
          "echo 'BMC dead, replaced the BMC FRU. Ran fixBMC.sh before powering on. Updated the new BMC to "
          + core.SITE_BMC + ".' > resolution.txt"],
    setup=s114, check=c114)


# ============================================================== 115 NVLink switch
def s115(st):
    st["switches"]["SW4"]["state"] = "offline"
    st["fabric"] = "DOWN (SW4 offline)"
    for ct in st["cts"].values():
        ct["in_job"] = False
    st["switches"]["SWNEW"] = {"tag": core.svc_tag("spare-switch"), "model": "N5200", "state": "boxed",
                               "slot": None, "reset": False}


def c115(x):
    sws = x.st["switches"]
    kv = x.kv("tags.txt")
    x.c("tags.txt has the failed switch tag (SW4=...)", kv.get("sw4", "").upper() == sws["SW4"]["tag"])
    x.c("tags.txt has the spare switch tag (SWNEW=...)", kv.get("swnew", "").upper() == sws["SWNEW"]["tag"])
    rs = x.acts("switch", sw="SWNEW", action="factory-reset")
    ins = x.acts("switch", sw="SWNEW", action="install")
    x.c("Spare was factory reset before it went into the rack", x.before(x.first_t(rs), x.first_t(ins)))
    x.c("SW4 removed, spare online in slot 4", sws["SW4"]["state"] == "removed" and sws["SWNEW"]["state"] == "online"
        and sws["SWNEW"]["slot"] == 4)
    x.c("NVLink fabric is back", x.st["fabric"] == "ok")
    resolution(x, ("whole rack", "entire rack", "halt", "all production", "all 18", "every tray"),
               ("switch 1", "sw1"), ("primary", "master"))
    no_viol(x)


register(
    tid="DCOPS-115", title="NVLink switch SW4 offline", track="GB200", ct=None,
    body="Rack R12 stopped all work. `tech look SW4` shows the switch offline. A spare switch tray "
         "(SWNEW) is on site. It came out of another rack.",
    teach=[
        "One NVLink switch offline will halt production on the whole rack.",
        "Switches must be factory reset before going into production racks, else ZTP will fail.",
        "Switch 1 is the primary or master switch.",
        "Architecture: 9 NVLink switch trays, 2 ASICs per tray, so 9 physical switches make 18 logical "
        "switches. 144 ACP links run through the cable cartridges.",
        "NVLink switch service tag: bottom of the luggage tag, bottom right (N5200) or right side (N5600).",
        "Lab hands:  tech switch <SW> status | factory-reset | remove | install --slot N",
    ],
    do=["cd {wd}", "Look at SW4 and SWNEW. Record both service tags in tags.txt (SW4=..., SWNEW=...).",
        "Prepare the spare the way a production rack needs.", "Swap it into slot 4 and confirm it comes online.",
        "Write resolution.txt: how urgent is one switch down and why, and which switch is the primary?"],
    nudge="The spare still carries its old rack's config. What must happen before ZTP can work?",
    walk=["tech look SW4 / SWNEW for the model.", "tech tag with the spot for an N5200.",
          "Factory reset the spare first.", "Remove SW4, install SWNEW in slot 4.", "tech look RACK shows the fabric."],
    show=["cd {wd}", "tech look SW4", "tech tag SW4 luggage-tag-bottom-right", "tech tag SWNEW luggage-tag-bottom-right",
          "nano tags.txt    # SW4=...  SWNEW=...", "tech switch SWNEW factory-reset", "tech switch SW4 remove",
          "tech switch SWNEW install --slot 4", "tech look RACK",
          "echo 'One NVLink switch offline halts production on the whole rack, so this is top priority. "
          "Factory reset the spare so ZTP works. Switch 1 is the primary.' > resolution.txt"],
    setup=s115, check=c115)
