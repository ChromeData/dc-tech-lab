"""Read every ID image and write img/ids.json: for each part id, one point safely inside it and its pixel area.

The web app uses these points to place labels and to turn the view toward a part.
    python tools/make_ids.py
"""
import glob
import json
import os

import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None
IMG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lab", "web", "img")
VALID = set(range(1, 51)) | set(range(101, 119)) | set(range(121, 130)) | set(range(141, 159)) | set(range(161, 179)) \
    | set(range(181, 190)) | {201, 202, 203}


def erode(m, r):
    out = m.copy()
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            if dx * dx + dy * dy <= r * r and (dx or dy):
                out &= np.roll(np.roll(m, dy, 0), dx, 1)
    return out


def points(path, r):
    a = np.array(Image.open(path).convert("RGB"))[:, :, 0]
    h, w = a.shape
    out, odd = {}, []
    for i in np.unique(a):
        i = int(i)
        if i == 0:
            continue
        if i not in VALID:
            odd.append(i)
            continue
        ys, xs = np.nonzero(a == i)
        area = len(ys)
        y0, y1, x0, x1 = max(0, ys.min() - r - 1), ys.max() + r + 2, max(0, xs.min() - r - 1), xs.max() + r + 2
        m = a[y0:y1, x0:x1] == i
        e = erode(m, r) if area > 80 else m
        if not e.any():
            e = m
        ey, ex = np.nonzero(e)
        k = int(np.argmin((ey - ey.mean()) ** 2 + (ex - ex.mean()) ** 2))
        out[i] = [round((x0 + ex[k] + 0.5) / w, 5), round(1 - (y0 + ey[k] + 0.5) / h, 5), int(area)]
    return out, odd


def main():
    data = {"pano": {}, "tray": {}}
    for f in sorted(glob.glob(os.path.join(IMG, "*_id.png"))):
        key = os.path.basename(f)[:-7]
        kind = "pano" if key.startswith("pano") else "tray"
        pts, odd = points(f, 2 if kind == "pano" else 3)
        data[kind][key] = pts
        print(f"{key}: {len(pts)} ids" + (f"   UNEXPECTED VALUES {odd[:12]}" if odd else ""))
    with open(os.path.join(IMG, "ids.json"), "w") as fh:
        json.dump(data, fh, separators=(",", ":"))
    print("wrote ids.json")


if __name__ == "__main__":
    main()
