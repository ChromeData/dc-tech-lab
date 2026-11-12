#!/usr/bin/env python3
"""Tiny stand-in for the Jira Cloud REST API (only the calls the lab makes). For testing the link offline."""
import json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer

ISSUES = {}
TR = [{"id": "11", "name": "To Do", "to": {"name": "To Do", "statusCategory": {"key": "new"}}},
      {"id": "21", "name": "In Progress", "to": {"name": "In Progress", "statusCategory": {"key": "indeterminate"}}},
      {"id": "31", "name": "Done", "to": {"name": "Done", "statusCategory": {"key": "done"}}}]

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def out(self, code, body=None):
        data = json.dumps(body).encode() if body is not None else b""
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n)) if n else {}
    def do_GET(self):
        p = self.path.split("?")[0]
        if not self.headers.get("Authorization", "").startswith("Basic "): return self.out(401, {"error": "auth"})
        if p == "/rest/api/3/myself": return self.out(200, {"displayName": "Lab Tester"})
        if p == "/rest/api/3/project/DCOPS": return self.out(200, {"key": "DCOPS", "issueTypes": [{"name": "Task", "subtask": False}]})
        if p == "/dump": return self.out(200, ISSUES)
        parts = p.split("/")
        if len(parts) >= 6 and parts[4] == "issue" and parts[5] in ISSUES:
            if p.endswith("/transitions"): return self.out(200, {"transitions": TR})
            return self.out(200, {"key": parts[5], "fields": {"status": {"name": ISSUES[parts[5]]["status"]}}})
        self.out(404, {"error": "not found"})
    def do_POST(self):
        p = self.path; b = self.body(); parts = p.split("/")
        if p == "/rest/api/3/issue":
            f = b["fields"]
            assert f["project"]["key"] == "DCOPS" and f["description"]["type"] == "doc" and f["issuetype"]["name"] == "Task"
            key = f"DCOPS-{len(ISSUES) + 1}"
            ISSUES[key] = {"summary": f["summary"], "labels": f["labels"], "status": "To Do", "comments": []}
            return self.out(201, {"id": str(10000 + len(ISSUES)), "key": key})
        if len(parts) >= 7 and parts[5] in ISSUES and parts[6] == "transitions":
            ISSUES[parts[5]]["status"] = next(t["name"] for t in TR if t["id"] == b["transition"]["id"]); return self.out(204)
        if len(parts) >= 7 and parts[5] in ISSUES and parts[6] == "comment":
            assert b["body"]["type"] == "doc"; ISSUES[parts[5]]["comments"].append(json.dumps(b["body"])); return self.out(201, {"id": "1"})
        self.out(404, {"error": "not found"})

HTTPServer(("127.0.0.1", int(sys.argv[1]) if len(sys.argv) > 1 else 8899), H).serve_forever()
