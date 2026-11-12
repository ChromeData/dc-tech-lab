"""Assemble the demo video: path-traced fly-through intro + the screen recording of the lab in use.

    python tools/make_video.py <screen_recording.webm> [output.mp4]
"""
import glob
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
FLY = os.path.join(ROOT, "blender", "renders", "fly3")
OUT = os.path.join(HERE, "out")
W, H, FPS = 1600, 900, 30
FONT = "C\\:/Windows/Fonts/segoeuib.ttf"
FF = shutil.which("ffmpeg") or "ffmpeg"


def run(args):
    p = subprocess.run([FF, "-y", "-hide_banner", "-loglevel", "error"] + args, capture_output=True, text=True)
    if p.returncode:
        print(p.stderr[-1500:])
        sys.exit(1)


def text(s, y, size, start, end, color="white"):
    return (f"drawtext=fontfile='{FONT}':text='{s}':fontcolor={color}:fontsize={size}:x=70:y={y}:"
            f"shadowcolor=black@0.7:shadowx=2:shadowy=2:alpha='if(lt(t,{start}),0,if(lt(t,{start}+0.6),(t-{start})/0.6,"
            f"if(lt(t,{end}),1,if(lt(t,{end}+0.6),1-(t-{end})/0.6,0))))'")


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    screen = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "DC-Lab-demo.mp4")
    n = 0 if screen.endswith(".txt") or "--no-intro" in sys.argv else len(glob.glob(os.path.join(FLY, "f_*.jpg")))
    intro = os.path.join(OUT, "intro.mp4")
    body = os.path.join(OUT, "body.mp4")
    enc = ["-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p", "-r", str(FPS)]
    if n:
        dur = n / (FPS / 2)                       # half speed, in-between frames interpolated
        vf = ",".join([f"scale={W}:{H}:flags=lanczos", f"minterpolate=fps={FPS}:mi_mode=mci:mc_mode=aobmc:vsbmc=1",
                       "tpad=stop_mode=clone:stop_duration=1.2",
                       text("DC LAB", 640, 64, 0.4, dur - 0.2, "0xf5b301"),
                       text("GB200 NVL72 rack R12   \\|   every frame path-traced in Blender Cycles", 720, 28, 0.9, dur - 0.2)])
        run(["-framerate", str(FPS // 2), "-i", os.path.join(FLY, "f_%04d.jpg"), "-vf", vf] + enc + [intro])
    if screen.endswith(".txt"):      # frames captured by record_demo.py --hq
        run(["-f", "concat", "-safe", "0", "-i", screen, "-vf", f"fps={FPS},scale=1920:1080:flags=lanczos",
             "-c:v", "libx264", "-preset", "slow", "-crf", "17", "-pix_fmt", "yuv420p", "-an", body])
    else:
        run(["-i", screen, "-vf", f"scale={W}:{H}:flags=lanczos,fps={FPS}"] + enc + ["-an", body])
    if not n:
        shutil.copy(body, out)
    else:
        d = dur + 1.2
        run(["-i", intro, "-i", body, "-filter_complex", f"[0:v][1:v]xfade=transition=fade:duration=0.8:offset={d - 0.8:.2f},format=yuv420p[v]",
             "-map", "[v]"] + enc + [out])
    print("video:", os.path.abspath(out), f"{os.path.getsize(out) / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
