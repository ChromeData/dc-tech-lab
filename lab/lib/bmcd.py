"""Fake BMC web service: HTTPS Redfish on 443 for every tray's BMC IP (run as root by up.sh)."""
import base64
import json
import os
import ssl
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core  # noqa: E402

CERT = os.environ.get("DCLAB_CERT", "/var/lib/dclab/bmc.crt")
KEY = os.environ.get("DCLAB_KEY", "/var/lib/dclab/bmc.key")
GOOD = "Basic " + base64.b64encode(b"admin:admin").decode()


def err(code, msg, rid="Base.1.15.0.GeneralError"):
    return code, {"error": {"code": rid, "message": msg,
                            "@Message.ExtendedInfo": [{"MessageId": rid, "Message": msg}]}}


def route(ct, path):
    path = path.split("?")[0].rstrip("/") or "/"
    sysid = "/redfish/v1/Systems/System_0"
    hgx = "/redfish/v1/Systems/HGX_Baseboard_0"
    if path in ("/redfish", "/redfish/v1"):
        return 200, {"@odata.id": "/redfish/v1", "Name": "Root Service", "RedfishVersion": "1.17.0",
                     "Systems": {"@odata.id": "/redfish/v1/Systems"},
                     "Managers": {"@odata.id": "/redfish/v1/Managers"},
                     "UpdateService": {"@odata.id": "/redfish/v1/UpdateService"}}
    if path == "/redfish/v1/Systems":
        return 200, {"Members": [{"@odata.id": sysid}, {"@odata.id": hgx}], "Members@odata.count": 2}
    if path == sysid:
        return 200, {"@odata.id": sysid, "Id": "System_0", "Model": "PowerEdge XE9712", "SerialNumber": ct["tag"],
                     "PowerState": "On" if ct["power"] == "on" else "Off",
                     "Status": {"State": "Enabled", "Health": "Critical" if core.blocked(ct) else "OK"}}
    if path.startswith(hgx):
        if ct["hmc_fault"]:
            return err(503, "HMC is not responding. Check the HMC card and slimline cables.",
                       "Base.1.15.0.ServiceTemporarilyUnavailable")
        if path == hgx:
            return 200, {"@odata.id": hgx, "Id": "HGX_Baseboard_0", "Name": "HGX Baseboard (HMC)",
                         "LogServices": {"@odata.id": hgx + "/LogServices"}}
        if path == hgx + "/LogServices":
            return 200, {"Members": [{"@odata.id": hgx + "/LogServices/EventLog"}]}
        if path == hgx + "/LogServices/EventLog":
            return 200, {"@odata.id": hgx + "/LogServices/EventLog", "Entries": {"@odata.id": core.HMC_BASE}}
        if path == core.HMC_BASE:
            return 200, core.hmc_entries(ct)
        if path.startswith(core.HMC_BASE + "/"):
            eid = path.rsplit("/", 1)[1]
            for m in core.hmc_entries(ct)["Members"]:
                if m["Id"] == eid:
                    return 200, m
    if path == "/redfish/v1/Managers":
        return 200, {"Members": [{"@odata.id": "/redfish/v1/Managers/BMC_0"}]}
    if path == "/redfish/v1/Managers/BMC_0":
        return 200, {"Id": "BMC_0", "FirmwareVersion": ct["fw"]["bmc"], "Model": "XE9712 BMC"}
    if path == "/redfish/v1/UpdateService":
        return 200, {"FirmwareInventory": {"@odata.id": "/redfish/v1/UpdateService/FirmwareInventory"}}
    inv = core.fw_inventory(ct)
    base = "/redfish/v1/UpdateService/FirmwareInventory"
    if path == base:
        return 200, {"@odata.id": base, "Members": [{"@odata.id": f"{base}/{k}"} for k in inv],
                     "Members@odata.count": len(inv), "Name": "Firmware Inventory Collection"}
    if path.startswith(base + "/"):
        k = path.rsplit("/", 1)[1]
        if k in inv:
            name, ver = inv[k]
            absent = k == "BF3_Firmware" and not ct["bf3_present"]
            return 200, {"@odata.id": path, "Id": k, "Name": name, "Version": ver, "Updateable": True,
                         "Status": {"State": "Absent" if absent else "Enabled", "Health": "OK"}}
    return err(404, f"The resource at the URI {path} was not found.", "Base.1.15.0.ResourceMissingAtURI")


class H(BaseHTTPRequestHandler):
    server_version = "dclab-bmc"

    def log_message(self, *a):
        pass

    def send(self, code, body):
        data = (json.dumps(body, indent=None) + "\n").encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        if code == 401:
            self.send_header("WWW-Authenticate", 'Basic realm="dclab-bmc"')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        ip = self.connection.getsockname()[0]
        with core.rack(write=False) as st:
            ct = core.ct_by_ip(st, ip)
            ok = self.headers.get("Authorization") == GOOD
            if ct is not None and core.reachable(ct) and ok:
                code, body = route(ct, self.path)
            elif ct is None or not core.reachable(ct):
                code, body = err(404, f"No BMC at {ip}")
            else:
                code, body = err(401, "Unauthorized", "Base.1.15.0.InsufficientPrivilege")
        try:
            with open(core.REDFISH_LOG, "a") as f:
                f.write(json.dumps({"t": time.time(), "ip": ip, "ct": ct["name"] if ct else None,
                                    "path": self.path, "code": code}) + "\n")
            os.chmod(core.REDFISH_LOG, 0o666)
        except OSError:
            pass
        self.send(code, body)

    do_POST = do_PATCH = lambda self: self.send(*err(405, "This lab BMC is read-only. Use ipmitool or tech."))


def main():
    httpd = ThreadingHTTPServer(("0.0.0.0", 443), H)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(CERT, KEY)
    httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
    print("dclab bmcd listening on :443", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
