"""Serial-over-LAN console for the simulated compute trays.

What you see depends on the tray state: POST, the F2/F11 window, PXE, the EFI
shell, or the Support Live Image. Output is driven by the tray's power-on time,
so you only see POST if the console is open before you power the tray on.
"""
import os
import select
import signal
import sys
import termios
import time
import tty

import core
import liveimage

F2 = (b"\x1bOQ", b"\x1b[12~", b"\x1b[[B")
F11 = (b"\x1b[23~",)
FKEY_FROM, FKEY_TO = 6.0, 9.5
OUTCOME_AT = 9.5
DIE_CUT = 3.5
PROMPTS = {"shell": "Shell> ", "live": "root@liveimage:~# ", "login": "provision-ct login: "}


def post_lines(ct):
    fw = ct["fw"]
    bf3 = "detected" if ct["bf3_present"] else "NOT DETECTED"
    return [
        (0.5, f"Dell PowerEdge XE9712   BIOS {fw['bios']}   Service Tag {ct['tag']}", "post_start"),
        (1.2, "Initializing Grace CPU 0 (72 cores) ............ OK", None),
        (1.8, "Initializing Grace CPU 1 (72 cores) ............ OK", None),
        (2.6, "Memory training: 2 x 480 GB LPDDR5X ............ OK", None),
        (3.2, "Bianca board 0: GPU0 GPU1 (B200) ............... detected", None),
        (3.8, "Bianca board 1: GPU2 GPU3 (B200) ............... detected", None),
        (4.4, "ConnectX-7 mezz ports 1-4 ...................... detected", None),
        (4.8, f"BlueField-3 DPU (MT41692) ...................... {bf3}", None),
        (5.4, f"BMC {fw['bmc']}   HMC ready", None),
        (6.0, "Press <F2> System Setup, <F11> Boot Manager    (over SOL you can also type ESC then 2 / ESC then !)",
         "fkeys"),
    ]


def outcome_lines(ct, out, t0):
    L = []

    def add(d, txt, mark=None):
        L.append((t0 + d, txt, mark))

    def shell(t):
        add(t, "BdsDxe: No bootable option or device was found.")
        add(t + 0.8, "UEFI Interactive Shell v2.2")
        add(t + 1.0, "EDK II")
        add(t + 1.2, "UEFI v2.80 (Dell Inc., 0x00010000)")
        add(t + 1.4, "Mapping table")
        add(t + 1.6, "      FS0: Alias(s):HD0b:;BLK1:")
        add(t + 1.8, "     BLK0: Alias(s):")
        add(t + 2.2, "Press ESC in 5 seconds to skip startup.nsh or any other key to continue.")
        add(t + 4.2, PROMPTS["shell"], "shell")

    if out == "live":
        add(0.0, "Booting from USB: SanDisk Ultra (Support Live Image)", "live_boot")
        add(1.0, "EFI stub: Booting Linux Kernel...")
        add(1.8, "[    0.000000] Booting Linux on physical CPU 0x0000000000 [0x410fd4f0]")
        for i in range(4):
            add(2.2 + 0.2 * i, f"[    4.21{i}331] mlx5_core 000{i}:01:00.0: firmware version: {ct['fw']['cx7']}")
        if ct["bf3_present"]:
            add(3.1, f"[    4.902114] mlx5_core 0006:01:00.0: BlueField-3 firmware version: {ct['fw']['bf3']}")
        add(3.6, "Support Live Image 4.2 (dclab) -- Valet auto-run started (real time: 5-10 min)", "valet_start")
        add(4.4, "Valet: collecting mlxlink_info (network port state and health) ...")
        add(6.0, "Valet: collecting GPU snapshot (remapped rows, ECC) ...")
        add(7.6, "Valet: done. Results in /root/valet/ : mlxlink_info.txt  valet_summary.txt", "valet_done")
        add(8.0, "")
        add(8.1, PROMPTS["live"], "live")
        return L
    if out == "shell_direct":
        shell(0.2)
        return L
    add(0.0, "Checking Media Presence......")
    if not ct["bf3_present"]:
        add(1.2, "No network boot device found.", "pxe_fail")
        shell(2.0)
        return L
    add(1.0, "Media Present......")
    add(1.6, f">>Start PXE over IPv4 on MAC: {ct['mac']}.", "pxe_try")
    if out == "pxe":
        add(3.0, f"  Station IP address is 10.20.12.{100 + ct['slot']}")
        add(3.4, "  Server IP address is 10.20.0.5")
        add(3.8, "  NBP filename is shimaa64.efi")
        add(4.2, "  NBP filesize is 950640 Bytes")
        add(4.6, " Downloading NBP file...")
        add(5.8, "  Succeed to download NBP file.")
        add(6.6, "Loading provisioning image (hand-off to the provisioning team) ...", "pxe_ok")
        add(8.0, "")
        add(8.1, PROMPTS["login"], "login")
        return L
    msg = "  PXE-E16: No valid offer received." if core.vt(ct["fw"]["bf3"]) < (1, 3) \
        else "  PXE-E18: Server response timeout."
    add(6.0, msg, "pxe_fail")
    shell(7.0)
    return L


def timeline(ct):
    if ct["power"] != "on":
        return []
    T = ct["power_t"]
    out0 = ct.get("out0", "pxe")
    L = []
    for off, txt, mark in post_lines(ct):
        if out0 == "die" and off > DIE_CUT:
            break
        L.append((T + off, txt, mark))
    if out0 == "die":
        return L
    L += outcome_lines(ct, out0, T + OUTCOME_AT)
    for leg in ct["legs"]:
        L += outcome_lines(ct, leg["out"], leg["t"])
    return L


def current_mode(L, now):
    mode = None
    for t, _, mark in L:
        if t <= now:
            mode = mark if mark in PROMPTS else None
    return mode


def retry_outcome(ct):
    if ct["usb"]:
        return "live"
    return "pxe" if core.pxe_ok(ct) else "shell"


def bios_screen(ct):
    bf3 = "Present" if ct["bf3_present"] else "Not Detected"
    return (
        "\n=========================================================================\n"
        f" System Setup  -  PowerEdge XE9712    BIOS {ct['fw']['bios']}    Service Tag {ct['tag']}\n"
        "-------------------------------------------------------------------------\n"
        " Processors        : 2 x NVIDIA Grace (72 cores each)\n"
        " Memory            : 960 GB LPDDR5X\n"
        " GPUs              : 4 x B200 on 2 Bianca boards\n"
        " PCIe device inventory\n"
        "   Mezz  ConnectX-7 (MT4129) ports 1-4 ............ Present\n"
        f"   Slot  BlueField-3 DPU (MT41692) ................ {bf3}\n"
        "   M.2   Boot drive riser ......................... Present\n"
        "   NVMe  Front drive slots 0-3 .................... Present\n"
        " Network boot      : PXE device 1 = BlueField-3 port 0 (IPv4)\n"
        "-------------------------------------------------------------------------\n"
        " <ESC> exit setup and continue boot\n"
        "=========================================================================\n")


def bootmgr_screen(ct):
    s = "\n Boot Manager - One-Shot UEFI Boot Menu\n"
    if ct["bf3_present"]:
        s += f"   1) UEFI PXEv4: BlueField-3 Port 0 (MAC {ct['mac']})\n"
    s += "   2) UEFI Internal Shell\n"
    if ct["usb"]:
        s += "   3) UEFI USB: SanDisk Ultra (Support Live Image)\n"
    return s + " Type a number, or <ESC> to continue normal boot: "


class Session:
    def __init__(self, name):
        self.name = name
        self.clean = False
        self.line = ""
        self.bol = True
        self.tilde = False
        self.esc_t = 0.0
        self.menu = None
        self.mode = None

    def w(self, s):
        try:
            os.write(1, s.replace("\r\n", "\n").replace("\n", "\r\n").encode())
        except OSError:
            pass

    def _hup(self, *_):
        raise SystemExit(0)

    def run(self):
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd) if os.isatty(fd) else None
        signal.signal(signal.SIGHUP, self._hup)
        signal.signal(signal.SIGTERM, self._hup)
        try:
            if old:
                tty.setraw(fd)
            self.w("[SOL Session operational.  Use ~? for help]\n")
            self.loop(fd)
        finally:
            if old:
                try:
                    termios.tcsetattr(fd, termios.TCSADRAIN, old)
                except termios.error:
                    pass
            self.finish()
        return 0

    def finish(self):
        with core.rack() as st:
            s = st["cts"][self.name]["sol"]
            if s.get("pid") != os.getpid():
                return
            if self.clean:
                s.update(active=False, stale=False, pid=0)
                core.act(st, "sol_exit", ct=self.name, clean=True)
            else:
                s.update(stale=True, t=time.time())
                core.act(st, "sol_exit", ct=self.name, clean=False)

    def seen(self, ct, mark):
        ct["seen"].append({"m": mark, "boot": ct["boot_id"], "t": time.time()})

    def loop(self, fd):
        shown = time.time()
        while True:
            r, _, _ = select.select([fd], [], [], 0.15)
            now = time.time()
            with core.rack() as st:
                ct = st["cts"][self.name]
                if not ct["sol"]["active"] or ct["sol"].get("pid") != os.getpid():
                    self.w("\n[SOL payload deactivated by another session]\n")
                    return
                if not self.menu:
                    L = timeline(ct)
                    for t, txt, mark in L:
                        if shown < t <= now:
                            self.w(txt if mark in PROMPTS else txt + "\n")
                            if mark:
                                self.seen(ct, mark)
                            if mark == "valet_done":
                                liveimage.write_valet(st, ct)
                    shown = now
                    self.mode = current_mode(L, now)
                if r:
                    data = os.read(fd, 256)
                    if not data:
                        return
                    res = self.handle(st, ct, data)
                    if res == "quit":
                        self.clean = True
                        return
                    if res == "resync":
                        shown = time.time()

    # ------------------------------------------------------------ input
    def handle(self, st, ct, data):
        if data == b"\x1b":
            if self.menu:
                return self.leave_menu(st, ct)
            self.esc_t = time.time()
            return None
        if data.startswith(b"\x1b"):
            if data in F2:
                return self.fkey(st, ct, "F2")
            if data in F11:
                return self.fkey(st, ct, "F11")
            if self.menu and data[:1] == b"\x1b":
                return self.leave_menu(st, ct)
            return None
        res = None
        for ch in data.decode("utf-8", "replace"):
            if self.esc_t and time.time() - self.esc_t < 2.0 and ch in "2!":
                self.esc_t = 0.0
                res = self.fkey(st, ct, "F2" if ch == "2" else "F11") or res
                continue
            self.esc_t = 0.0
            r = self.char(st, ct, ch)
            if r == "quit":
                return "quit"
            res = r or res
        return res

    def char(self, st, ct, ch):
        if self.tilde:
            self.tilde = False
            if ch == ".":
                self.w("\n[terminated ipmitool]\n")
                return "quit"
            if ch == "?":
                self.w("~?\nSupported escape sequences:\n  ~.  terminate connection\n  ~B  send a BREAK\n"
                       "  ~?  this message\n  ~~  send the escape character by typing it twice\n"
                       "(Note that escapes are only recognized immediately after newline.)\n")
                return None
            if ch != "~":
                self.feed(st, ct, "~")
        elif ch == "~" and self.bol:
            self.tilde = True
            return None
        return self.feed(st, ct, ch)

    def feed(self, st, ct, ch):
        if self.menu:
            return self.menu_key(st, ct, ch)
        if ch in ("\r", "\n"):
            self.bol = True
            if self.mode:
                self.w("\n")
                cmd, self.line = self.line.strip(), ""
                return self.run_cmd(st, ct, cmd)
            return None
        self.bol = False
        if ch in ("\x7f", "\x08"):
            if self.mode and self.line:
                self.line = self.line[:-1]
                self.w("\b \b")
            return None
        if ch == "\x03":
            if self.mode == "live":
                self.w("^C\n" + PROMPTS["live"])
                self.line = ""
            return None
        if self.mode and ch.isprintable():
            self.line += ch
            self.w(ch)
        return None

    def fkey(self, st, ct, key):
        off = time.time() - ct["power_t"]
        ok = (ct["power"] == "on" and ct.get("out0") != "die" and not ct["legs"]
              and FKEY_FROM <= off < FKEY_TO and not self.menu)
        core.act(st, "fkey", ct=ct["name"], key=key, in_window=ok)
        if not ok:
            return None
        self.menu = ("bios" if key == "F2" else "bootmgr", time.time())
        self.seen(ct, "bios_view" if key == "F2" else "bootmgr_view")
        self.w(bios_screen(ct) if key == "F2" else bootmgr_screen(ct))
        return None

    def leave_menu(self, st, ct):
        kind, t0 = self.menu
        self.menu = None
        ct["power_t"] += time.time() - t0
        self.w("\n[continuing boot]\n")
        return "resync"

    def menu_key(self, st, ct, ch):
        kind, t0 = self.menu
        if kind != "bootmgr" or ch not in "123":
            return None
        choice = {"1": "pxe_pick", "2": "shell_direct", "3": "live"}[ch]
        if (ch == "1" and not ct["bf3_present"]) or (ch == "3" and not ct["usb"]):
            return None
        self.w(ch + "\n")
        self.menu = None
        if choice == "pxe_pick":
            choice = "pxe" if core.pxe_ok(ct) else "shell"
        ct["override"] = choice
        ct["out0"] = choice
        ct["power_t"] = time.time() - OUTCOME_AT + 0.3
        core.act(st, "boot_override", ct=ct["name"], pick=choice)
        return "resync"

    # ------------------------------------------------------------ commands
    def run_cmd(self, st, ct, cmd):
        core.act(st, "sol_input", ct=ct["name"], mode=self.mode, cmd=cmd)
        if self.mode == "shell":
            word = cmd.split()[0].lower() if cmd else ""
            if not word:
                self.w(PROMPTS["shell"])
            elif word == "exit":
                ct["legs"].append({"t": time.time() + 0.4, "out": retry_outcome(ct)})
                self.seen(ct, "shell_exit")
                self.mode = None
            elif word == "reset":
                core.power_on(ct)
                self.mode = None
                return "resync"
            elif word in ("help", "?"):
                self.w("Commands in this lab shell: exit (leave the shell and try to boot again), reset, map, help\n"
                       + PROMPTS["shell"])
            elif word == "map":
                self.w("Mapping table\n      FS0: Alias(s):HD0b:;BLK1:\n     BLK0: Alias(s):\n" + PROMPTS["shell"])
            else:
                self.w(f"'{cmd.split()[0]}' is not recognized as an internal or external command, operable "
                       "program, or script file.\n" + PROMPTS["shell"])
            return None
        if self.mode == "login":
            if cmd:
                self.w("This tray belongs to the provisioning team now. No local tech login.\n")
            self.w(PROMPTS["login"])
            return None
        if self.mode == "live":
            out, action = liveimage.run(st, ct, cmd)
            if out:
                self.w(out if out.endswith("\n") else out + "\n")
            if action == "poweroff":
                core.act(st, "graceful", ct=ct["name"], was_in_job=ct["in_job"], via="os")
                ct["in_job"] = False
                core.power_off(ct)
                self.mode = None
                return "resync"
            if action == "reboot":
                core.power_on(ct)
                self.mode = None
                return "resync"
            self.w(PROMPTS["live"])
        return None
