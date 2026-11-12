"""dclab: start a ticket, read it, get hints, grade it, drill the facts."""
import json
import os
import random
import sys
import time

import cards
import core
import ticketlib
import tickets_gb200  # noqa: F401  (registers tickets)
import tickets_ops  # noqa: F401

REG = ticketlib.REG
PROGRESS = os.path.join(core.STATE_DIR, "progress.json")
DRILL = os.path.join(core.STATE_DIR, "drill.json")
TTY = sys.stdout.isatty()


def c(code, s):
    return f"\033[{code}m{s}\033[0m" if TTY else s


B, G, R, Y, D = (lambda s: c("1", s)), (lambda s: c("32", s)), (lambda s: c("31", s)), (lambda s: c("33", s)), \
    (lambda s: c("2", s))


def jload(p, default):
    try:
        with open(p) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def jsave(p, obj):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        json.dump(obj, f, indent=1)


def tid_of(arg):
    a = arg.upper()
    if a in REG:
        return a
    if ("DCOPS-" + a) in REG:
        return "DCOPS-" + a
    return None


def wrap(text, indent, width=96):
    import textwrap
    return textwrap.fill(text, width=width, initial_indent=indent, subsequent_indent=" " * len(indent))


def current(st=None):
    st = st or core.load()
    t = (st or {}).get("ticket")
    return REG.get(t), st


def show_ticket(t, st):
    f = lambda s: ticketlib.fill(s, st, t)
    print(B(f"\n{t.tid}  {t.title}") + D(f"    [{t.track}]"))
    print(wrap(f(t.body), "  "))
    print(Y("\nTEACH") + D("  (the facts you need. Say each one out loud before you start.)"))
    for i, line in enumerate(t.teach, 1):
        print(wrap(f(line), f"  {i}. "))
    print(Y("\nDO"))
    for i, line in enumerate(t.do, 1):
        print(wrap(f(line), f"  {i}. "))
    print(D(f"\nWork folder: {core.workdir(st)}   (type dcgo to jump there)"))
    print(D("Stuck: dclab nudge | dclab walk | dclab show      Done: dclab grade\n"))


def cmd_list(_):
    prog = jload(PROGRESS, {})
    cur, _st = current()
    print(B("\nTickets") + D("   start one with: dclab start <number>\n"))
    last = None
    for tid in sorted(REG):
        t = REG[tid]
        if t.track != last:
            print(Y(f" {t.track}"))
            last = t.track
        mark = G("PASS") if tid in prog else "    "
        here = B(" <- current") if cur and cur.tid == tid else ""
        print(f"  {mark}  {tid[6:]}  {t.title}{here}")
    print(D(f"\n {len(prog)}/{len(REG)} passed. RHCSA and RHCE tracks run on the Rocky VMs: see rhcsa-rhce/README.md\n"))


def cmd_start(args):
    if not args or not tid_of(args[0]):
        print("Which ticket? Example: dclab start 104   (dclab list shows them all)")
        return 1
    tid = tid_of(args[0])
    t = REG[tid]
    wd = os.path.join(core.WORK, tid)
    if os.path.isdir(wd) and os.listdir(wd):
        os.rename(wd, f"{wd}.old-{time.strftime('%m%d-%H%M%S')}")
    os.makedirs(wd, exist_ok=True)
    with core.rack() as st:
        st.clear()
        st.update(core.new_rack())
        st["ticket"] = tid
        st["started"] = time.time()
        if t.setup:
            t.setup(st)
        snap = json.loads(json.dumps(st))
    show_ticket(t, snap)
    try:
        import jira
        jira.on_start(t)
    except Exception as e:  # the lab never depends on Jira
        print(f"  Jira: skipped ({e})")
    return 0


def cmd_ticket(_):
    t, st = current()
    if not t:
        print("No ticket started. Try: dclab list")
        return 1
    show_ticket(t, st)
    return 0


def cmd_grade(_):
    t, _st = current()
    if not t:
        print("No ticket started. Try: dclab list")
        return 1
    with core.rack() as st:
        snap = json.loads(json.dumps(st))
    # Grade on a snapshot, outside the lock: some checks run your scripts, and those call the lab tools.
    x = ticketlib.Ctx(snap)
    t.check(x)
    ok = sum(1 for _, good in x.results if good)
    print(B(f"\n{t.tid}  {t.title}"))
    for label, good in x.results:
        print(f"  {G('PASS') if good else R('FAIL')}  {label}")
    total = len(x.results)
    if ok == total:
        prog = jload(PROGRESS, {})
        prog[t.tid] = time.time()
        jsave(PROGRESS, prog)
        print(G(f"\n  {ok}/{total}  Ticket passed."))
        try:
            import jira
            jira.on_grade(t, x.results, True, x.read("resolution.txt"))
        except Exception as e:
            print(f"  Jira: skipped ({e})")
        print(wrap("Now SPEAK it: 60 seconds, out loud, no notes. Symptom, the evidence you collected, the fix, "
                   "how you confirmed it. `dclab speak` runs the timer.", "  "))
    else:
        print(Y(f"\n  {ok}/{total}  Not yet. Fix the FAIL lines and grade again. (dclab nudge for a hint; "
                f"dclab start {t.tid[6:]} resets the ticket.)"))
    print()
    return 0 if ok == total else 2


def cmd_hint(level):
    def run(_):
        t, st = current()
        if not t:
            print("No ticket started.")
            return 1
        f = lambda s: ticketlib.fill(s, st, t)
        if level == "nudge":
            print(Y("\nNudge: ") + f(t.nudge) + "\n")
        elif level == "walk":
            print(Y("\nWalk me (steps, no commands):"))
            for i, s in enumerate(t.walk, 1):
                print(wrap(f(s), f"  {i}. "))
            print()
        else:
            print(Y("\nShow me (full commands). Type them yourself; do not paste."))
            for s in t.show:
                print("  " + f(s))
            print()
        return 0
    return run


def cmd_rack(_):
    with core.rack(write=False) as st:
        print(B(f"\nRack {st['rack']}") + D(f"   fabric: {st['fabric']}   ticket: {st.get('ticket') or '-'}"))
        print(D("  tray  service tag  BMC IP          power  where    in job"))
        for name in sorted(st["cts"]):
            ct = st["cts"][name]
            if ct["rack"] == core.HOSP and name.startswith("H"):
                continue
            where = ct["location"] if ct["rack"] == core.RACK else f"{ct['location']}/hosp"
            print(f"  {name:<5} {ct['tag']:<12} {ct['bmc_ip']:<15} {ct['power']:<6} {where:<8} {'yes' if ct['in_job'] else 'no'}")
        sw = "  ".join(f"{k}:{v['state']}" for k, v in sorted(st["switches"].items()))
        print(D("  switches  ") + sw)
        print(D("  hospital rack: tech hospital     credentials for every BMC: admin / admin\n"))
    return 0


def cmd_matrix(_):
    p = core.PKG
    print(B("\nFirmware matrix (GB200)"))
    print(D("  Only package 1.3.6 and BMC 26.01.10001500 come from the class slides. The other builds are lab placeholders."))
    print(f"  {'Component':<10}{'Old 1.2.5':<18}{'Standard 1.3.6':<18}{core.SITE_NAME[:1].upper() + core.SITE_NAME[1:]}")
    for comp in core.FW_ORDER:
        print(f"  {comp:<10}{p['1.2.5'][comp]:<18}{p['1.3.6'][comp]:<18}{core.SITE[comp]}")
    print(f"  {'bf3':<10}{'1.2.0':<18}{core.BF3_OK:<18}{core.BF3_OK}   (PXE needs v1.3 or above)")
    print("  Rules: update BMC, then BIOS, then Bianca. CT powered off for each. 1.3.6 can not be downgraded.\n")
    return 0


def cmd_learn(args):
    if not args or args[0] not in cards.LEARN:
        print(B("\nTopics") + D("   dclab learn <topic>, then dclab drill <topic>\n"))
        for k, (title, facts) in cards.LEARN.items():
            print(f"  {k:<9} {title}  " + D(f"({len(facts)} facts)"))
        print()
        return 0
    title, facts = cards.LEARN[args[0]]
    print(B(f"\n{title}"))
    for i, fct in enumerate(facts, 1):
        print(wrap(fct, f"  {i}. "))
    print(D(f"\n  Say each line out loud once. Then test yourself: dclab drill {args[0]}\n"))
    return 0


def card_ok(answer, groups):
    a = answer.lower()
    return all(any(alt in a for alt in g.split("|")) for g in groups)


def cmd_drill(args):
    topic = next((a for a in args if a in cards.LEARN), None)
    n = next((int(a) for a in args if a.isdigit()), 10)
    pool = [cd for cd in cards.CARDS if topic in (None, cd[0])]
    box = jload(DRILL, {})
    random.shuffle(pool)
    pool.sort(key=lambda cd: box.get(cd[1], 0))
    pool = pool[:n]
    if not pool:
        print("No cards for that topic. dclab learn lists the topics.")
        return 1
    print(B(f"\nDrill: {len(pool)} cards") + D("   type your answer, Enter. q to stop.\n"))
    right = 0
    for i, (tp, q, ans, groups) in enumerate(pool, 1):
        print(Y(f"[{i}/{len(pool)}] ") + q)
        try:
            a = input("  > ")
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if a.strip().lower() == "q":
            break
        if card_ok(a, groups):
            right += 1
            box[q] = min(box.get(q, 0) + 1, 5)
            print(G("  Correct.") + D(f"  ({ans})\n"))
        else:
            box[q] = 0
            print(R("  Not yet. ") + f"Answer: {ans}")
            try:
                while not card_ok(input("  Type the answer once to lock it in > "), groups):
                    pass
            except (EOFError, KeyboardInterrupt):
                print()
                break
            print(D(f"  Good. It comes back next round. (dclab learn {tp})\n"))
        jsave(DRILL, box)
    known = sum(1 for cd in cards.CARDS if box.get(cd[1], 0) >= 3)
    print(B(f"  {right}/{len(pool)} first try.") + D(f"   {known}/{len(cards.CARDS)} cards solid (right 3 times in a row).\n"))
    return 0


def cmd_speak(_):
    t, _st = current()
    print(B("\nSPEAK, out loud, no notes.") + (f"  Ticket {t.tid}: {t.title}" if t else ""))
    print("  1. Symptom   2. Evidence you collected   3. Root cause   4. Fix   5. How you confirmed it")
    try:
        input(D("  Press Enter to start 60 seconds... "))
        for left in range(60, 0, -1):
            print(f"\r  {left:>2} s ", end="", flush=True)
            time.sleep(1)
        print("\r  Time. Say it once more, faster.\n")
    except (EOFError, KeyboardInterrupt):
        print()
    return 0


def cmd_status(_):
    prog = jload(PROGRESS, {})
    t, st = current()
    print(B("\nDC tech lab") + D(f"   {len(prog)}/{len(REG)} tickets passed"))
    if t:
        print(f"  Current ticket: {t.tid}  {t.title}")
    print(D("  dclab list | start <n> | ticket | grade | nudge | walk | show | rack | matrix | learn | drill | speak | jira | web"))
    print(D("  Tools: ipmitool (simulated BMCs), curl + jq (Redfish/HMC), ezbmc, tech (your hands). tech -h lists actions.\n"))
    return 0


def cmd_web(_):
    import webd
    print(webd.url())
    return 0


def cmd_workdir(_):
    print(core.workdir())
    return 0


def main(argv):
    cmds = {"list": cmd_list, "start": cmd_start, "ticket": cmd_ticket, "grade": cmd_grade,
            "nudge": cmd_hint("nudge"), "walk": cmd_hint("walk"), "show": cmd_hint("show"), "rack": cmd_rack,
            "matrix": cmd_matrix, "learn": cmd_learn, "drill": cmd_drill, "speak": cmd_speak,
            "status": cmd_status, "workdir": cmd_workdir, "web": cmd_web,
            "jira": lambda a: __import__("jira").main(a), "reset": lambda a: cmd_start([(current()[0] or REG["DCOPS-100"]).tid])}
    if not argv:
        return cmd_status([])
    fn = cmds.get(argv[0])
    if not fn:
        print(f"Unknown command: {argv[0]}")
        return cmd_status([])
    return fn(argv[1:])
