"""Optional link to a real Jira Cloud site. The lab works without it.

    dclab jira setup     ask for the site, your email and an API token; test them; save them (file mode 600)
    dclab jira push      create one Jira issue per lab ticket (safe to run again: it skips ones that exist)
    dclab jira status    show each lab ticket's Jira key and status
    dclab jira off       forget the saved site and token

Once set up: `dclab start` moves the issue to In Progress, and a passing `dclab grade` posts the
grader checklist and your resolution.txt as a comment and moves the issue to Done.
"""
import base64
import getpass
import json
import os
import time
import urllib.error
import urllib.request

import core

CFG = os.path.join(core.STATE_DIR, "jira.json")
MAP = os.path.join(core.STATE_DIR, "jira_map.json")


def _load(p, default):
    try:
        with open(p) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def cfg():
    c = _load(CFG, None)
    return c if c and c.get("site") and c.get("token") else None


def api(c, method, path, body=None, timeout=20):
    req = urllib.request.Request(c["site"].rstrip("/") + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None)
    req.add_header("Authorization", "Basic " + base64.b64encode(f"{c['email']}:{c['token']}".encode()).decode())
    req.add_header("Accept", "application/json")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, {"error": raw.decode("utf-8", "replace")[:200]}
    except (urllib.error.URLError, OSError) as e:
        return 0, {"error": str(e)}


# ---- Atlassian Document Format helpers
def _p(text):
    return {"type": "paragraph", "content": [{"type": "text", "text": text}]} if text else {"type": "paragraph"}


def _h(text):
    return {"type": "heading", "attrs": {"level": 3}, "content": [{"type": "text", "text": text}]}


def _ol(items):
    return {"type": "orderedList", "content": [{"type": "listItem", "content": [_p(i)]} for i in items]}


def doc(*blocks):
    return {"type": "doc", "version": 1, "content": [b for b in blocks if b]}


def describe(t, st):
    import ticketlib
    f = lambda s: ticketlib.fill(s, st, t).replace(core.workdir(st), "~/dclab/work/" + t.tid)
    return doc(_p(f(t.body)), _h("TEACH"), _ol([f(x) for x in t.teach]), _h("DO"), _ol([f(x) for x in t.do]),
               _p("Lab ticket " + t.tid + ". Work it in the DC tech lab, then run: dclab grade"))


def issue_type(c):
    code, proj = api(c, "GET", f"/rest/api/3/project/{c['project']}")
    if code != 200:
        return None, f"Project {c['project']} not found on {c['site']} (HTTP {code}). Create a Kanban project with that key first."
    names = [i["name"] for i in proj.get("issueTypes", []) if not i.get("subtask")]
    for want in ("Task", "Story", "Bug"):
        if want in names:
            return want, None
    return (names[0], None) if names else (None, "The project has no usable issue type.")


def transition(c, key, category):
    """Move an issue to the first status in the given category: 'indeterminate' (in progress) or 'done'."""
    code, data = api(c, "GET", f"/rest/api/3/issue/{key}/transitions")
    if code != 200:
        return False
    words = {"indeterminate": ("progress", "doing"), "done": ("done", "closed", "resolved")}[category]
    pick = None
    for tr in data.get("transitions", []):
        to = tr.get("to", {})
        if to.get("statusCategory", {}).get("key") == category or any(w in tr.get("name", "").lower() for w in words):
            pick = tr["id"]
            break
    if not pick:
        return False
    code, _ = api(c, "POST", f"/rest/api/3/issue/{key}/transitions", {"transition": {"id": pick}})
    return code in (200, 204)


def comment(c, key, *blocks):
    code, _ = api(c, "POST", f"/rest/api/3/issue/{key}/comment", {"body": doc(*blocks)})
    return code in (200, 201)


# ---- hooks used by dclab
def on_start(t):
    c = cfg()
    key = _load(MAP, {}).get(t.tid) if c else None
    if not key:
        return
    ok = transition(c, key, "indeterminate")
    comment(c, key, _p(f"Work started in the lab ({time.strftime('%Y-%m-%d %H:%M')})."))
    print(f"  Jira: {key} -> In Progress" if ok else f"  Jira: could not move {key} (check the workflow)")


def on_grade(t, results, passed, resolution):
    c = cfg()
    key = _load(MAP, {}).get(t.tid) if c else None
    if not key or not passed:
        return
    comment(c, key, _h("Resolution"), _p(resolution.strip() or "(no resolution.txt)"), _h("Lab checks"),
            _ol([("PASS  " if ok else "FAIL  ") + label for label, ok in results]))
    ok = transition(c, key, "done")
    print(f"  Jira: {key} -> Done, resolution posted" if ok else f"  Jira: comment posted on {key}, but could not move it to Done")


# ---- commands
def cmd_setup(_):
    print("Link the lab to your Jira Cloud site. You need a site (free plan is fine), a project, and an API token\n"
          "from https://id.atlassian.com/manage-profile/security/api-tokens . The token is saved only on this machine.")
    site = input("  Site URL (https://yourname.atlassian.net): ").strip().rstrip("/")
    email = input("  Atlassian account email: ").strip()
    token = getpass.getpass("  API token (hidden): ").strip()
    project = (input("  Project key [DCOPS]: ").strip() or "DCOPS").upper()
    c = {"site": site, "email": email, "token": token, "project": project}
    code, me = api(c, "GET", "/rest/api/3/myself")
    if code != 200:
        print(f"  Could not sign in (HTTP {code}). Nothing saved. {me.get('error', '')}")
        return 1
    itype, err = issue_type(c)
    os.makedirs(core.STATE_DIR, exist_ok=True)
    with open(CFG, "w") as f:
        json.dump(c, f)
    os.chmod(CFG, 0o600)
    print(f"  Signed in as {me.get('displayName', email)}. Saved.")
    print(f"  {err}" if err else f"  Project {project} found (issue type {itype}). Next: dclab jira push")
    return 0


def cmd_push(_):
    import ticketlib
    c = cfg()
    if not c:
        print("Not linked yet. Run: dclab jira setup")
        return 1
    itype, err = issue_type(c)
    if err:
        print(err)
        return 1
    m = _load(MAP, {})
    st = core.new_rack()
    made = 0
    for tid in sorted(ticketlib.REG):
        if tid in m:
            continue
        t = ticketlib.REG[tid]
        st["ticket"] = tid
        fields = {"project": {"key": c["project"]}, "summary": f"[{tid[6:]}] {t.title}", "issuetype": {"name": itype},
                  "description": describe(t, st), "labels": ["dclab", t.track.lower()]}
        code, data = api(c, "POST", "/rest/api/3/issue", {"fields": fields})
        if code not in (200, 201):
            print(f"  {tid}: failed (HTTP {code}) {json.dumps(data)[:160]}")
            continue
        m[tid] = data["key"]
        made += 1
        print(f"  {tid} -> {data['key']}")
        with open(MAP, "w") as f:
            json.dump(m, f, indent=1)
    print(f"{made} issue(s) created, {len(m)} linked in total. Board: {c['site']}/jira/software/projects/{c['project']}/boards")
    return 0


def cmd_status(_):
    import ticketlib
    c = cfg()
    m = _load(MAP, {})
    if not c:
        print("Not linked. Run: dclab jira setup")
        return 1
    print(f"Jira site {c['site']}  project {c['project']}  ({len(m)} linked)")
    for tid in sorted(m):
        code, data = api(c, "GET", f"/rest/api/3/issue/{m[tid]}?fields=status")
        status = data.get("fields", {}).get("status", {}).get("name", f"HTTP {code}")
        print(f"  {tid}  {m[tid]:<10} {status:<14} {ticketlib.REG[tid].title if tid in ticketlib.REG else ''}")
    return 0


def cmd_off(_):
    for p in (CFG,):
        if os.path.exists(p):
            os.remove(p)
    print("Jira link removed from this machine (issues on the site are untouched).")
    return 0


def main(args):
    cmds = {"setup": cmd_setup, "push": cmd_push, "status": cmd_status, "off": cmd_off}
    if not args or args[0] not in cmds:
        print(__doc__)
        return 0
    return cmds[args[0]](args[1:])
