"""Support Live Image shell (booted from USB). Valet, mlxlink, nvidia-smi, lspci, dmesg."""
import os
import re
import shlex
import time

import core

GPU_BUS = ["0008:01:00.0", "0009:01:00.0", "0018:01:00.0", "0019:01:00.0"]
DEVS = {"mlx5_0": "1", "mlx5_1": "2", "mlx5_2": "3", "mlx5_3": "4", "mlx5_4": "bf3",
        "/dev/mst/mt4129_pciconf0": "1", "/dev/mst/mt4129_pciconf1": "2", "/dev/mst/mt4129_pciconf2": "3",
        "/dev/mst/mt4129_pciconf3": "4", "/dev/mst/mt41692_pciconf0": "bf3",
        "mt4129_pciconf0": "1", "mt4129_pciconf1": "2", "mt4129_pciconf2": "3", "mt4129_pciconf3": "4",
        "mt41692_pciconf0": "bf3"}


def port_status(ct, p):
    if p == "bf3":
        return ("Active", "LinkUp", "200G", "No issue was observed", 0)
    o = ct["osfp"][p]
    if not (o["seated"] and o["foam"] and o["tension"]):
        return ("Polling", "N/A", "N/A", "Cable is unplugged", 1024)
    if not o["pins"]:
        return ("Polling", "Polling", "N/A", "Signal not detected", 2)
    return ("Active", "LinkUp", "400G", "No issue was observed", 0)


def mlxlink_info(ct):
    lines = [f"Valet mlxlink_info   tray {ct['name']}   service tag {ct['tag']}   {core.stamp():%Y-%m-%d %H:%M:%S}",
             f"{'Port':<8}{'Device':<9}{'State':<10}{'Physical':<10}{'Speed':<7}Recommendation"]
    for p, dev in (("1", "mlx5_0"), ("2", "mlx5_1"), ("3", "mlx5_2"), ("4", "mlx5_3")):
        s = port_status(ct, p)
        lines.append(f"{'CX7-P' + p:<8}{dev:<9}{s[0]:<10}{s[1]:<10}{s[2]:<7}{s[3]}")
    if ct["bf3_present"]:
        s = port_status(ct, "bf3")
        lines.append(f"{'BF3-P0':<8}{'mlx5_4':<9}{s[0]:<10}{s[1]:<10}{s[2]:<7}{s[3]}")
    else:
        lines.append("BF3-P0  --       device not found (no BlueField-3 on the PCIe bus)")
    return "\n".join(lines) + "\n"


def valet_summary(ct):
    g = ct.get("remap_fail")
    lines = [f"Valet summary   {ct['name']} ({ct['tag']})",
             f"GPUs found        : 4 (B200)",
             f"Remapped rows     : " + (f"GPU{g} REMAPPING FAILURE (no spare rows)" if g is not None else "none pending, no failures"),
             f"ECC uncorrectable : " + (f"GPU{g} = 8" if g is not None else "0 on all GPUs"),
             f"XID events        : " + (", ".join(f"GPU{x['gpu']} XID {x['xid']}" for x in ct["gpu_xid"]) or "none"),
             f"BlueField-3       : " + ("present, fw " + ct["fw"]["bf3"] if ct["bf3_present"] else "NOT FOUND"),
             "Network ports     : see mlxlink_info.txt"]
    return "\n".join(lines) + "\n"


def outdir(st, ct):
    d = os.path.join(core.workdir(st), f"{ct['tag']}-liveimage")
    os.makedirs(d, exist_ok=True)
    return d


def write_valet(st, ct):
    d = outdir(st, ct)
    with open(os.path.join(d, "mlxlink_info.txt"), "a") as f:
        f.write(mlxlink_info(ct) + "\n")
    with open(os.path.join(d, "valet_summary.txt"), "a") as f:
        f.write(valet_summary(ct) + "\n")
    core.act(st, "valet", ct=ct["name"], ports={p: port_status(ct, p)[0] for p in "1234"},
             bf3=ct["bf3_present"])


def mlxlink(ct, args):
    dev, mod = None, False
    i = 0
    while i < len(args):
        if args[i] in ("-d", "--device") and i + 1 < len(args):
            dev = args[i + 1]
            i += 1
        elif args[i] in ("-m", "--show_module"):
            mod = True
        i += 1
    if not dev:
        return "-E- Please provide a device name using -d (try: mst status, or mlx5_0 ... mlx5_4)"
    p = DEVS.get(dev)
    if p is None or (p == "bf3" and not ct["bf3_present"]):
        return f"-E- Failed to open device: {dev}"
    s = port_status(ct, p)
    speed_ext = "0x00002000 (400G_4X)" if s[0] == "Active" else "N/A"
    out = ["", "Operational Info", "----------------",
           f"State                              : {s[0]}",
           f"Physical state                     : {s[1]}",
           f"Speed                              : {s[2]}",
           f"Width                              : {'4x' if s[0] == 'Active' else 'N/A'}",
           f"FEC                                : {'Standard_RS-FEC - (544,514)' if s[0] == 'Active' else 'N/A'}",
           "Loopback Mode                      : No Loopback",
           "Auto Negotiation                   : ON", "",
           "Supported Info", "--------------",
           "Enabled Link Speed (Ext.)          : 0x00003ff2 (400G_4X,200G_2X,200G_4X,100G_1X,100G_2X,50G_1X,25G,10G,1G)",
           f"Supported Cable Speed (Ext.)       : {speed_ext}", "",
           "Troubleshooting Info", "--------------------",
           f"Status Opcode                      : {s[4]}",
           f"Group Opcode                       : {'N/A' if s[4] == 0 else 'PHY FW'}",
           f"Recommendation                     : {s[3]}", "",
           "Tool Information", "----------------",
           f"Firmware Version                   : {ct['fw']['bf3'] if p == 'bf3' else ct['fw']['cx7']}",
           "MFT Version                        : mft 4.30.0-139"]
    if mod and p != "bf3":
        rx = "-1.1,-0.9,-1.2,-1.0" if s[0] == "Active" else "-40.0,-40.0,-40.0,-40.0"
        out += ["", "Module Info", "-----------", "Identifier                         : OSFP",
                "Compliance                         : 400GBASE-SR4", "Cable Type                         : Optical Module (separated)",
                "Vendor Name                        : NVIDIA", "Vendor Part Number                 : MMA4Z00-NS400",
                f"Vendor Serial Number               : MT24{core.nv_sn(ct['tag'] + p)[:8]}",
                f"Rx Power Current [dBm]             : {rx}",
                "Tx Power Current [dBm]             : 0.8,0.9,0.7,0.8"]
    return "\n".join(out)


def lspci(ct):
    L = [f"000{i}:01:00.0 Infiniband controller: Mellanox Technologies MT2910 Family [ConnectX-7]" for i in range(4)]
    if ct["bf3_present"]:
        L.append("0006:01:00.0 Ethernet controller: Mellanox Technologies MT43244 BlueField-3 integrated ConnectX-7 network controller (rev 01)")
    L += [f"{b} 3D controller: NVIDIA Corporation Device 2941 (rev a1)" for b in GPU_BUS]
    return "\n".join(L)


def nvsmi(ct, args):
    a = " ".join(args)
    g = ct.get("remap_fail")
    if "ROW_REMAPPER" in a.upper():
        out = ["", "==============NVSMI LOG==============", ""]
        for i, b in enumerate(GPU_BUS):
            bad = g == i
            out += [f"GPU 0000{b}", "    Remapped Rows",
                    f"        Correctable Error                 : 0",
                    f"        Uncorrectable Error               : {8 if bad else 0}",
                    f"        Pending                           : No",
                    f"        Remapping Failure Occurred        : {'Yes' if bad else 'No'}", ""]
        return "\n".join(out)
    if "ECC" in a.upper():
        out = ["", "==============NVSMI LOG==============", ""]
        for i, b in enumerate(GPU_BUS):
            bad = g == i
            out += [f"GPU 0000{b}", "    ECC Mode", "        Current                           : Enabled",
                    "    ECC Errors", "        Volatile",
                    "            DRAM Correctable              : 0",
                    f"            DRAM Uncorrectable            : {8 if bad else 0}",
                    "        Aggregate",
                    f"            DRAM Uncorrectable            : {8 if bad else 0}", ""]
        return "\n".join(out)
    rows = ["+-----------------------------------------------------------------------------+",
            "| NVIDIA-SMI 570.xx (dclab)            Driver Version: lab                     |",
            "| GPU  Name        Bus-Id            Temp   Uncorr. ECC   Remap failure          |",
            "|=============================================================================|"]
    for i, b in enumerate(GPU_BUS):
        bad = g == i
        rows.append(f"|  {i}   NVIDIA GB200  {b}    {41 + i}C    {8 if bad else 0:<12}  {'Yes' if bad else 'No':<20}  |")
    rows.append("+-----------------------------------------------------------------------------+")
    return "\n".join(rows)


def dmesg(ct):
    L = ["[    0.000000] Booting Linux on physical CPU 0x0000000000 [0x410fd4f0]",
         "[    4.210331] mlx5_core 0000:01:00.0: firmware version: " + ct["fw"]["cx7"]]
    for x in ct["gpu_xid"]:
        L.append(f"[ 8123.55{x['gpu']}203] NVRM: Xid (PCI:{GPU_BUS[x['gpu']]}): {x['xid']}, pid='<unknown>', "
                 f"name=<unknown>, {x['text']}")
    for p in "1234":
        if port_status(ct, p)[0] != "Active":
            L.append(f"[   12.80{p}114] mlx5_core 000{int(p) - 1}:01:00.0: Port module event: module 0, Cable unplugged")
    return "\n".join(L)


def bug_report(st, ct):
    d = outdir(st, ct)
    body = [f"nvidia-bug-report (dclab)   {ct['tag']}   {core.stamp():%Y-%m-%d %H:%M:%S}", "",
            nvsmi(ct, []), nvsmi(ct, ["-q", "-d", "ECC"]), nvsmi(ct, ["-q", "-d", "ROW_REMAPPER"]), "", dmesg(ct)]
    with open(os.path.join(d, "nvidia-bug-report.log"), "w") as f:
        f.write("\n".join(body) + "\n")
    core.act(st, "bug_report", ct=ct["name"])
    return ("nvidia-bug-report.sh will now collect information about your system and create the file\n"
            "'nvidia-bug-report.log.gz' in the current directory.\n\nRunning nvidia-bug-report.sh... complete.\n"
            f"(lab) Copy saved for you: {d}/nvidia-bug-report.log")


HELP = ("Live image commands: ls, cat <file>, mst status, mlxlink -d <dev> [-m], lspci, nvidia-smi\n"
        "  [-q -d ECC | -q -d ROW_REMAPPER], nvidia-bug-report.sh, dmesg, hostname, poweroff, reboot, exit\n"
        "  Pipes work for grep, e.g.  lspci | grep -i mellanox   or   dmesg | grep -i xid")


def run(st, ct, cmdline):
    core.act(st, "live_cmd", ct=ct["name"], cmd=cmdline)
    if not cmdline:
        return "", None
    parts = [p.strip() for p in cmdline.split("|")]
    try:
        argv = shlex.split(parts[0])
    except ValueError:
        return "-bash: syntax error", None
    cmd, args = argv[0], argv[1:]
    action = None
    if cmd in ("help", "?"):
        out = HELP
    elif cmd == "ls":
        out = "mlxlink_info.txt  valet_summary.txt" if (args and "valet" in args[0]) else "valet"
    elif cmd == "cd":
        out = ""
    elif cmd == "cat":
        f = (args[0] if args else "")
        if f.endswith("mlxlink_info.txt"):
            out = mlxlink_info(ct)
        elif f.endswith("valet_summary.txt"):
            out = valet_summary(ct)
        else:
            out = f"cat: {f}: No such file or directory"
    elif cmd == "mst":
        devs = [f"/dev/mst/mt4129_pciconf{i}         - PCI configuration cycles access.\n"
                f"                                   domain:bus:dev.fn=000{i}:01:00.0  (ConnectX-7, mlx5_{i})" for i in range(4)]
        if ct["bf3_present"]:
            devs.append("/dev/mst/mt41692_pciconf0        - PCI configuration cycles access.\n"
                        "                                   domain:bus:dev.fn=0006:01:00.0  (BlueField-3, mlx5_4)")
        out = "MST modules:\n------------\n    MST PCI configuration module loaded\n\nMST devices:\n------------\n" + "\n".join(devs)
    elif cmd == "mlxlink":
        out = mlxlink(ct, args)
    elif cmd == "lspci":
        out = lspci(ct)
    elif cmd == "nvidia-smi":
        out = nvsmi(ct, args)
    elif cmd in ("nvidia-bug-report.sh", "./nvidia-bug-report.sh"):
        out = bug_report(st, ct)
    elif cmd == "dmesg":
        out = dmesg(ct)
    elif cmd == "hostname":
        out = "liveimage"
    elif cmd == "whoami":
        out = "root"
    elif cmd == "date":
        out = time.strftime("%a %b %d %H:%M:%S UTC %Y")
    elif cmd in ("poweroff", "halt") or (cmd == "shutdown" and "-h" in args):
        return "[  OK  ] Reached target System Power Off.", "poweroff"
    elif cmd == "reboot" or (cmd == "shutdown" and "-r" in args):
        return "[  OK  ] Reached target System Reboot.", "reboot"
    elif cmd in ("exit", "logout"):
        out = "logout\n\nSupport Live Image 4.2 (dclab) - automatic login: root"
    else:
        out = f"-bash: {cmd}: command not found"
    for flt in parts[1:]:
        try:
            fa = shlex.split(flt)
        except ValueError:
            fa = flt.split()
        if not fa:
            continue
        if fa[0] == "grep":
            ign = "-i" in fa
            inv = "-v" in fa
            pats = [x for x in fa[1:] if not x.startswith("-")]
            if not pats:
                return "Usage: grep [OPTION]... PATTERNS [FILE]...", None
            rx = re.compile(re.escape(pats[0]) if not any(c in pats[0] for c in ".*[]^$") else pats[0],
                            re.I if ign else 0)
            out = "\n".join(l for l in out.splitlines() if bool(rx.search(l)) != inv)
        elif fa[0] == "head":
            n = int(fa[2]) if len(fa) > 2 and fa[1] == "-n" else 10
            out = "\n".join(out.splitlines()[:n])
        elif fa[0] == "wc" and "-l" in fa:
            out = str(len(out.splitlines()))
        else:
            out = f"-bash: {fa[0]}: only grep, head and wc -l work after a pipe in this live image"
    return out, action
