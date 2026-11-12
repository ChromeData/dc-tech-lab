"""Lab web server: the 3D app (static files), live rack state (JSON), and terminals over WebSocket.

Listens on 127.0.0.1 only. The terminal socket needs the token from state/web.token and a
same-origin page, so another web site cannot open a shell through your browser.
"""
import base64
import fcntl
import hashlib
import json
import mimetypes
import os
import pty
import secrets
import select
import signal
import struct
import sys
import termios
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core  # noqa: E402

PORT = int(os.environ.get("DCLAB_WEB_PORT", "8770"))
WEB = os.path.join(core.LAB, "web")
TOKEN_FILE = os.path.join(core.STATE_DIR, "web.token")
PID_FILE = os.path.join(core.STATE_DIR, "web.pid")
GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
mimetypes.add_type("model/gltf-binary", ".glb")
mimetypes.add_type("text/javascript", ".js")


def token():
    os.makedirs(core.STATE_DIR, exist_ok=True)
    if not os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "w") as f:
            f.write(secrets.token_urlsafe(18))
        os.chmod(TOKEN_FILE, 0o600)
    with open(TOKEN_FILE) as f:
        return f.read().strip()


def url():
    return f"http://localhost:{PORT}/?t={token()}"


def public_state():
    import ticketlib
    import tickets_gb200  # noqa: F401
    import tickets_ops  # noqa: F401
    with core.rack(write=False) as st:
        t = ticketlib.REG.get(st.get("ticket") or "")
        out = {"rack": st["rack"], "fabric": st["fabric"], "now": time.time(),
               "ticket": {"id": t.tid, "title": t.title, "ct": t.ct} if t else None, "cts": {}, "switches": {}}
        for name, ct in st["cts"].items():
            on = ct["power"] == "on"
            out["cts"][name] = {
                "tag": ct["tag"], "ip": ct["bmc_ip"], "power": ct["power"], "location": ct["location"],
                "rack": "hospital" if ct["rack"] == core.HOSP else "production", "lid": ct["lid"],
                "in_job": ct["in_job"], "usb": ct["usb"], "sol": ct["sol"]["active"],
                "amber": bool(on and ct.get("out0") == "die" and core.blocked(ct) == "leak"),
                "bmc": ct["bmc_state"]}
        for name, sw in st["switches"].items():
            out["switches"][name] = {"state": sw["state"], "slot": sw.get("slot")}
        acts = [a for a in st["actions"] if a["k"] not in ("ipmitool", "live_cmd", "sol_input", "look", "tag_look")]
        out["last"] = acts[-1] if acts else None
        ip = [a for a in st["actions"] if a["k"] == "ipmitool"]
        out["last_ipmi"] = ip[-1] if ip else None
        out["violations"] = [a["msg"] for a in st["actions"] if a["k"] == "violation"]
    try:
        with open(os.path.join(core.STATE_DIR, "progress.json")) as f:
            out["passed"] = sorted(json.load(f))
    except (OSError, ValueError):
        out["passed"] = []
    out["total"] = len(ticketlib.REG)
    return out


def tickets_list():
    import jira
    import ticketlib
    import tickets_gb200  # noqa: F401
    import tickets_ops  # noqa: F401
    st = core.load() or {}
    try:
        with open(os.path.join(core.STATE_DIR, "progress.json")) as f:
            done = set(json.load(f))
    except (OSError, ValueError):
        done = set()
    m = jira._load(jira.MAP, {})
    c = jira.cfg()
    out = []
    for tid in sorted(ticketlib.REG):
        t = ticketlib.REG[tid]
        status = "done" if tid in done else ("inprogress" if tid == st.get("ticket") else "todo")
        out.append({"id": tid, "title": t.title, "track": t.track, "status": status, "jira": m.get(tid)})
    return {"tickets": out, "jira": {"linked": bool(c), "site": c["site"] if c else None, "project": c["project"] if c else None}}


def ticket_detail(tid):
    import ticketlib
    import tickets_gb200  # noqa: F401
    import tickets_ops  # noqa: F401
    t = ticketlib.REG.get(tid)
    if not t:
        return None
    st = core.new_rack()
    ct = st["cts"].get(t.ct) if t.ct else None

    def f(s):
        s = s.replace("{wd}", "~/dclab/work/" + tid)
        if ct:
            s = s.replace("{ip}", ct["bmc_ip"]).replace("{tag}", ct["tag"]).replace("{ct}", ct["name"])
        return s
    return {"id": tid, "title": t.title, "track": t.track, "body": f(t.body), "teach": [f(x) for x in t.teach], "do": [f(x) for x in t.do]}


# ------------------------------------------------------------------ WebSocket
def ws_send(sock, data, opcode=2):
    n = len(data)
    head = bytes([0x80 | opcode])
    if n < 126:
        head += bytes([n])
    elif n < 65536:
        head += bytes([126]) + struct.pack(">H", n)
    else:
        head += bytes([127]) + struct.pack(">Q", n)
    sock.sendall(head + data)


def recv_exact(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError
        buf += chunk
    return buf


def ws_recv(sock):
    b1, b2 = recv_exact(sock, 2)
    opcode = b1 & 0x0F
    n = b2 & 0x7F
    if n == 126:
        n = struct.unpack(">H", recv_exact(sock, 2))[0]
    elif n == 127:
        n = struct.unpack(">Q", recv_exact(sock, 8))[0]
    mask = recv_exact(sock, 4) if b2 & 0x80 else None
    data = recv_exact(sock, n) if n else b""
    if mask:
        data = bytes(c ^ mask[i % 4] for i, c in enumerate(data))
    return opcode, data


def terminal(sock):
    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(os.path.expanduser("~"))
        env = dict(os.environ, TERM="xterm-256color", DCLAB_HOME=core.LAB, DCLAB_WEBTERM="1")
        os.execvpe("bash", ["bash", "--rcfile", os.path.join(core.LAB, "dclabrc"), "-i"], env)
    try:
        while True:
            r, _, _ = select.select([fd, sock], [], [], 30)
            if fd in r:
                try:
                    data = os.read(fd, 65536)
                except OSError:
                    break
                if not data:
                    break
                ws_send(sock, data)
            if sock in r:
                op, data = ws_recv(sock)
                if op == 8:
                    break
                if op == 9:
                    ws_send(sock, data, 10)
                elif op == 1:
                    try:
                        msg = json.loads(data.decode())
                    except ValueError:
                        continue
                    if "resize" in msg:
                        cols, rows = msg["resize"]
                        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", int(rows), int(cols), 0, 0))
                    elif "input" in msg:
                        os.write(fd, msg["input"].encode())
                elif op == 2:
                    os.write(fd, data)
    except (ConnectionError, OSError):
        pass
    finally:
        try:
            os.kill(pid, signal.SIGHUP)
            os.close(fd)
            os.waitpid(pid, 0)
        except (OSError, ChildProcessError):
            pass


class H(BaseHTTPRequestHandler):
    server_version = "dclab-web"
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def send_bytes(self, code, body, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/ws/term":
            return self.ws(q)
        if u.path == "/api/state":
            try:
                return self.send_bytes(200, json.dumps(public_state()).encode())
            except Exception as e:  # keep the page alive if the state file is mid-write
                return self.send_bytes(200, json.dumps({"error": str(e)}).encode())
        if u.path == "/api/tickets":
            return self.send_bytes(200, json.dumps(tickets_list()).encode())
        if u.path == "/api/ticket":
            d = ticket_detail(q.get("id", [""])[0])
            return self.send_bytes(200 if d else 404, json.dumps(d or {"error": "no such ticket"}).encode())
        rel = "index.html" if u.path in ("/", "") else u.path.lstrip("/")
        full = os.path.realpath(os.path.join(WEB, rel))
        if not full.startswith(os.path.realpath(WEB) + os.sep) or not os.path.isfile(full):
            return self.send_bytes(404, b"not found", "text/plain")
        with open(full, "rb") as f:
            body = f.read()
        self.send_bytes(200, body, mimetypes.guess_type(full)[0] or "application/octet-stream")

    def ws(self, q):
        origin = self.headers.get("Origin", "")
        ok_origin = origin in (f"http://localhost:{PORT}", f"http://127.0.0.1:{PORT}")
        if not ok_origin or q.get("t", [""])[0] != token() or "websocket" not in self.headers.get("Upgrade", "").lower():
            return self.send_bytes(403, b"forbidden", "text/plain")
        key = self.headers["Sec-WebSocket-Key"]
        accept = base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()
        self.send_response(101)
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", accept)
        self.end_headers()
        self.close_connection = True
        terminal(self.connection)


def serve():
    token()
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    httpd.daemon_threads = True
    print(f"dclab web on {url()}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    serve()
