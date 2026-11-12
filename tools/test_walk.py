"""Walking test: arrow keys, W A S D, the floor plan, and keys typed into a terminal.

    python tools/test_walk.py

Needs the lab running (START-DCLAB.ps1). Drives a real browser and prints OK / FAIL per check.
"""
import math
import sys

from playwright.sync_api import sync_playwright

import record_demo as rd

FAILS = []


def check(name, ok, detail=""):
    print(f"{'OK  ' if ok else 'FAIL'} {name}" + (f"   ({detail})" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def main():
    token = rd.wsl("cat ~/dclab/state/web.token")
    if not token:
        sys.exit("Lab web server is not running. Start it with START-DCLAB.ps1")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False, args=["--ignore-gpu-blocklist", "--enable-gpu", "--use-angle=d3d11",
                                                           "--window-size=1600,990", "--window-position=40,20"])
        page = browser.new_context(viewport={"width": 1600, "height": 900}).new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"http://localhost:{rd.PORT}/?t={token}")
        page.wait_for_function("window.dclab && document.querySelector('#loading').style.display === 'none'", timeout=60000)
        page.wait_for_timeout(2500)

        def here():
            return page.evaluate("window.dclab.V.station")

        def yaw():
            return page.evaluate("window.dclab.V.yaw")

        def settle():
            page.wait_for_function("window.dclab.settled()", timeout=8000)
            page.wait_for_timeout(250)

        def key(k, expect=None, name=None):
            page.keyboard.press(k)
            page.wait_for_timeout(150)
            settle()
            if expect:
                check(name or f"{k} -> {expect}", here() == expect, f"at {here()}")

        def has(name):
            return page.evaluate(f"fetch('img/pano_{name}.jpg').then(r => r.ok)")

        vis = page.evaluate("document.querySelector('#live').getBoundingClientRect().left")
        page.mouse.click(vis * 0.5, 760)                      # click the floor: focus the hall
        settle()
        check("starts in front of R12", here() == "front", here())

        key("ArrowDown", "c1", "ArrowDown steps back to the cross aisle")
        key("ArrowUp", "f06", "ArrowUp steps forward to the row")
        y0 = yaw()
        for _ in range(3):
            key("ArrowLeft")
        turned = (yaw() - y0) % (2 * math.pi)
        check("ArrowLeft x3 turns 90 degrees left", abs(turned - math.pi / 2) < 0.05, f"turned {turned:.2f} rad")
        key("ArrowUp", "front", "ArrowUp walks along the row")
        key("w", "f05", "W steps forward")
        key("s", "front", "S steps back")
        y1 = yaw()
        key("d")
        check("D turns right", abs(((y1 - yaw()) % (2 * math.pi)) - math.pi / 6) < 0.05)
        key("a")

        # a viewpoint that is not rendered yet must not break anything
        page.evaluate("window.dclab.station('f05')")
        settle()
        if not has("f04"):
            for _ in range(2):
                key("ArrowLeft")                               # the row runs along x: face it squarely
            page.keyboard.press("ArrowUp")
            page.wait_for_timeout(1500)
            check("missing viewpoint: stays put", here() == "f05", here())
        else:
            print("     (every viewpoint is rendered: skipped the missing-viewpoint check)")

        # floor plan: click the dot of c1
        pos = page.evaluate("""(() => {
          const c = document.querySelector('#map'), r = c.getBoundingClientRect(), p = window.dclab.ST.c1.pos;
          const k = Math.min((c.width - 24) / 22.4, (c.height - 24) / 15.8);
          const x = 12 + (p[0] + 9.2) * k, y = 12 + (3.4 - p[1]) * k;
          return { x: r.left + x / c.width * r.width, y: r.top + y / c.height * r.height };
        })()""")
        page.mouse.click(pos["x"], pos["y"])
        page.wait_for_timeout(300)
        settle()
        check("floor plan click goes to that spot", here() == "c1", here())

        # keys typed into a terminal belong to the terminal
        box = page.locator("#term1").bounding_box()
        page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        page.keyboard.press("ArrowUp")
        page.keyboard.type("w")
        page.wait_for_timeout(800)
        check("typing in a terminal does not walk", here() == "c1", here())
        page.keyboard.press("Backspace")

        # Front button brings you back
        page.locator("#views button[data-view=front]").click()
        page.wait_for_timeout(300)
        settle()
        check("Front button returns to R12", here() == "front", here())
        check("no script errors", not errors, "; ".join(errors[:3]))
        browser.close()
    print("\nALL OK" if not FAILS else f"\n{len(FAILS)} FAILED: {FAILS}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
