"""Browser test of the rack-side work orders (no tray frames needed)."""
import os
import sys
import time

sys.argv = [sys.argv[0]]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import record_demo as r  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

token = r.wsl("cat ~/dclab/state/web.token")
with sync_playwright() as pw:
    b = pw.chromium.launch(headless=False, args=["--ignore-gpu-blocklist", "--enable-gpu", "--use-angle=d3d11", "--window-size=1600,990"])
    ctx = b.new_context(viewport={"width": 1600, "height": 900})
    ctx.add_init_script(r.CURSOR)
    page = ctx.new_page()
    errs = []
    page.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.goto(f"http://localhost:8770/?t={token}&mode=quiz")
    page.wait_for_function("window.dclab && document.querySelector('#loading').style.display === 'none'", timeout=60000)
    time.sleep(2)
    d = r.Demo(page)
    ok = True
    page.evaluate("window.dclab.go('wo_switch')")
    time.sleep(2.5)
    ok &= d.click3d("rack", "sw")
    d.opt("Production halts on the whole rack")
    for t in ("Factory reset the spare switch", "Remove the failed switch", "Install the spare", "ZTP runs"):
        d.opt(t)
    d.num(1)
    d.shot("rack_switch")
    d.enter(1.5)
    d.enter(1.0)
    page.evaluate("window.dclab.go('wo_cart')")
    time.sleep(3.0)
    ok &= d.click3d("rack", "cc")
    ok &= d.click3d("rack", ids=[49])
    d.opt("The NVIDIA SN")
    d.num(144)
    d.shot("rack_cart")
    d.enter(1.5)
    d.enter(1.0)
    page.evaluate("window.dclab.go('wo_power_tag')")
    time.sleep(3.0)
    ok &= d.click3d("rack", ids=[50])
    ok &= d.click3d("rack", "rbus")
    d.shot("rack_power")
    d.enter(1.5)
    d.enter(1.0)
    page.evaluate("window.dclab.go('wo_rack_tag')")
    time.sleep(3.0)
    ok &= d.click3d("rack", ids=[47])
    for t in ("Back of the rack, right corner", "Top center", "Front right corner"):
        d.opt(t)
    page.locator("#woconfirm").click()
    time.sleep(0.8)
    d.shot("rack_tag")
    d.enter(1.5)
    q = page.evaluate("({right: window.dclab.Q.right, asked: window.dclab.Q.asked})")
    print("clicks ok:", ok, "| quiz:", q, "| errors:", errs[:4])
    ctx.close()
    b.close()
