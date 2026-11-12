"""Drive the DC Lab web app with a real browser: test it and record the demo video.

    python tools/record_demo.py [live] [bench] [quiz] [--video]

Needs the lab running (START-DCLAB.ps1). Screenshots go to tools/out, the video to tools/out/video.
"""
import math
import os
import subprocess
import sys
import time

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
os.makedirs(OUT, exist_ok=True)
PORT = 8770
HQ = "--hq" in sys.argv
W, H = (1920, 1080) if HQ else (1600, 900)
args = [a for a in sys.argv[1:] if not a.startswith("--")] or ["walk", "live", "bench", "quiz"]
VIDEO = "--video" in sys.argv
I = "ipmitool -I lanplus -H {ip} -U admin -P admin"

CURSOR = """
(() => {
  const add = () => {
    const c = document.createElement('div');
    c.id = 'fakecursor';
    c.style.cssText = 'position:fixed;left:0;top:0;width:22px;height:22px;z-index:99999;pointer-events:none;' +
      'background:radial-gradient(circle,#fff 0 3px,rgba(245,179,1,.9) 4px 7px,rgba(245,179,1,0) 8px);border-radius:50%;' +
      'transform:translate(-50%,-50%);transition:width .12s,height .12s';
    document.body.appendChild(c);
    addEventListener('mousemove', (e) => { c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px'; }, true);
    addEventListener('mousedown', () => { c.style.width = c.style.height = '34px'; }, true);
    addEventListener('mouseup', () => { c.style.width = c.style.height = '22px'; }, true);
  };
  if (document.body) add(); else addEventListener('DOMContentLoaded', add);
})();
"""


class Capture:
    """Grab the page frame by frame at high JPEG quality (much sharper than the built-in video recorder)."""

    def __init__(self, page, outdir):
        import base64
        import shutil
        self.b64 = base64
        self.dir = outdir
        shutil.rmtree(outdir, ignore_errors=True)
        os.makedirs(outdir)
        self.cdp = page.context.new_cdp_session(page)
        self.frames = []
        self.cdp.on("Page.screencastFrame", self._frame)

    def _frame(self, ev):
        name = f"{len(self.frames):06d}.jpg"
        with open(os.path.join(self.dir, name), "wb") as f:
            f.write(self.b64.b64decode(ev["data"]))
        self.frames.append((name, ev["metadata"]["timestamp"]))
        self.cdp.send("Page.screencastFrameAck", {"sessionId": ev["sessionId"]})

    def start(self):
        self.cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 90, "everyNthFrame": 2})

    def stop(self):
        self.cdp.send("Page.stopScreencast")
        path = os.path.join(self.dir, "list.txt")
        with open(path, "w") as f:
            for i, (name, ts) in enumerate(self.frames):
                nxt = self.frames[i + 1][1] if i + 1 < len(self.frames) else ts + 0.04
                f.write(f"file '{name}'\nduration {max(0.001, nxt - ts):.4f}\n")
            if self.frames:
                f.write(f"file '{self.frames[-1][0]}'\n")
        return path


def wsl(cmd):
    return subprocess.run(["wsl", "-d", "Ubuntu", "-e", "bash", "-lc", cmd], capture_output=True, text=True).stdout.strip()


class Demo:
    def __init__(self, page):
        self.p = page
        self.shots = 0

    def shot(self, name):
        self.shots += 1
        self.p.screenshot(path=os.path.join(OUT, f"{self.shots:02d}_{name}.png"))

    def state(self):
        return self.p.evaluate("fetch('/api/state').then(r => r.json())")

    def settle(self, extra=0.4):
        for _ in range(60):
            if self.p.evaluate("window.dclab.settled()"):
                break
            time.sleep(0.1)
        time.sleep(extra)

    def move(self, x, y, steps=18):
        self.p.mouse.move(x, y, steps=steps)

    # ---- terminals
    def focus_term(self, n):
        box = self.p.locator(f"#term{n}").bounding_box()
        self.move(box["x"] + box["width"] * 0.5, box["y"] + box["height"] * 0.6, 12)
        self.p.mouse.click(box["x"] + box["width"] * 0.5, box["y"] + box["height"] * 0.6)

    def text(self, n):
        return self.p.evaluate(f"document.querySelector('#term{n} .xterm-rows').innerText")

    def run(self, n, cmd, wait=None, timeout=40, pause=0.9, delay=14):
        self.focus_term(n)
        self.p.keyboard.type(cmd, delay=delay)
        time.sleep(0.25)
        self.p.keyboard.press("Enter")
        if wait:
            self.wait(n, wait, timeout)
        time.sleep(pause)

    def wait(self, n, needle, timeout=40):
        end = time.time() + timeout
        while time.time() < end:
            if needle in self.text(n).replace(" ", " "):
                return True
            time.sleep(0.2)
        print(f"   !! window {n}: never saw {needle!r}")
        return False

    # ---- 3D
    def click3d(self, model, gid=None, sub=None, ids=None):
        """Click a part on the picture. gid = part group, sub = busbar section, ids = raw ID list."""
        import json as _j
        arg = _j.dumps(ids) if ids is not None else _j.dumps(gid)
        js = f"window.dclab.screenOf('{model}', {arg}, {_j.dumps(sub)})"
        pos = prev = None
        for _ in range(30):          # wait until the view has stopped moving
            pos = self.p.evaluate(js)
            if pos and pos == prev:
                break
            prev = pos
            time.sleep(0.15)
        if not pos:
            print(f"   !! no clickable spot for {model}/{gid or ids}/{sub}")
            return False
        self.move(pos["x"], pos["y"], 22)
        time.sleep(0.3)
        self.p.mouse.click(pos["x"], pos["y"])
        time.sleep(0.8)
        return True

    def orbit(self, dx, dy=0, steps=40):
        box = self.p.locator("#gl").bounding_box()
        vis = self.p.evaluate("(document.querySelector('body.mode-live #live, body.mode-quiz #quiz') || {getBoundingClientRect: () => ({left: innerWidth})}).getBoundingClientRect().left")
        x, y = vis * 0.5, box["y"] + box["height"] * 0.55
        self.move(x, y, 10)
        self.p.mouse.down()
        self.p.mouse.move(x + dx, y + dy, steps=steps)
        self.p.mouse.up()
        time.sleep(0.3)

    def opt(self, text):
        b = self.p.locator("#qbody .opt", has_text=text).first
        try:
            b.wait_for(timeout=4000)
        except Exception:
            self.shot("FAIL_opt")
            print("   !! option not shown:", text, "| step:", " / ".join(self.p.locator("#qbody").inner_text()[:160].split()),
                  "| feedback:", self.p.locator("#qfeedback").inner_text())
            raise
        box = b.bounding_box()
        self.move(box["x"] + 60, box["y"] + box["height"] / 2, 14)
        time.sleep(0.2)
        b.click()
        time.sleep(0.75)

    def num(self, value):
        self.p.locator("#qin").click()
        self.p.keyboard.type(str(value), delay=90)
        time.sleep(0.3)
        self.p.keyboard.press("Enter")
        time.sleep(0.9)

    def enter(self, pause=1.0):
        self.p.keyboard.press("Enter")
        time.sleep(pause)


PATH_JS = """(t) => {
  const ST = window.dclab.ST, s = window.dclab.V.station, prev = { [s]: null }, q = [s];
  while (q.length) { const n = q.shift(); if (n === t) break; for (const m of ST[n].nb) if (!(m in prev)) { prev[m] = n; q.push(m); } }
  const out = [];
  for (let n = t; n && n !== s; n = prev[n]) out.unshift(n);
  return out;
}"""
TURN_JS = """(a) => {
  const V = window.dclab.V, y = V.goal ? V.goal.yaw : V.yaw;
  return ((a - y + Math.PI) % (2 * Math.PI) + 2 * Math.PI) % (2 * Math.PI) - Math.PI;
}"""
BEARING_JS = """(n) => { const ST = window.dclab.ST, a = ST[window.dclab.V.station].pos, b = ST[n].pos; return Math.atan2(b[1] - a[1], b[0] - a[0]); }"""


def face(d, angle, pause=0.5):
    """Turn with the arrow keys until we look along `angle` (30 degrees per press)."""
    for _ in range(12):
        diff = d.p.evaluate(TURN_JS, angle)
        if abs(diff) <= math.pi / 12 + 0.02:
            break
        d.p.keyboard.press("ArrowLeft" if diff > 0 else "ArrowRight")
        time.sleep(pause)


def walk_to(d, target, pause=0.8):
    """Arrow keys only: turn toward the next viewpoint on the way, step, repeat."""
    for _ in range(40):
        path = d.p.evaluate(PATH_JS, target)
        if not path:
            break
        face(d, d.p.evaluate(BEARING_JS, path[0]))
        d.p.keyboard.press("ArrowUp")
        time.sleep(pause)
        d.settle(0.05)
    return d.p.evaluate("window.dclab.V.station") == target


def walk(d):
    """Arrow keys: walk from the main floor to rack R12, then open the ticket board."""
    p = d.p
    p.evaluate("window.dclab.station('hall')")
    time.sleep(2.5)
    d.shot("walk_hall")
    box = p.locator("#gl").bounding_box()
    vis = p.evaluate("document.querySelector('#live').getBoundingClientRect().left")
    d.move(vis * 0.5, box["height"] * 0.8, 14)
    p.mouse.click(vis * 0.5, box["height"] * 0.8)          # focus the hall (floor: nothing to pick)
    d.orbit(-300, -20, 60)                                  # look around: the glass room, then back
    time.sleep(0.5)
    d.orbit(300, 20, 60)
    time.sleep(0.6)
    ok = walk_to(d, "front")
    face(d, math.pi / 2)                                    # square up to the rack
    time.sleep(1.2)
    d.shot("walk_arrive")
    here = p.evaluate("window.dclab.V.station")
    print("   walked to:", here)
    p.evaluate("window.dclab.station('front')")
    time.sleep(1.0)
    p.locator("#ltabs button[data-tab=board]").click()
    time.sleep(2.0)
    d.shot("walk_board")
    row = p.locator("#tlist .trow", has_text="CT07").first
    bx = row.bounding_box()
    d.move(bx["x"] + 120, bx["y"] + bx["height"] / 2, 16)
    row.click()
    time.sleep(2.2)
    d.shot("walk_ticket")
    return ok and here == "front"


def live(d):
    """Ticket 104: leak alarm from an old BMC. Logs, firmware, SOL in window 2, power on, grade."""
    if d.p.locator("#tstart").count() and d.p.locator("#tstart").is_visible():
        btn = d.p.locator("#tstart")
        bx = btn.bounding_box()
        d.move(bx["x"] + 40, bx["y"] + 14, 14)
        btn.click()                                        # "Start in Window 1" types the command for us
        d.wait(1, "dclab grade", 30)
        time.sleep(3.0)
    else:
        d.run(1, "dclab start 104", "dclab grade", pause=3.0)
    st = d.state()
    ct = st["cts"]["CT07"]
    i = I.format(ip=ct["ip"])
    tag = ct["tag"]
    d.click3d("rack", ids=[7])
    d.shot("live_ticket")
    d.run(1, "dcgo")
    d.run(1, f"{i} sdr elist | tee -a {tag}-sdr.txt", "HMC_Status", pause=2.2)
    d.shot("live_sdr")
    d.run(1, f"{i} sel -v list | tee -a {tag}-sel.txt", "Description", pause=1.2)
    d.run(1, f"curl -sk -u admin:admin https://{ct['ip']}/redfish/v1/Systems/HGX_Baseboard_0/LogServices/EventLog/Entries | jq | tee -a {tag}-HMCevents.txt",
          "Members", pause=1.2)
    d.run(1, "clear", pause=0.3)
    d.run(1, f"curl -sk -u admin:admin https://{ct['ip']}/redfish/v1/UpdateService/FirmwareInventory/BMC_Firmware | jq .Version", "25.06", pause=1.6)
    d.run(1, "dclab matrix", "Rules:", pause=2.2)
    d.run(1, "tech fwupdate CT07 bmc 26.01.10001500", "done.", pause=1.0)
    d.run(2, f"{i} sol activate", "SOL Session operational", pause=1.0)
    d.run(1, f"{i} chassis power on", "Up/On", pause=0.5)
    d.wait(2, "provision-ct login", 45)
    d.shot("live_post")
    time.sleep(1.5)
    d.focus_term(2)
    d.p.keyboard.press("Enter")
    time.sleep(0.4)
    d.p.keyboard.type("~.", delay=120)
    d.wait(2, "terminated ipmitool", 10)
    d.run(1, "clear", pause=0.3)
    d.run(1, f"{i} sdr elist | grep Lea", "Cha0LeaDete1Mani", pause=1.6)
    d.run(1, "echo 'Ch0LeaDet0ColPla (M0_0) read 0.66 V. BMC was below 25.09.30001500. Updated the BMC with the CT off.' > resolution.txt", pause=0.8)
    d.run(1, "dclab grade", "Ticket passed", pause=4.0)
    d.shot("live_grade")
    return "DCOPS-104" in d.state()["passed"]


def bench(d):
    """Ticket 106 hands-on part: pull the tray, open it, re-torque the busbar. The 3D view follows."""
    d.run(1, "clear", pause=0.2)
    d.run(1, "dclab start 106", "dclab grade", pause=2.0)
    d.run(1, "clear", pause=0.2)
    d.run(1, "tech pull CT12", "bench", pause=2.6)
    d.run(1, "tech open CT12", "lid open", pause=2.2)
    d.shot("bench_open")
    d.run(1, "tech inspect CT12 busbar", "under-torqued", pause=3.2)
    d.shot("bench_busbar")
    d.run(1, "tech loosen CT12 busbar", "Loosened", pause=1.6)
    for sec in ("back", "front", "middle"):
        d.run(1, f"tech torque CT12 busbar --section {sec} --inlb 20", "20 in-lb", pause=1.4)
    d.run(1, "tech uv CT12", "No coolant", pause=2.6)
    d.run(1, "tech close CT12", "closed", pause=1.2)
    d.run(1, "tech insert CT12", "inserted", pause=2.6)
    d.shot("bench_back")
    st = d.state()
    return st["cts"]["CT12"]["location"] == "rack"


def quiz(d):
    """Work orders: ID the part on the model, then do what the slide says."""
    p = d.p
    p.locator("#bar nav button[data-mode=quiz]").click()
    time.sleep(2.0)
    d.settle(1.0)
    ok = True
    # 1. busbar
    p.evaluate("window.dclab.go('wo_busbar')")
    time.sleep(2.2)
    d.orbit(-150, 0)
    time.sleep(0.8)
    ok &= d.click3d("tray", "busbar")
    d.opt("Loosen ALL the screws")
    d.num(20)
    time.sleep(1.6)
    for sec in ("back", "front", "middle"):
        ok &= d.click3d("tray", "busbar", sec)
    d.shot("quiz_busbar")
    d.enter(2.2)
    d.enter(1.2)
    # 2. HMC
    p.evaluate("window.dclab.go('wo_hmc')")
    time.sleep(2.0)
    ok &= d.click3d("tray", "hmc")
    time.sleep(0.6)
    ok &= d.click3d("tray", "hmc")
    ok &= d.click3d("tray", "slimline")
    d.shot("quiz_hmc")
    d.enter(2.0)
    d.enter(1.2)
    # 3. leak sensor M1_0
    p.evaluate("window.dclab.go('wo_leak_M1_0')")
    time.sleep(2.0)
    ok &= d.click3d("tray", "leak10")
    d.num("1.75")
    for t in ("Verify the BMC revision", "Check with a UV light", "Clean the leak sensor", "use a zip tie"):
        d.opt(t)
    d.shot("quiz_leak")
    d.enter(2.2)
    d.enter(1.2)
    # 4. CT swap: four parts move
    p.evaluate("window.dclab.go('wo_swap')")
    time.sleep(2.0)
    for g in ("handles", "rails", "nvme", "m2"):
        ok &= d.click3d("tray", g)
    d.opt("Submit the swap form")
    d.shot("quiz_swap")
    d.enter(2.0)
    d.enter(1.2)
    # 5. rack: NVLink switch
    p.evaluate("window.dclab.go('wo_switch')")
    time.sleep(2.4)
    ok &= d.click3d("rack", "sw")
    d.opt("Production halts on the whole rack")
    for t in ("Factory reset the spare switch", "Remove the failed switch", "Install the spare", "ZTP runs"):
        d.opt(t)
    d.num(1)
    d.shot("quiz_switch")
    d.enter(2.2)
    # 6. rack rear: cable cartridge label
    d.enter(1.0)
    p.evaluate("window.dclab.go('wo_cart')")
    time.sleep(2.6)
    ok &= d.click3d("rack", "cc")
    ok &= d.click3d("rack", ids=[49])
    d.opt("The NVIDIA SN")
    d.num(144)
    d.shot("quiz_cart")
    d.enter(2.5)
    q = p.evaluate("({right: window.dclab.Q.right, asked: window.dclab.Q.asked})")
    print("   quiz:", q)
    return ok and q["right"] == q["asked"] == 6


def main():
    token = wsl("cat ~/dclab/state/web.token")
    if not token:
        sys.exit("Lab web server is not running. Start it with START-DCLAB.ps1")
    wsl("rm -f ~/dclab/state/progress.json; rm -rf ~/dclab/work/* ~/ezBMC_Logs")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False, args=["--ignore-gpu-blocklist", "--enable-gpu", "--use-angle=d3d11",
                                                           f"--window-size={W},{H + 90}", "--window-position=40,20"])
        kw = dict(viewport={"width": W, "height": H}, device_scale_factor=1)
        if VIDEO:
            kw.update(record_video_dir=os.path.join(OUT, "video"), record_video_size={"width": W, "height": H})
        ctx = browser.new_context(**kw)
        ctx.add_init_script(CURSOR)
        page = ctx.new_page()
        errors = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"http://localhost:{PORT}/?t={token}")
        page.wait_for_function("window.dclab && document.querySelector('#loading').style.display === 'none'", timeout=60000)
        time.sleep(3.0)
        cap = None
        if HQ:
            cap = Capture(page, os.path.join(OUT, "capture"))
            cap.start()
            time.sleep = lambda s: page.wait_for_timeout(max(1, int(s * 1000)))   # keep frames flowing while we wait
        d = Demo(page)
        results = {}
        for part in args:
            results[part] = bool({"walk": walk, "live": live, "bench": bench, "quiz": quiz}[part](d))
            print(f"{'OK  ' if results[part] else 'FAIL'} {part}")
        time.sleep(1.5)
        if cap:
            print("frames:", cap.stop(), len(cap.frames))
        path = page.video.path() if VIDEO else None
        ctx.close()
        browser.close()
        if errors:
            print("console errors:", errors[:5])
        if path:
            print("video:", path)
    return 0 if all(results.values()) and not errors else 1


if __name__ == "__main__":
    sys.exit(main())
