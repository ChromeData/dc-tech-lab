"""Lab stand-in for ipmitool. Same syntax as the real tool, talking to the simulated rack."""
import getpass
import sys
import time

import core

USAGE = """ipmitool version 1.8.19 (dclab simulator)

usage: ipmitool [options...] <command>

       -I intf        Interface to use (use lanplus for these BMCs)
       -H hostname    Remote host name for LAN interface
       -U username    Remote session username
       -P password    Remote session password
       -v             Verbose (sel -v list gives the full record)
       -h             This help

Commands:
	chassis    Get chassis status and set power state
	power      Shortcut to chassis power commands
	sdr        Print Sensor Data Repository entries and readings
	sel        Print System Event Log (SEL)
	mc         Management Controller status and global enables
	fru        Print built-in FRU and scan SDR for FRU locators
	lan        Configure LAN Channels
	sol        Configure and connect IPMIv2.0 Serial-over-LAN
"""

OPTS_WITH_ARG = set("IHUPpLCkyfAtbmoORNeSlTBc")
FLAGS = set("vVhEaga")


def parse(argv):
    opts, args, verbose = {}, [], 0
    i = 0
    while i < len(argv):
        a = argv[i]
        if a.startswith("-") and len(a) >= 2 and a != "-":
            flag = a[1]
            if flag in OPTS_WITH_ARG:
                if len(a) > 2:
                    opts[flag] = a[2:]
                else:
                    if i + 1 >= len(argv):
                        print(f"ipmitool: option requires an argument -- '{flag}'", file=sys.stderr)
                        return None, None, 0
                    opts[flag] = argv[i + 1]
                    i += 1
            elif flag == "v":
                verbose += a.count("v")
            elif flag in FLAGS:
                opts[flag] = True
            else:
                print(f"ipmitool: invalid option -- '{flag}'", file=sys.stderr)
                return None, None, 0
        else:
            args.append(a)
        i += 1
    return opts, args, verbose


def err(msg, code=1):
    print(msg, file=sys.stderr)
    return code


def main(argv):
    opts, args, verbose = parse(argv)
    if opts is None:
        return 1
    if opts.get("h") or not args or args[0] == "help":
        print(USAGE)
        return 0 if (opts.get("h") or args) else 1
    host, intf = opts.get("H"), opts.get("I", "open")
    if not host:
        return err("Could not open device at /dev/ipmi0 or /dev/ipmi/0 or /dev/ipmidev/0: No such file or directory\n"
                   "Error: Unable to establish local IPMI session (use -I lanplus -H <BMC_IP> for a remote BMC)")
    if intf not in ("lan", "lanplus"):
        return err(f"Invalid interface: {intf}")
    user = opts.get("U", "")
    pw = opts.get("P")
    if pw is None and "E" not in opts:
        try:
            pw = getpass.getpass("Password: ")
        except (EOFError, KeyboardInterrupt):
            return 1
    cmd = " ".join(args)
    with core.rack() as st:
        ct = core.ct_by_ip(st, host)
        core.act(st, "ipmitool", ip=host, ct=ct["name"] if ct else None, cmd=cmd, verbose=verbose, intf=intf)
        if ct is None or not core.reachable(ct):
            time.sleep(1.5)
            return err("Error: Unable to establish IPMI v2 / RMCP+ session")
        if intf == "lan":
            if args[0] == "sol":
                return err("Error: This command is only available over the lanplus interface")
            return err("Error: Unable to establish LAN session (this BMC needs -I lanplus)")
        if user != core.CREDS[0]:
            return err("> RAKP 2 message indicates an error : unauthorized name\n"
                       "Error: Unable to establish IPMI v2 / RMCP+ session")
        if pw != core.CREDS[1]:
            return err("> RAKP 2 HMAC is invalid\nError: Unable to establish IPMI v2 / RMCP+ session")
        if args[0] == "sol":
            rc = sol_cmd(st, ct, args[1:])
            if not isinstance(rc, tuple):
                return rc
            start = rc[1]
        else:
            handler = {"chassis": chassis, "power": power, "sdr": sdr, "sensor": sensor, "sel": sel,
                       "mc": mc, "fru": fru, "lan": lan}.get(args[0])
            if handler is None:
                return err(f"Invalid command: {args[0]}")
            return handler(st, ct, args[1:], verbose)
    # the console runs outside the state lock
    import sol
    return sol.Session(start).run()


# ------------------------------------------------------------------ power
def chassis(st, ct, args, verbose):
    if not args:
        print("Chassis Commands:  status, power, identify, policy, restart_cause, poh, bootdev, bootparam, selftest")
        return 0
    if args[0] == "power":
        return power(st, ct, args[1:], verbose)
    if args[0] == "status":
        on = ct["power"] == "on"
        print(f"System Power         : {'on' if on else 'off'}\nPower Overload       : false\n"
              "Power Interlock      : inactive\nMain Power Fault     : false\nPower Control Fault  : false\n"
              "Power Restore Policy : previous\nLast Power Event     : "
              + ("" if on else "command") + "\nChassis Intrusion    : "
              + ("active" if ct["lid"] == "open" else "inactive")
              + "\nFront-Panel Lockout  : inactive\nDrive Fault          : "
              + ("true" if ct.get("out0") == "die" else "false") + "\nCooling/Fan Fault    : "
              + ("true" if ct.get("fan_fail") and on else "false"))
        return 0
    return err(f"Invalid chassis command: {args[0]}")


def power(st, ct, args, verbose):
    if not args:
        print("chassis power Commands: status, on, off, cycle, reset, diag, soft")
        return 0
    op = args[0]
    on = ct["power"] == "on"
    if op == "status":
        print(f"Chassis Power is {'on' if on else 'off'}")
        return 0
    if op == "on":
        if not on:
            if ct["bmc_state"] == "needs_fix":
                core.violation(st, f"Powered on {ct['name']} before running fixBMC.sh on the new BMC", ct["name"])
            core.power_on(ct)
        print("Chassis Power Control: Up/On")
        return 0
    if op in ("off", "cycle", "reset"):
        if op != "off" and not on:
            return err(f"Set Chassis Power Control to {op.capitalize()} failed: Command not supported in present state")
        if on and ct["in_job"]:
            core.violation(st, f"Hard power {op} on {ct['name']} while it was in a running job: this breaks the "
                               "NVLink fabric and the job needs a manual restart. Use a graceful (soft/ACPI) "
                               "shutdown.", ct["name"])
            ct["in_job"] = False
        if op == "off":
            if on:
                core.power_off(ct)
            print("Chassis Power Control: Down/Off")
        else:
            core.power_on(ct)
            print(f"Chassis Power Control: {'Cycle' if op == 'cycle' else 'Reset'}")
        return 0
    if op == "soft":
        if on:
            core.act(st, "graceful", ct=ct["name"], was_in_job=ct["in_job"])
            ct["in_job"] = False
            core.power_off(ct)
        print("Chassis Power Control: Soft")
        return 0
    if op == "diag":
        print("Chassis Power Control: Diag")
        return 0
    return err(f"Invalid chassis power command: {op}")


# ------------------------------------------------------------------ sensors
def sdr(st, ct, args, verbose):
    sub = args[0] if args else "list"
    items = core.sensors(ct)
    if sub in ("list", "elist"):
        flt = args[1] if len(args) > 1 else "all"
        if flt not in ("all", "full", "compact", "event", "mcloc", "fru", "generic"):
            return err(f"Invalid SDR record type: {flt}")
        fmt = core.fmt_sdr_elist if sub == "elist" else core.fmt_sdr_list
        for s in items:
            print(fmt(s))
        return 0
    if sub == "type":
        if len(args) < 2:
            print("Sensor Types:\n\tTemperature  Voltage  Fan  Power Unit  Management Subsystem Health")
            return 0
        want = " ".join(args[1:]).lower()
        hits = [s for s in items if s["kind"].lower() == want]
        if not hits:
            return err(f"Invalid sensor type: {' '.join(args[1:])}")
        for s in hits:
            print(core.fmt_sdr_elist(s))
        return 0
    if sub == "info":
        print(f"SDR Version                         : 0x51\nRecord Count                        : {len(items)}\n"
              "Free Space                          : 32768 bytes")
        return 0
    return err(f"Invalid SDR command: {sub}")


def sensor(st, ct, args, verbose):
    if args and args[0] not in ("list",):
        return err("Use: sensor list")
    for s in core.sensors(ct):
        val = "na" if s["val"] is None else (f"{s['val']:.3f}" if isinstance(s["val"], float) else str(s["val"]))
        unit = {"Volts": "Volts", "RPM": "RPM", "C": "degrees C"}.get(s["unit"], "discrete")
        print(f"{s['name']:<16} | {val:<10} | {unit:<10} | {s['st']:<5} | na        | na        | na        | na        | na        | na")
    return 0


# ------------------------------------------------------------------ SEL
def sel(st, ct, args, verbose):
    sub = args[0] if args else "info"
    if sub == "info":
        last = core.stamp(ct["sel"][-1]["t"]).strftime("%m/%d/%Y %H:%M:%S") if ct["sel"] else "Not Available"
        print(f"SEL Information\nVersion          : 1.5 (v1.5, v2 compliant)\nEntries          : {len(ct['sel'])}\n"
              f"Free Space       : {65536 - 16 * len(ct['sel'])} bytes\nPercent Used     : 0%\n"
              f"Last Add Time    : {last}\nLast Del Time    : Not Available\nOverflow         : false")
        return 0
    if sub in ("list", "elist"):
        if not ct["sel"]:
            print("SEL has no entries")
            return 0
        for e in ct["sel"]:
            print(core.fmt_sel_verbose(e) if verbose else core.fmt_sel(e, extended=(sub == "elist")))
        return 0
    if sub == "clear":
        core.act(st, "sel_clear", ct=ct["name"])
        ct["sel"] = []
        print("Clearing SEL.  Please allow a few seconds to erase.")
        return 0
    return err(f"Invalid SEL command: {sub}")


# ------------------------------------------------------------------ mc / fru / lan
def mc(st, ct, args, verbose):
    sub = args[0] if args else ""
    if sub == "info":
        major, minor = ct["fw"]["bmc"].split(".")[:2]
        print(f"Device ID                 : 32\nDevice Revision           : 1\n"
              f"Firmware Revision         : {int(major)}.{minor}\nIPMI Version              : 2.0\n"
              "Manufacturer ID           : 674\nManufacturer Name         : DELL Inc\n"
              "Product ID                : 256 (0x0100)\nProduct Name              : PowerEdge XE9712 BMC\n"
              "Device Available          : yes\nProvides Device SDRs      : yes\n"
              "Additional Device Support :\n    Sensor Device\n    SDR Repository Device\n    SEL Device\n"
              "    FRU Inventory Device\n    Chassis Device\n"
              f"Aux Firmware Rev Info     : (full build: {ct['fw']['bmc']})")
        return 0
    if sub == "reset" and len(args) > 1 and args[1] in ("cold", "warm"):
        print(f"Sent {args[1]} reset command to MC")
        return 0
    return err("MC Commands:\n  reset <warm|cold>\n  info")


def fru(st, ct, args, verbose):
    print(f"FRU Device Description : Builtin FRU Device (ID 0)\n Chassis Type          : Rack Mount Chassis\n"
          f" Chassis Serial        : {ct['tag']}\n Board Mfg             : Dell Inc.\n"
          f" Board Product         : PowerEdge XE9712 Compute Tray\n Product Manufacturer  : Dell Inc.\n"
          f" Product Name          : PowerEdge XE9712\n Product Serial        : {ct['tag']}\n"
          f" Product Asset Tag     : {ct['rack']}-{ct['name']}")
    return 0


def lan(st, ct, args, verbose):
    if not args or args[0] != "print":
        return err("LAN Commands: print [channel]")
    print(f"Set in Progress         : Set Complete\nIP Address Source       : Static Address\n"
          f"IP Address              : {ct['bmc_ip']}\nSubnet Mask             : 255.255.255.0\n"
          f"MAC Address             : {ct['mac'].lower()}\nDefault Gateway IP      : 192.168.8.1\n"
          "Cipher Suite Priv Max   : aaaaaaaaaaaaaaa")
    return 0


# ------------------------------------------------------------------ SOL
def sol_cmd(st, ct, args):
    sub = args[0] if args else ""
    s = ct["sol"]
    if sub == "info":
        print(f"Set in progress                 : set-complete\nEnabled                         : true\n"
              f"Force Encryption                : true\nPrivilege Level                 : ADMINISTRATOR\n"
              f"Character Accumulate Level (ms) : 50\nVolatile Bit Rate (kbps)        : 115.2\n"
              f"Non-Volatile Bit Rate (kbps)    : 115.2\nPayload Channel                 : 1 (0x01)\n"
              f"Payload Port                    : 623\nSession active                  : {'yes' if s['active'] else 'no'}")
        return 0
    if sub == "deactivate":
        if not s["active"]:
            print("Info: SOL payload already de-activated")
            return 0
        s.update(active=False, stale=False, sticky=False, pid=0)
        core.act(st, "sol_deactivate", ct=ct["name"])
        return 0
    if sub == "activate":
        if s["active"]:
            core.act(st, "sol_busy", ct=ct["name"])
            return err("Info: SOL payload already active on another session")
        import os
        s.update(active=True, t=time.time(), pid=os.getpid(), stale=False, sticky=False)
        core.act(st, "sol_activate", ct=ct["name"])
        return ("SOL", ct["name"])
    return err("SOL Commands: info [<channel number>]\n              activate [<usesolkeepalive|nokeepalive>]\n"
               "              deactivate")
