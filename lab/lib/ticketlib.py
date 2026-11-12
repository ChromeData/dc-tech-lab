"""Ticket registry and the grading context shared by all ticket files."""
import glob
import json
import os
import re

import core

REG = {}
ORDER = []


class Ticket:
    def __init__(self, tid, title, track, ct=None, body="", teach=(), do=(), nudge="", walk=(), show=(),
                 setup=None, check=None):
        self.tid, self.title, self.track, self.ct = tid, title, track, ct
        self.body, self.teach, self.do = body, list(teach), list(do)
        self.nudge, self.walk, self.show = nudge, list(walk), list(show)
        self.setup, self.check = setup, check


def register(**kw):
    t = Ticket(**kw)
    REG[t.tid] = t
    ORDER.append(t.tid)
    return t


def fill(text, st, t):
    """Replace {ip} {tag} {ct} {wd} with this ticket's tray values."""
    wd = core.workdir(st)
    out = text.replace("{wd}", wd)
    if t.ct and t.ct in st["cts"]:
        ct = st["cts"][t.ct]
        out = out.replace("{ip}", ct["bmc_ip"]).replace("{tag}", ct["tag"]).replace("{ct}", ct["name"])
    return out


class Ctx:
    def __init__(self, st):
        self.st = st
        self.wd = core.workdir(st)
        self.A = st["actions"]
        self.results = []

    def c(self, label, ok):
        self.results.append((label, bool(ok)))
        return bool(ok)

    def ct(self, name):
        return self.st["cts"][name]

    def acts(self, kind, **kw):
        return [a for a in self.A if a["k"] == kind and all(a.get(k) == v for k, v in kw.items())]

    def ipmi(self, ct, *starts):
        return [a for a in self.A if a["k"] == "ipmitool" and a.get("ct") == ct
                and any(a["cmd"].startswith(s) for s in starts)]

    def first_t(self, acts):
        return acts[0]["t"] if acts else None

    def last_t(self, acts):
        return acts[-1]["t"] if acts else None

    def before(self, a, b):
        """True when a happened, and happened before b (or b never happened)."""
        return a is not None and (b is None or a < b)

    def files(self, pat):
        return sorted(glob.glob(os.path.join(self.wd, pat)))

    def read(self, pat):
        out = []
        for f in self.files(pat):
            try:
                with open(f, encoding="utf-8", errors="replace") as fh:
                    out.append(fh.read())
            except OSError:
                pass
        return "\n".join(out)

    def grep(self, pat, rx):
        return bool(re.search(rx, self.read(pat), re.I))

    def kv(self, name):
        d = {}
        for line in self.read(name).splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                d[k.strip().lower()] = v.strip()
        return d

    def violations(self):
        return [a["msg"] for a in self.acts("violation")]

    def redfish(self, ct, substr):
        hits = []
        try:
            with open(core.REDFISH_LOG) as f:
                for line in f:
                    try:
                        e = json.loads(line)
                    except ValueError:
                        continue
                    if e["t"] >= self.st["started"] and e.get("ct") == ct and substr in e["path"] and e["code"] == 200:
                        hits.append(e)
        except OSError:
            pass
        return hits


# ------------------------------------------------------------ shared checks
def logs_ok(x, ct, kinds=("sel", "sdr", "hmc")):
    tag = ct["tag"]
    if "sel" in kinds:
        x.c(f"SEL saved in {tag}-sel.txt", x.grep(f"{tag}-sel.txt", r"SEL Record ID|\| Asserted|SEL has no entries"))
    if "sdr" in kinds:
        x.c(f"SDR saved in {tag}-sdr.txt", x.grep(f"{tag}-sdr.txt", r"Ch0LeaDet0ColPla"))
    if "hmc" in kinds:
        x.c(f"HMC event log saved in {tag}-HMCevents.txt", x.grep(f"{tag}-HMCevents.txt", r'"Members"'))


def logs_first(x, ct, fix_acts, what="the fix"):
    t_logs = x.first_t(x.ipmi(ct["name"], "sel", "sdr")) or x.first_t(x.acts("ezbmc", ct=ct["name"]))
    x.c(f"Logs were collected before {what}", x.before(t_logs, x.first_t(fix_acts)))


def no_viol(x):
    v = x.violations()
    x.c("No safety or process violations" + (f"  ->  {v[0]}" if v else ""), not v)


def healthy(x, ct):
    ok = ct["power"] == "on" and ct["location"] == "rack" and not core.blocked(ct) and ct.get("out0") != "die"
    x.c(f"{ct['name']} is back in the rack, powered on and healthy", ok)


def resolution(x, *groups):
    text = x.read("resolution.txt").lower()
    ok = bool(text.strip()) and all(any(k in text for k in g) for g in groups)
    x.c("resolution.txt names the cause and the fix in your own words", ok)


def failed_boot_history(ct, ago=600):
    """Make the tray look like it tried to boot `ago` seconds back and shut itself down."""
    n0 = len(ct["sel"])
    core.power_on(ct)
    ct["power_t"] -= ago
    for e in ct["sel"][n0:]:
        e["t"] -= ago
    core.settle(ct)
    ct["in_job"] = False


def parked_at_shell(ct, ago=900):
    ct["in_job"] = False
    ct["out0"] = core.first_outcome(ct)
    ct["power"] = "on"
    ct["power_t"] = core.time.time() - ago
