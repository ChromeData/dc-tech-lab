"""Data center operations tickets from the two postings: tools, inventory, optics, power, metrics, SOP, scripts."""
import csv
import datetime as dt
import math
import os
import random
import re
import subprocess

import core
from ticketlib import register


def wfile(st, name, text):
    p = os.path.join(core.workdir(st), name)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", newline="\n") as f:
        f.write(text)


def near(a, b, tol):
    try:
        return abs(float(str(a).replace(",", "")) - b) <= tol
    except (TypeError, ValueError):
        return False


# ============================================================== 100 tool up
def c100(x):
    have = lambda p: subprocess.run(["dpkg", "-s", p], capture_output=True).returncode == 0
    for p in ("jq", "lshw", "pciutils"):
        x.c(f"Package {p} is installed", have(p))
    try:
        owner = subprocess.run(["dpkg", "-S", "/usr/bin/script"], capture_output=True, text=True).stdout.split(":")[0]
    except OSError:
        owner = ""
    kv = x.kv("answers.txt")
    x.c("answers.txt: script_pkg names the package that owns /usr/bin/script", bool(owner) and kv.get("script_pkg") == owner)
    try:
        ver = subprocess.run(["jq", "--version"], capture_output=True, text=True).stdout.strip()
    except OSError:
        ver = ""
    x.c("answers.txt: jq_version matches `jq --version`", bool(ver) and kv.get("jq_version") == ver)


register(
    tid="DCOPS-100", title="Tool up your WSL", track="Linux",
    body="The class runs its tools from WSL. Yours is missing jq, which every HMC log command needs.",
    teach=[
        "Ubuntu/Debian: `sudo apt update`, `sudo apt install -y <pkg>`, `dpkg -s <pkg>` (is it installed), "
        "`dpkg -S <file>` (which package owns a file), `dpkg -L <pkg>` (files in a package).",
        "RHEL/Rocky/Oracle Linux use dnf and rpm for the same jobs: `dnf install`, `rpm -q`, `rpm -qf <file>`, "
        "`rpm -ql <pkg>`.",
        "jq formats and filters JSON. The HMC log is JSON, so the slide command pipes curl into jq.",
    ],
    do=["Install the packages jq, lshw and pciutils.",
        "Find which package owns the file /usr/bin/script.",
        "Write {wd}/answers.txt with two lines:  script_pkg=<package>   and   jq_version=<output of jq --version>"],
    nudge="apt installs; dpkg answers questions about what is installed.",
    walk=["sudo apt update, then one apt install with three names.", "dpkg -S with the file path.",
          "jq --version.", "Two lines in answers.txt."],
    show=["sudo apt update && sudo apt install -y jq lshw pciutils", "dpkg -S /usr/bin/script", "jq --version",
          "printf 'script_pkg=%s\\njq_version=%s\\n' \"$(dpkg -S /usr/bin/script | cut -d: -f1)\" \"$(jq --version)\" > {wd}/answers.txt"],
    setup=lambda st: None, check=c100)


# ============================================================== 201 receiving
PO = [("BF3-B3240", 4), ("OSFP-400G-SR4", 12), ("FAN-XE9712", 6), ("NVME-3.84TB", 8), ("PDB-XE9712", 2)]


def recv_data():
    r = random.Random(4411)
    slip = []
    for part, qty in PO:
        n = qty - 1 if part == "FAN-XE9712" else qty
        for _ in range(n):
            slip.append((part, "".join(r.choice("0123456789BCDFGHJKLMNPQRSTVWXZ") for _ in range(10))))
    missing = [slip[7][1], slip[25][1]]          # one OSFP, one NVMe never arrived
    extra = ("OSFP-400G-SR4", "ZZ" + "".join(r.choice("0123456789") for _ in range(8)))
    scanned = [s for _, s in slip if s not in missing] + [extra[1]]
    r.shuffle(scanned)
    return slip, scanned, missing, extra


def s201(st):
    slip, scanned, _, _ = recv_data()
    wfile(st, "po_4411.csv", "part,qty\n" + "".join(f"{p},{q}\n" for p, q in PO))
    wfile(st, "packing_slip.csv", "part,serial\n" + "".join(f"{p},{s}\n" for p, s in slip))
    wfile(st, "scanned_serials.txt", "".join(s + "\n" for s in scanned))


def c201(x):
    slip, scanned, missing, extra = recv_data()
    lines = [l.split() for l in x.read("discrepancies.txt").upper().splitlines() if l.strip()]
    got_m = {l[1] for l in lines if l[0] == "MISSING" and len(l) > 1}
    got_e = {l[1] for l in lines if l[0] == "EXTRA" and len(l) > 1}
    got_s = {(l[1], l[2]) for l in lines if l[0] == "SHORT" and len(l) > 2}
    ok_serials = {s for _, s in slip} & set(scanned)
    want_s = set()
    for part, qty in PO:
        got = sum(1 for p, s in slip if p == part and s in ok_serials)
        if got < qty:
            want_s.add((part, str(qty - got)))
    x.c("MISSING lines: every serial on the slip that was not scanned", got_m == set(missing))
    x.c("EXTRA lines: every scanned serial that is not on the slip", got_e == {extra[1]})
    x.c("SHORT lines: every part where received < PO quantity, with the shortfall", got_s == want_s)
    rows = set()
    for l in x.read("received.csv").upper().splitlines():
        f = [c.strip() for c in l.split(",")]
        if len(f) >= 3 and f[2] == "RECEIVED":
            rows.add((f[0], f[1]))
    x.c("received.csv lists exactly the units that are on the slip AND scanned (part,serial,RECEIVED)",
        rows == {(p, s) for p, s in slip if s in ok_serials})


register(
    tid="DCOPS-201", title="Receiving: PO 4411 arrived", track="Ops",
    body="A pallet for PO 4411 is at the dock. You have the PO, the vendor packing slip, and the serials "
         "you scanned. Reconcile them before anything goes on a shelf.",
    teach=[
        "Receiving is a three-way match: purchase order (what we bought), packing slip (what the vendor "
        "says they shipped), and the physical scan (what is actually here).",
        "Record a unit as received only when it is on the slip AND you scanned it. Report the rest.",
        "Shell tools for this: `sort`, `comm -23 a b` (lines only in a), `comm -13 a b` (lines only in b), "
        "`cut -d, -f2`, `grep -c`, `awk -F,`. `comm` needs sorted input.",
    ],
    do=["cd {wd}   Files: po_4411.csv, packing_slip.csv, scanned_serials.txt",
        "Write discrepancies.txt with one line per problem:",
        "   MISSING <serial>        on the slip, not scanned",
        "   EXTRA <serial>          scanned, not on the slip",
        "   SHORT <part> <count>    PO quantity minus units that are on the slip and scanned",
        "Write received.csv with a line  part,serial,RECEIVED  for every unit that is on the slip and scanned."],
    nudge="Make two sorted serial lists. comm does the rest.",
    walk=["Cut the serial column from the slip (skip the header) and sort it.", "Sort the scanned serials.",
          "comm -23 gives MISSING, comm -13 gives EXTRA, comm -12 gives the good serials.",
          "For each PO line, count the good serials for that part and subtract.",
          "Join the good serials back to their part for received.csv."],
    show=["cd {wd}", "tail -n +2 packing_slip.csv | cut -d, -f2 | sort > slip.txt; sort scanned_serials.txt > scan.txt",
          "comm -23 slip.txt scan.txt | sed 's/^/MISSING /' > discrepancies.txt",
          "comm -13 slip.txt scan.txt | sed 's/^/EXTRA /' >> discrepancies.txt",
          "comm -12 slip.txt scan.txt > good.txt",
          "grep -F -f good.txt packing_slip.csv | awk -F, '{print $1\",\"$2\",RECEIVED\"}' > received.csv",
          "tail -n +2 po_4411.csv | while IFS=, read p q; do n=$(grep -c \"^$p,\" received.csv); [ $n -lt $q ] && echo \"SHORT $p $((q-n))\"; done >> discrepancies.txt"],
    setup=s201, check=c201)


# ============================================================== 202 spares
SPARES = [("FAN-XE9712", 3, 6, 12), ("CMOS-CR2032", 14, 5, 20), ("OSFP-400G-SR4", 2, 8, 24), ("BF3-B3240", 1, 2, 4),
          ("NVME-3.84TB", 9, 4, 12), ("PDB-XE9712", 0, 1, 2), ("HMC-XE9712", 2, 1, 3), ("BMC-XE9712", 0, 2, 4),
          ("M2-RISER", 3, 2, 5), ("OSFP-HEADER", 1, 4, 10), ("IPEX-GB200", 2, 2, 4), ("LOM-XE9712", 1, 1, 2),
          ("CABLE-SLIMLINE", 5, 6, 16), ("BACKPLANE-NVME", 1, 1, 2)]


def s202(st):
    wfile(st, "spares.csv", "part,on_hand,min,max\n" + "".join(f"{p},{o},{mn},{mx}\n" for p, o, mn, mx in SPARES))


def c202(x):
    want = {(p, str(mx - o)) for p, o, mn, mx in SPARES if o < mn}
    got = set()
    for l in x.read("reorder.csv").upper().splitlines():
        f = [c.strip() for c in l.split(",")]
        if len(f) >= 2 and f[1].isdigit():
            got.add((f[0], f[1]))
    x.c("reorder.csv lists every part below its minimum", {p for p, _ in got} == {p for p, _ in want})
    x.c("Order quantity brings each part back up to its maximum", got == want)


register(
    tid="DCOPS-202", title="Spare parts below minimum", track="Ops",
    body="Weekly spares check for the R12 cage. Build the reorder list.",
    teach=["Min/max stocking: reorder when on-hand is BELOW the minimum, and order enough to reach the maximum "
           "(order = max - on_hand).",
           "awk on CSV:  awk -F, 'NR>1 && $2<$3 {print $1\",\"$4-$2}' file   (NR>1 skips the header)."],
    do=["cd {wd}   File: spares.csv (part,on_hand,min,max)",
        "Write reorder.csv with a header  part,order_qty  and one line per part that is below its minimum."],
    nudge="One awk line: a condition on two columns, and a subtraction.",
    walk=["Field 2 is on_hand, 3 is min, 4 is max.", "Condition: $2 < $3.", "Print part and $4-$2.",
          "Add the header line first."],
    show=["cd {wd}", "echo part,order_qty > reorder.csv",
          "awk -F, 'NR>1 && $2<$3 {print $1\",\"$4-$2}' spares.csv >> reorder.csv", "cat reorder.csv"],
    setup=s202, check=c202)


# ============================================================== 203 optics
def dom_data():
    r = random.Random(2031)
    files = {}
    bad = set()
    names = [f"R12-leaf{l}-p{p:02d}.txt" for l in (1, 2) for p in range(1, 13)]
    low = {names[4]: 2, names[13]: 4, names[20]: 1}
    hot = {names[9]}
    for n in names:
        rx = [round(r.uniform(-2.4, 0.6), 1) for _ in range(4)]
        temp = round(r.uniform(38, 55), 1)
        if n in low:
            rx[low[n] - 1] = round(r.uniform(-11.5, -8.4), 1)
            bad.add(n)
        if n in hot:
            temp = 74.6
            bad.add(n)
        sn = "MT24" + "".join(r.choice("0123456789") for _ in range(9))
        body = [f"Identifier                : 0x19 (OSFP)", "Vendor name               : NVIDIA",
                "Vendor PN                 : MMA4Z00-NS400", f"Vendor SN                 : {sn}",
                f"Module temperature        : {temp} degrees C", "Module temp high warning  : 70.0 degrees C",
                "Rx power low warning      : -7.3 dBm"]
        body += [f"Rx power lane {i + 1}           : {v} dBm" for i, v in enumerate(rx)]
        body += [f"Tx power lane {i + 1}           : {round(r.uniform(0.2, 1.4), 1)} dBm" for i in range(4)]
        files[n] = "\n".join(body) + "\n"
    return files, bad


def s203(st):
    files, _ = dom_data()
    for n, body in files.items():
        wfile(st, os.path.join("dom", n), body)


def c203(x):
    _, bad = dom_data()
    hot = "R12-leaf1-p10.txt"
    got = {os.path.basename(l.strip()) for l in x.read("bad_optics.txt").splitlines() if l.strip()}
    x.c("bad_optics.txt has every module with an Rx lane below the low warning", (bad - {hot}) <= got)
    x.c("bad_optics.txt has the module that is over its temperature warning", hot in got)
    x.c("No healthy module is listed", got <= bad)
    kv = x.kv("answers.txt")
    x.c("answers.txt: first_step is inspect (inspect, clean, inspect)", "inspect" in kv.get("first_step", "").lower())


register(
    tid="DCOPS-203", title="Optics: find the weak links", track="Ops",
    body="24 OSFP 400G modules on the R12 leaf switches were dumped to text (DOM = digital optical "
         "monitoring). Find the ones to service before they flap.",
    teach=[
        "DOM reports temperature and per-lane Tx/Rx light in dBm, plus the module's own warning thresholds. "
        "dBm is a log scale: more negative = less light. -9 dBm is weaker than -2 dBm.",
        "Flag a module when any Rx lane is BELOW its 'Rx power low warning', or its temperature is ABOVE "
        "its high warning.",
        "Fiber rule: inspect, clean, inspect. Never plug in a connector you have not inspected. Never look "
        "into a live fiber or port.",
        "Single-mode (OS2) jackets are yellow. Multimode OM3/OM4 jackets are aqua. 400G SR4 uses multimode "
        "with an MPO connector.",
        "Shell: `grep -l` prints file names that match; awk can compare numbers per line.",
    ],
    do=["cd {wd}   Files: dom/*.txt",
        "Write bad_optics.txt with the file name of every module that breaks a warning threshold.",
        "Write answers.txt with one line:  first_step=<the first thing you do to a suspect fiber end>"],
    nudge="Compare each Rx lane with -7.3 and the temperature with 70.0. awk handles negative numbers.",
    walk=["Rx lines: the value is the field before 'dBm'.", "awk: when a line starts with 'Rx power lane' and "
          "the value < -7.3, print FILENAME.", "Second pass for 'Module temperature' > 70.", "sort -u into the file."],
    show=["cd {wd}",
          "awk '/^Rx power lane/ && $(NF-1) < -7.3 {print FILENAME} /^Module temperature/ && $(NF-2) > 70 {print FILENAME}' dom/*.txt | sort -u | xargs -n1 basename > bad_optics.txt",
          "cat bad_optics.txt", "echo first_step=inspect > answers.txt"],
    setup=s203, check=c203)


# ============================================================== 204 power math
P_CT, P_SW, P_MISC = 5500, 1200, 1200
P_TOTAL = 18 * P_CT + 9 * P_SW + P_MISC
AMPS = P_TOTAL / (math.sqrt(3) * 415 * 0.95)
CIRCUITS = math.ceil(AMPS / (60 * 0.8))


def c204(x):
    kv = x.kv("answers.txt")
    x.c("total_w", near(kv.get("total_w"), P_TOTAL, 1))
    x.c("amps_per_phase (415 V three-phase, PF 0.95)", near(kv.get("amps_per_phase"), AMPS, 1.5))
    x.c("circuits_per_feed (60 A breakers at 80%)", near(kv.get("circuits_per_feed"), CIRCUITS, 0))
    x.c("total_circuits (A and B feeds, each carries the full load)", near(kv.get("total_circuits"), 2 * CIRCUITS, 0))
    x.c("btu_hr", near(kv.get("btu_hr"), P_TOTAL * 3.412, 4000))
    x.c("air_kw (15% of the heat stays in the air)", near(kv.get("air_kw"), P_TOTAL * 0.15 / 1000, 0.3))


register(
    tid="DCOPS-204", title="Power and cooling math for one rack", track="Ops",
    body="Facilities asks for the electrical and heat numbers before a new GB200 rack is energized. "
         "Use these planning figures (lab numbers, not a spec sheet): each compute tray 5,500 W, each "
         "NVLink switch tray 1,200 W, everything else in the rack 1,200 W total.",
    teach=[
        "Three-phase power:  P (W) = 1.732 x V (line-to-line) x I (amps per phase) x power factor.  So  "
        "I = P / (1.732 x V x PF).",
        "Breakers carry continuous load at 80% of their rating. A 60 A circuit gives you 48 A.",
        "A and B feeds (2N): each feed must be able to carry the whole rack alone.",
        "Heat: 1 W = 3.412 BTU/hr. All the electrical power becomes heat.",
        "Liquid cooling: cold plates take most of the heat to the CDU (coolant distribution unit). The rest "
        "goes into the room air. Here: 85% liquid, 15% air.",
        "The rack has 18 compute trays and 9 NVLink switch trays. `bc -l` or `python3 -c` does the math.",
    ],
    do=["Write {wd}/answers.txt with these six lines (numbers only):",
        "   total_w=            rack power in watts",
        "   amps_per_phase=     at 415 V three-phase, power factor 0.95",
        "   circuits_per_feed=  60 A three-phase circuits needed on ONE feed (whole number)",
        "   total_circuits=     for A + B feeds",
        "   btu_hr=             heat in BTU/hr",
        "   air_kw=             kW of heat left in the room air"],
    nudge="Add up watts first. Every other line is one formula on that number.",
    walk=["18 x 5500 + 9 x 1200 + 1200.", "Divide by (1.732 x 415 x 0.95).", "Divide amps by 48 and round UP.",
          "Double it for A + B.", "Watts x 3.412.", "Watts x 0.15 / 1000."],
    show=["python3 - <<'EOF' > {wd}/answers.txt\nimport math\nw=18*5500+9*1200+1200\na=w/(math.sqrt(3)*415*0.95)\n"
          "c=math.ceil(a/48)\nprint(f'total_w={w}\\namps_per_phase={a:.1f}\\ncircuits_per_feed={c}\\n"
          "total_circuits={2*c}\\nbtu_hr={w*3.412:.0f}\\nair_kw={w*0.15/1000:.2f}')\nEOF", "cat {wd}/answers.txt"],
    setup=lambda st: None, check=c204)


# ============================================================== 205 MTTD / MTTR
INC = [("INC-01", "gpu", "2026-11-02 01:10", 9, 142), ("INC-02", "optics", "2026-11-02 07:45", 4, 38),
       ("INC-03", "leak", "2026-11-03 13:02", 2, 96), ("INC-04", "gpu", "2026-11-03 22:31", 15, 201),
       ("INC-05", "power", "2026-11-04 04:18", 3, 64), ("INC-06", "optics", "2026-11-05 10:05", 6, 27),
       ("INC-07", "gpu", "2026-11-05 16:40", 11, 173), ("INC-08", "optics", "2026-11-06 02:22", 5, 44),
       ("INC-09", "power", "2026-11-07 09:09", 1, 52), ("INC-10", "leak", "2026-11-08 19:54", 2, 118),
       ("INC-11", "gpu", "2026-11-09 05:30", 13, 96), ("INC-12", "optics", "2026-11-10 14:12", 7, 31)]


def s205(st):
    rows = ["id,category,fault_start,detected,repaired"]
    for i, cat, start, ttd, ttr in INC:
        t0 = dt.datetime.strptime(start, "%Y-%m-%d %H:%M")
        t1 = t0 + dt.timedelta(minutes=ttd)
        t2 = t1 + dt.timedelta(minutes=ttr)
        rows.append(f"{i},{cat},{t0:%Y-%m-%d %H:%M},{t1:%Y-%m-%d %H:%M},{t2:%Y-%m-%d %H:%M}")
    wfile(st, "incidents.csv", "\n".join(rows) + "\n")


def c205(x):
    kv = x.kv("answers.txt")
    mean = lambda v: sum(v) / len(v)
    x.c("mttd_all (minutes)", near(kv.get("mttd_all"), mean([i[3] for i in INC]), 0.6))
    x.c("mttr_all (minutes)", near(kv.get("mttr_all"), mean([i[4] for i in INC]), 0.6))
    x.c("mttr_gpu", near(kv.get("mttr_gpu"), mean([i[4] for i in INC if i[1] == "gpu"]), 0.6))
    x.c("mttr_optics", near(kv.get("mttr_optics"), mean([i[4] for i in INC if i[1] == "optics"]), 0.6))
    x.c("worst_category names the category with the longest MTTR", kv.get("worst_category", "").lower() == "gpu")


register(
    tid="DCOPS-205", title="MTTD and MTTR for the week", track="Ops",
    body="The posting names two metrics you own: mean time to detect and mean time to repair. Compute "
         "them from last week's incidents.",
    teach=[
        "MTTD = mean time to detect = average of (detected - fault_start).",
        "MTTR = mean time to repair = average of (repaired - detected). (Some sites measure repair from the "
        "fault start. Ask which one your site uses.)",
        "`date -d '2026-11-02 01:10' +%s` turns a timestamp into seconds. Subtract, divide by 60 for minutes.",
        "Lower both by detecting faster (monitoring, alerts) and repairing faster (spares on hand, clear SOPs, "
        "logs collected the first time).",
    ],
    do=["cd {wd}   File: incidents.csv",
        "Write answers.txt (minutes, one decimal):  mttd_all=  mttr_all=  mttr_gpu=  mttr_optics=  "
        "worst_category=<category with the longest MTTR>"],
    nudge="Turn each timestamp into seconds, subtract, average. Group by column 2 for the per-category lines.",
    walk=["Loop over the rows after the header.", "date -d ... +%s for the three timestamps.",
          "Sum (detected-start) and (repaired-detected), count rows.", "Divide by count and by 60.",
          "Repeat with a filter on the category."],
    show=["cd {wd}",
          "python3 - <<'EOF' > answers.txt\nimport csv,datetime as d\nf='%Y-%m-%d %H:%M'\nR=list(csv.DictReader(open('incidents.csv')))\n"
          "m=lambda a,b:(d.datetime.strptime(b,f)-d.datetime.strptime(a,f)).total_seconds()/60\n"
          "avg=lambda v:sum(v)/len(v)\nttr=lambda c:avg([m(r['detected'],r['repaired']) for r in R if c in (None,r['category'])])\n"
          "print(f\"mttd_all={avg([m(r['fault_start'],r['detected']) for r in R]):.1f}\")\nprint(f'mttr_all={ttr(None):.1f}')\n"
          "print(f\"mttr_gpu={ttr('gpu'):.1f}\")\nprint(f\"mttr_optics={ttr('optics'):.1f}\")\n"
          "print('worst_category='+max({r['category'] for r in R},key=ttr))\nEOF", "cat answers.txt"],
    setup=s205, check=c205)


# ============================================================== 206 SOP (Sr.)
SOP_HEADS = ["purpose", "scope", "safety", "tools", "procedure", "verification", "records"]


def c206(x):
    text = x.read("SOP-CT-SWAP.md")
    low = text.lower()
    heads = [h for h in SOP_HEADS if re.search(rf"^#+\s*\d*\.?\s*{h}", low, re.M)]
    x.c("All seven sections are there: " + ", ".join(h.title() for h in SOP_HEADS), len(heads) == len(SOP_HEADS))
    x.c("At least 150 words, written as numbered steps", len(low.split()) >= 150 and len(re.findall(r"^\s*\d+[.)]", text, re.M)) >= 6)
    for label, keys in (("logs are collected first", ("log", "ezbmc")),
                        ("graceful / ACPI shutdown", ("graceful", "acpi", "soft")),
                        ("ESD protection", ("esd",)), ("hospital rack", ("hospital",)),
                        ("Part Only work order", ("part only", "work order")),
                        ("handles, rails and drives move over", ("handle",)), ("rails", ("rail",)),
                        ("drives (internal and front)", ("drive",)), ("swap form", ("swap form",))):
        x.c(f"Covers: {label}", any(k in low for k in keys))


register(
    tid="DCOPS-206", title="Write the SOP: compute tray swap (Sr.)", track="Ops",
    body="Both postings ask you to create and maintain SOPs. The Sr. posting adds leading projects. Write "
         "the CT swap SOP a new tech could follow at 3 a.m.",
    teach=[
        "A usable SOP has: Purpose, Scope, Safety, Tools, Procedure (numbered steps, one action each), "
        "Verification (how you know it worked), Records (what you file and where).",
        "Write each step as a command: verb first, one action, the exact value. 'Torque to 20 in-lb.'",
        "The CT swap facts are in ticket DCOPS-111 (`dclab learn swap`).",
    ],
    do=["Write {wd}/SOP-CT-SWAP.md with those seven headings (markdown # headings).",
        "Cover the whole swap: logs, shutdown in a production rack, move to hospital, support work order, "
        "parts to transfer, swap form, and how to verify the replacement.",
        "Read it out loud once. Fix any step you stumbled on."],
    nudge="Write it from memory first. Then check it against `dclab learn swap` and fill the holes.",
    walk=["Seven # headings.", "Safety: ESD strap, two-person lift, never pull a live tray.",
          "Procedure: number every step.", "Verification: POST completes, sensors ok, tray joins the fabric.",
          "Records: ticket, work order, old and new service tags, swap form."],
    show=["dclab learn swap", "nano {wd}/SOP-CT-SWAP.md   # write it yourself: the grader checks headings and key steps, not wording"],
    setup=lambda st: None, check=c206)


# ============================================================== 301 script: collect logs
def s301(st):
    ct = st["cts"]["CT03"]
    core.add_sel(ct, "System Event", "Boot Event", 0x60, "OEM System boot event", discrete=True)


def run(cmd, cwd, timeout=60):
    env = dict(os.environ, PATH=os.path.join(core.LAB, "bin") + ":" + os.environ.get("PATH", ""))
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)
        return p.returncode, p.stdout + p.stderr
    except (OSError, subprocess.TimeoutExpired) as e:
        return 99, str(e)


def c301(x):
    path = os.path.join(x.wd, "collect_ct_logs.sh")
    x.c("collect_ct_logs.sh exists, starts with #!/bin/bash (or env bash), and is executable",
        os.path.exists(path) and os.access(path, os.X_OK) and open(path).readline().startswith("#!"))
    if not os.path.exists(path):
        return
    ct = x.ct("CT03")
    out = os.path.join(x.wd, "_grader_run")
    os.makedirs(out, exist_ok=True)
    for f in os.listdir(out):
        os.remove(os.path.join(out, f))
    rc, _ = run([path, ct["bmc_ip"], ct["tag"]], out)
    x.c("Exit code 0 on a reachable BMC", rc == 0)
    read = lambda n: open(os.path.join(out, n)).read() if os.path.exists(os.path.join(out, n)) else ""
    x.c("Creates <ServiceTag>-sel.txt", "SEL Record ID" in read(f"{ct['tag']}-sel.txt"))
    x.c("Creates <ServiceTag>-sdr.txt", "Ch0LeaDet0ColPla" in read(f"{ct['tag']}-sdr.txt"))
    x.c("Creates <ServiceTag>-HMCevents.txt", '"Members"' in read(f"{ct['tag']}-HMCevents.txt"))
    rc2, o2 = run([path], out)
    x.c("With no arguments: prints a usage line and exits non-zero", rc2 not in (0, 99) and "usage" in o2.lower())
    rc3, _ = run([path, "192.168.8.99", "NOSUCH"], out)
    x.c("Unreachable BMC: exits non-zero", rc3 not in (0, 99))


register(
    tid="DCOPS-301", title="Script it: collect_ct_logs.sh", track="Linux", ct="CT03",
    body="You type the same three log commands on every ticket. Turn them into one script.",
    teach=[
        "A bash script starts with `#!/bin/bash`. Make it executable with `chmod +x`.",
        "`$1` and `$2` are the first and second arguments. `$#` is how many were given.",
        "`exit 1` ends the script with a failure code. `$?` holds the exit code of the last command.",
        "With a pipe, `$?` is the LAST command (tee). `set -o pipefail` makes the pipe fail when any part fails.",
        "Test: `[ $# -ne 2 ]`.  Print to the error stream with `>&2`.",
    ],
    do=["Write {wd}/collect_ct_logs.sh. Usage:  collect_ct_logs.sh <BMC_IP> <SERVICE_TAG>",
        "It saves <TAG>-sel.txt, <TAG>-sdr.txt and <TAG>-HMCevents.txt in the current directory (tee -a).",
        "With the wrong number of arguments it prints a line containing 'usage' and exits non-zero.",
        "If the BMC cannot be reached it exits non-zero.",
        "Test it yourself on CT03 ({ip} {tag}), then grade."],
    nudge="Check the argument count first. Then pipefail makes an ipmitool failure visible through tee.",
    walk=["Shebang, then set -o pipefail.", "If $# is not 2: echo usage to stderr, exit 2.",
          "ip=$1, tag=$2.", "Three commands with tee -a; add `|| exit 1` to each.", "chmod +x."],
    show=["cat > {wd}/collect_ct_logs.sh <<'EOF'\n#!/bin/bash\nset -o pipefail\nif [ $# -ne 2 ]; then echo \"usage: $0 <BMC_IP> <SERVICE_TAG>\" >&2; exit 2; fi\n"
          "ip=$1; tag=$2\nipmitool -I lanplus -H \"$ip\" -U admin -P admin sel -v list | tee -a \"$tag-sel.txt\" || exit 1\n"
          "ipmitool -I lanplus -H \"$ip\" -U admin -P admin sdr elist | tee -a \"$tag-sdr.txt\" || exit 1\n"
          "curl -sfk -u 'admin:admin' \"https://$ip/redfish/v1/Systems/HGX_Baseboard_0/LogServices/EventLog/Entries\" | jq | tee -a \"$tag-HMCevents.txt\" || exit 1\nEOF",
          "chmod +x {wd}/collect_ct_logs.sh", "cd {wd} && ./collect_ct_logs.sh {ip} {tag}"],
    setup=s301, check=c301)


# ============================================================== 302 script: rack sweep
def s302(st):
    a, b = st["cts"]["CT06"], st["cts"]["CT15"]
    a["leak"]["M0_1"] = "dirty"
    a["in_job"] = False
    b["fan_fail"] = 5
    b["in_job"] = False


def c302(x):
    path = os.path.join(x.wd, "rack_sweep.sh")
    x.c("rack_sweep.sh exists and is executable", os.path.exists(path) and os.access(path, os.X_OK))
    if not os.path.exists(path):
        return
    rc, out = run([path], x.wd, timeout=180)
    lines = [l for l in out.splitlines() if l.strip()]
    x.c("Runs and exits 0", rc == 0)
    x.c("Reports the bad sensor on 192.168.8.16", any("192.168.8.16" in l and "Cha0LeaDete0Mani" in l for l in lines))
    x.c("Reports the bad sensor on 192.168.8.25", any("192.168.8.25" in l and "Fan5" in l for l in lines))
    x.c("Prints nothing for healthy sensors or healthy trays",
        all(("192.168.8.16" in l or "192.168.8.25" in l) and " ok " not in l and "| ok" not in l for l in lines) and len(lines) <= 4)


register(
    tid="DCOPS-302", title="Script it: sweep the whole rack", track="Linux",
    body="Monitoring is half the job (MTTD). Sweep all 18 BMCs in R12 and print only what is wrong.",
    teach=[
        "Loop over numbers:  for i in $(seq 11 28); do ... done   (R12 BMCs are 192.168.8.11 to 192.168.8.28).",
        "`sdr elist` status column: ok = normal, cr = critical, nc = non-critical, ns = no reading.",
        "awk -F'|' splits on the pipe. Fields have spaces around them; `$3 ~ /cr/` matches the status.",
        "Prefix each line with the BMC IP so the output says where the problem is.",
    ],
    do=["Write {wd}/rack_sweep.sh (no arguments). For each of the 18 BMCs, run `sdr elist`.",
        "Print one line per sensor whose status is cr or nc, starting with the BMC IP, and nothing else.",
        "Run it. Two trays in this rack have a problem. Then grade."],
    nudge="A for loop around one ipmitool call, piped into one awk filter.",
    walk=["for i in $(seq 11 28).", "ip=192.168.8.$i.", "ipmitool ... sdr elist piped to awk.",
          "awk: if field 3 has cr or nc, print the ip and the line."],
    show=["cat > {wd}/rack_sweep.sh <<'EOF'\n#!/bin/bash\nfor i in $(seq 11 28); do\n  ip=192.168.8.$i\n"
          "  ipmitool -I lanplus -H $ip -U admin -P admin sdr elist | awk -F'|' -v ip=$ip '$3 ~ /cr|nc/ {print ip, $0}'\ndone\nEOF",
          "chmod +x {wd}/rack_sweep.sh && {wd}/rack_sweep.sh"],
    setup=s302, check=c302)
