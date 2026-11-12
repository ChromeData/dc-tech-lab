#!/usr/bin/env python3
"""End-to-end test: every ticket must FAIL when fresh and PASS after it is solved the taught way.

Run inside WSL:  python3 ~/dclab/tests/solve_all.py [ticket numbers...]
"""
import glob
import json
import os
import pty
import select
import subprocess
import sys
import time

LAB = os.path.expanduser("~/dclab")
ENV = dict(os.environ, PATH=f"{LAB}/bin:" + os.environ["PATH"], DCLAB_HOME=LAB)
I = "ipmitool -I lanplus -H {ip} -U admin -P admin"


def state():
    with open(f"{LAB}/state/rack.json") as f:
        return json.load(f)


def wd():
    return os.path.join(LAB, "work", state()["ticket"])


def sh(cmd, check=False, quiet=True):
    p = subprocess.run(["bash", "-c", cmd], cwd=wd(), env=ENV, capture_output=True, text=True)
    if not quiet or (check and p.returncode):
        print(f"   $ {cmd}\n{p.stdout}{p.stderr}")
    return p.returncode, p.stdout + p.stderr


def ct(name):
    c = state()["cts"][name]
    return c["bmc_ip"], c["tag"]


class Term:
    """Drive an interactive command in a pty."""

    def __init__(self, cmd):
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            os.chdir(wd())
            os.execvpe("bash", ["bash", "-c", cmd], ENV)
        self.buf = ""

    def expect(self, text, timeout=40):
        end = time.time() + timeout
        start = len(self.buf)
        while time.time() < end:
            if text in self.buf[start:]:
                return True
            r, _, _ = select.select([self.fd], [], [], 0.2)
            if r:
                try:
                    self.buf += os.read(self.fd, 4096).decode("utf-8", "replace")
                except OSError:
                    break
        ok = text in self.buf[start:]
        if not ok:
            print(f"   !! expected {text!r}; tail: {self.buf[-300:]!r}")
        return ok

    def send(self, s):
        os.write(self.fd, s.encode() if isinstance(s, str) else s)

    def close(self):
        try:
            for _ in range(20):
                r, _, _ = select.select([self.fd], [], [], 0.2)
                if not r:
                    break
                self.buf += os.read(self.fd, 4096).decode("utf-8", "replace")
        except OSError:
            pass
        try:
            os.close(self.fd)
        except OSError:
            pass
        try:
            os.waitpid(self.pid, 0)
        except ChildProcessError:
            pass


def logs(name, kinds="sel sdr hmc"):
    ip, tag = ct(name)
    i = I.format(ip=ip)
    if "sel" in kinds:
        sh(f"{i} sel -v list | tee -a {tag}-sel.txt")
    if "sdr" in kinds:
        sh(f"{i} sdr elist | tee -a {tag}-sdr.txt")
    if "hmc" in kinds:
        sh(f"curl -sk -u 'admin:admin' https://{ip}/redfish/v1/Systems/HGX_Baseboard_0/LogServices/EventLog/Entries | jq | tee -a {tag}-HMCevents.txt")


def res(text):
    sh(f"echo {json.dumps(text)} > resolution.txt")


def power(name, op):
    ip, _ = ct(name)
    return sh(f"{I.format(ip=ip)} chassis power {op}")


# ------------------------------------------------------------------ solutions
def t100():
    sh("printf 'script_pkg=%s\\njq_version=%s\\n' \"$(dpkg -S /usr/bin/script | cut -d: -f1)\" \"$(jq --version)\" > answers.txt")


def t101():
    out = {}
    for item, spot in (("RACK", "rack-back-right-corner"), ("CT07", "luggage-tag-near-bmc-port"),
                       ("SW1", "luggage-tag-bottom-right"), ("CC2", "left-side-middle"),
                       ("PT3", "back-right-near-busbar"), ("CAP1", "right-side")):
        _, o = sh(f"tech tag {item} {spot}")
        out[item] = o.strip().split()[-1]
    sh("printf '%s\\n' " + " ".join(f"{k}={v}" for k, v in out.items()) + " > tags.txt")


def t102():
    ip, tag = ct("CT03")
    i = I.format(ip=ip)
    rc, o = sh(f"{i} sol activate")
    assert "already active" in o, o
    sh(f"{i} sol deactivate")
    t = Term(f"script -q -c '{i} sol activate' {tag}-sol.txt")
    assert t.expect("SOL Session operational")
    power("CT03", "cycle")
    assert t.expect("Shell> ", 60)
    t.send("exit\r")
    assert t.expect("Shell> ", 60)
    t.send("\r")
    time.sleep(0.5)
    t.send("~.")
    t.expect("terminated ipmitool", 10)
    t.close()
    res("POST completed, EFI shell is normal when PXE finds nothing. Hand to provisioning to check the PXE target.")


def t103():
    logs("CT11")
    sh(f"ezbmc {ct('CT11')[0]}")
    res("GPU_3 logged XID 121 C2C bus error")


def t104():
    logs("CT07")
    sh("tech fwupdate CT07 bmc 26.01.10001500", check=True)
    power("CT07", "on")
    time.sleep(8)
    res("Ch0LeaDet0ColPla M0_0 read 0.66 V. BMC below 25.09.30001500. Updated BMC with CT off.")


def t105():
    logs("CT09", "sel sdr")
    for c in ("pull", "open", "uv"):
        sh(f"tech {c} CT09", check=True)
    sh("tech inspect CT09 leak-sensors; tech clean CT09 M1_0; tech ziptie CT09 M1_0; tech close CT09; tech insert CT09", check=True)
    power("CT09", "on")
    time.sleep(8)
    logs("CT09", "sdr")
    res("Ch0LeaDet1ColPla M1_0 0.66 V, no coolant under UV, sensor touched the cold plate, cleaned and zip tied.")


def t106():
    logs("CT12", "sel sdr")
    sh("tech pull CT12; tech open CT12; tech inspect CT12 busbar; tech loosen CT12 busbar", check=True)
    for s in ("back", "front", "middle"):
        sh(f"tech torque CT12 busbar --section {s} --inlb 20", check=True)
    sh("tech close CT12; tech insert CT12", check=True)
    power("CT12", "on")
    time.sleep(8)
    res("P54V busbar low. Loosened all screws, re-torqued to 20 in-lb back front middle.")


def t107():
    logs("CT04")
    sh("tech pull CT04; tech open CT04; tech reseat CT04 hmc-slimline-cables; tech reseat CT04 hmc-card; tech close CT04; tech insert CT04", check=True)
    power("CT04", "on")
    time.sleep(8)
    logs("CT04", "hmc")
    res("HMC not responding 503. Reseated slimline cables and the HMC card.")


def live_boot(name, cmds, power_first=None):
    """Open SOL (recorded), get to the live image via USB + exit at Shell>, run cmds, leave."""
    ip, tag = ct(name)
    i = I.format(ip=ip)
    t = Term(f"script -q -a -c '{i} sol activate' {tag}-sol.txt")
    assert t.expect("SOL Session operational")
    if power_first:
        power(name, power_first)
    else:
        t.send("\r")
    assert t.expect("Shell> ", 60)
    sh(f"tech usb {name} insert")
    t.send("exit\r")
    assert t.expect("root@liveimage:~# ", 60)
    for c in cmds:
        t.send(c + "\r")
        if c == "poweroff":
            time.sleep(1.5)
            break
        assert t.expect("root@liveimage:~# ", 20)
    t.send("\r")
    time.sleep(0.4)
    t.send("~.")
    t.expect("terminated ipmitool", 10)
    t.close()
    return t.buf


def t108():
    out = live_boot("CT14", ["cat valet/mlxlink_info.txt", "mlxlink -d mlx5_2", "lspci | grep -i mellanox", "poweroff"])
    assert "Polling" in out and "Cable is unplugged" in out, out[-600:]
    sh("tech pull CT14; tech open CT14; tech inspect CT14 osfp; tech reseat CT14 foam-pad --port 3; "
       "tech torque CT14 tension-bar --port 3; tech replace CT14 osfp-cable --port 4; tech close CT14; tech insert CT14", check=True)
    out = live_boot("CT14", ["mlxlink -d mlx5_3 -m"], power_first="on")
    assert "LinkUp" in out, out[-600:]
    res("Port 3 foam pad out of place and tension bar loose. Port 4 bent pins, cable replaced.")


def t109():
    ip, tag = ct("CT16")
    i = I.format(ip=ip)
    t = Term(f"{i} sol activate")
    assert t.expect("SOL Session operational")
    power("CT16", "cycle")
    assert t.expect("Boot Manager", 30)
    time.sleep(0.5)
    t.send(b"\x1bOQ")
    assert t.expect("System Setup", 10)
    assert "Present" in t.buf
    t.send(b"\x1b")
    assert t.expect("Shell> ", 60)
    sh(f"curl -sk -u admin:admin https://{ip}/redfish/v1/UpdateService/FirmwareInventory/BF3_Firmware | jq")
    power("CT16", "soft")
    sh("tech fwupdate CT16 bf3 1.3.4", check=True)
    power("CT16", "on")
    assert t.expect("provision-ct login: ", 60)
    t.send("\r")
    time.sleep(0.4)
    t.send("~.")
    t.close()
    res("BF3 present but firmware 1.2.0. Updated BF3 to 1.3.4 with CT off.")


def t110():
    ip, tag = ct("CT17")
    i = I.format(ip=ip)
    t = Term(f"{i} sol activate")
    assert t.expect("SOL Session operational")
    power("CT17", "cycle")
    assert t.expect("Boot Manager", 30)
    time.sleep(0.4)
    t.send(b"\x1b")
    time.sleep(0.3)
    t.send("2")
    assert t.expect("Not Detected", 10)
    t.send(b"\x1b")
    assert t.expect("Shell> ", 60)
    t.send("\r")
    time.sleep(0.4)
    t.send("~.")
    t.close()
    logs("CT17", "hmc")
    rc, o = sh(f"tech case CT17 --attach {tag}-HMCevents.txt")
    assert "work order" in o, o
    sh("tech receive CT17")
    power("CT17", "soft")
    sh("tech pull CT17; tech open CT17; tech replace CT17 bf3; tech close CT17; tech insert CT17", check=True)
    power("CT17", "on")
    res("BF3 missing in BIOS. HMC log shows PCI link error. Support work order, replaced BF3.")


def t111():
    ip, tag = ct("CT05")
    sh(f"ezbmc {ip}")
    power("CT05", "soft")
    power("CT05", "status")
    sh("tech pull CT05; tech move CT05 hospital; tech insert CT05", check=True)
    rc, o = sh(f"tech case CT05 --attach ~/ezBMC_Logs/{tag}_*.zip")
    assert "WO-" in o, o
    wo = [w for w in o.split() if w.startswith("WO-")][0]
    rc, o = sh("tech receive CT05")
    new = o.split("New service tag:")[1].split()[0].rstrip(".")
    sh("tech pull CT05", check=True)
    for item in ("handles", "rails", "drives-internal", "drives-front"):
        sh(f"tech transfer CT05 {item}", check=True)
    sh(f"tech swap-form --old {tag} --new {new} --wo {wo}", check=True)
    res("GPU_3 XID 121 and remap failure. Graceful shutdown, moved to hospital, swap form submitted.")


def t112():
    power("CT02", "soft")
    for comp, ver in (("bmc", "26.01.10001500"), ("bios", "1.3.6.12"), ("bianca", "1.3.6.07")):
        sh(f"tech fwupdate CT02 {comp} {ver}", check=True)
    power("CT02", "on")
    res("CT02 on site matrix. CT08 is 1.3.6 and cannot be downgraded.")


def t113():
    logs("CT10", "sel sdr")
    power("CT10", "soft")
    power("CT10", "status")
    sh("tech pull CT10; tech open CT10; tech replace CT10 fan; tech close CT10; tech insert CT10", check=True)
    power("CT10", "on")
    res("Fan3 failed. Graceful ACPI shutdown because a hard off breaks the NVLink fabric.")


def t114():
    rc, o = power("CT13", "status")
    assert "Unable to establish" in o, o
    sh("tech pull CT13; tech open CT13; tech replace CT13 bmc; tech close CT13; tech insert CT13; tech run CT13 fixBMC.sh", check=True)
    sh("tech fwupdate CT13 bmc 26.01.10001500", check=True)
    power("CT13", "on")
    res("Replaced BMC, ran fixBMC.sh before powering on, updated BMC.")


def t115():
    a = sh("tech tag SW4 luggage-tag-bottom-right")[1].split()[-1]
    b = sh("tech tag SWNEW luggage-tag-bottom-right")[1].split()[-1]
    sh(f"printf 'SW4={a}\\nSWNEW={b}\\n' > tags.txt")
    sh("tech switch SWNEW factory-reset; tech switch SW4 remove; tech switch SWNEW install --slot 4", check=True)
    res("One switch offline halts the whole rack. Switch 1 is the primary. Factory reset so ZTP works.")


def t201():
    sh("tail -n +2 packing_slip.csv | cut -d, -f2 | sort > slip.txt; sort scanned_serials.txt > scan.txt;"
       "comm -23 slip.txt scan.txt | sed 's/^/MISSING /' > discrepancies.txt;"
       "comm -13 slip.txt scan.txt | sed 's/^/EXTRA /' >> discrepancies.txt;"
       "comm -12 slip.txt scan.txt > good.txt;"
       "grep -F -f good.txt packing_slip.csv | awk -F, '{print $1\",\"$2\",RECEIVED\"}' > received.csv;"
       "tail -n +2 po_4411.csv | while IFS=, read p q; do n=$(grep -c \"^$p,\" received.csv); [ $n -lt $q ] && echo \"SHORT $p $((q-n))\"; done >> discrepancies.txt; true")


def t202():
    sh("echo part,order_qty > reorder.csv; awk -F, 'NR>1 && $2<$3 {print $1\",\"$4-$2}' spares.csv >> reorder.csv")


def t203():
    sh("awk '/^Rx power lane/ && $(NF-1) < -7.3 {print FILENAME} /^Module temperature/ && $(NF-2) > 70 {print FILENAME}' dom/*.txt"
       " | sort -u | xargs -n1 basename > bad_optics.txt; echo first_step=inspect > answers.txt")


def t204():
    sh("python3 -c \"import math;w=18*5500+9*1200+1200;a=w/(math.sqrt(3)*415*0.95);c=math.ceil(a/48);"
       "print(f'total_w={w}\\namps_per_phase={a:.1f}\\ncircuits_per_feed={c}\\ntotal_circuits={2*c}\\nbtu_hr={w*3.412:.0f}\\nair_kw={w*0.15/1000:.2f}')\" > answers.txt")


def t205():
    code = ("import csv,datetime as d\nf='%Y-%m-%d %H:%M'\nR=list(csv.DictReader(open('incidents.csv')))\n"
            "m=lambda a,b:(d.datetime.strptime(b,f)-d.datetime.strptime(a,f)).total_seconds()/60\n"
            "avg=lambda v:sum(v)/len(v)\nttr=lambda c:avg([m(r['detected'],r['repaired']) for r in R if c in (None,r['category'])])\n"
            "print(f\"mttd_all={avg([m(r['fault_start'],r['detected']) for r in R]):.1f}\")\nprint(f'mttr_all={ttr(None):.1f}')\n"
            "print(f\"mttr_gpu={ttr('gpu'):.1f}\")\nprint(f\"mttr_optics={ttr('optics'):.1f}\")\n"
            "print('worst_category='+max({r['category'] for r in R},key=ttr))\n")
    with open(os.path.join(wd(), "_s.py"), "w") as f:
        f.write(code)
    sh("python3 _s.py > answers.txt")


def t206():
    body = ["# Purpose", "Swap a failed compute tray for a replacement and return the slot to service. " * 3,
            "# Scope", "GB200 NVL72 compute trays in production racks and the hospital rack. " * 2,
            "# Safety", "Wear an ESD strap. Two people lift the tray. Never pull a live tray. " * 2,
            "# Tools", "Laptop with WSL, ipmitool, ezBMC, torque driver, ESD strap, cart.",
            "# Procedure",
            "1. Collect logs with ezBMC.", "2. Run a graceful ACPI shutdown (chassis power soft).",
            "3. Confirm power is off.", "4. Pull the tray and move it to the hospital rack.",
            "5. Open a support case; support opens a Part Only work order.",
            "6. Receive the replacement tray and record its service tag.",
            "7. Move the handles to the replacement.", "8. Move the rails to the replacement.",
            "9. Move the internal drive and the front drives.", "10. Submit the swap form.",
            "# Verification", "POST completes, all sensors read ok, the tray joins the fabric. " * 2,
            "# Records", "Ticket, work order number, old and new service tags, swap form. " * 2]
    with open(os.path.join(wd(), "SOP-CT-SWAP.md"), "w") as f:
        f.write("\n".join(body) + "\n")


def t301():
    code = ("#!/bin/bash\nset -o pipefail\nif [ $# -ne 2 ]; then echo \"usage: $0 <BMC_IP> <SERVICE_TAG>\" >&2; exit 2; fi\n"
            "ip=$1; tag=$2\nipmitool -I lanplus -H \"$ip\" -U admin -P admin sel -v list | tee -a \"$tag-sel.txt\" || exit 1\n"
            "ipmitool -I lanplus -H \"$ip\" -U admin -P admin sdr elist | tee -a \"$tag-sdr.txt\" || exit 1\n"
            "curl -sfk -u 'admin:admin' \"https://$ip/redfish/v1/Systems/HGX_Baseboard_0/LogServices/EventLog/Entries\" | jq | tee -a \"$tag-HMCevents.txt\" || exit 1\n")
    p = os.path.join(wd(), "collect_ct_logs.sh")
    with open(p, "w") as f:
        f.write(code)
    os.chmod(p, 0o755)


def t302():
    code = ("#!/bin/bash\nfor i in $(seq 11 28); do\n  ip=192.168.8.$i\n"
            "  ipmitool -I lanplus -H $ip -U admin -P admin sdr elist | awk -F'|' -v ip=$ip '$3 ~ /cr|nc/ {print ip, $0}'\ndone\n")
    p = os.path.join(wd(), "rack_sweep.sh")
    with open(p, "w") as f:
        f.write(code)
    os.chmod(p, 0o755)


def grade():
    p = subprocess.run(["dclab", "grade"], env=ENV, capture_output=True, text=True)
    return p.returncode, p.stdout


def main():
    want = sys.argv[1:]
    sols = {k[1:]: v for k, v in globals().items() if k.startswith("t") and k[1:].isdigit()}
    bad = []
    for num in sorted(sols):
        if want and num not in want:
            continue
        subprocess.run(["dclab", "start", num], env=ENV, capture_output=True)
        rc0, out0 = grade()
        t0 = time.time()
        try:
            sols[num]()
            err = None
        except AssertionError as e:
            err = f"assert: {str(e)[-300:]}"
        rc1, out1 = grade()
        ok = rc0 == 2 and rc1 == 0 and not err
        print(f"{'OK  ' if ok else 'FAIL'} DCOPS-{num}  fresh={'fails' if rc0 == 2 else 'PASSES(!)'}  "
              f"solved={'passes' if rc1 == 0 else 'fails'}  {time.time() - t0:.0f}s" + (f"  {err}" if err else ""))
        if not ok:
            bad.append(num)
            print(out0 if rc0 != 2 else out1)
    print(f"\n{'ALL OK' if not bad else 'FAILED: ' + ' '.join(bad)}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
