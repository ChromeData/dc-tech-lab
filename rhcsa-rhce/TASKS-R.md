# RHCSA track - Data Center Operations (node1)

Scenario: node1 is a GPU-server log collector in a data hall. You are the on-shift Linux tech.
Work on **node1** as root. Do the tasks in order (R02/R03/R07/R09 build on R01).
Everything must **survive a reboot**. `man` is allowed.

Grade: `bash /root/dclab-rh/grade-r.sh -v` (one task: `-t 5`). Grade, **reboot, grade again**.
Stuck? Open `HINTS.md` - nudge, then walk me, then show me. Try first.

Disks: `/dev/sdb` and `/dev/sdc` are blank 10 GB scratch disks. Do not touch `/dev/sda`.

---

## R01 - Log store on LVM (filesystem types, persistent mounts)

**TEACH**
- LVM stacks three layers: PV (`pvcreate`) -> VG (`vgcreate`, grow with `vgextend`) -> LV (`lvcreate -n NAME -L SIZE VG`). The device appears as `/dev/VG/LV`.
- Format with `mkfs.xfs` or `mkfs.ext4`. Mount **by UUID**: `blkid` prints it, and an `/etc/fstab` line is `UUID=... /mountpoint fstype defaults 0 0`. `mount -a` tests fstab without rebooting.
- `lvextend -r -L 7G /dev/VG/LV` grows the LV **and** its filesystem (`-r`) in one step, online.

**DO**
1. Make a volume group `dcvg` from `/dev/sdb`, then add `/dev/sdc` to it.
2. Create LV `ctlogs` (4 GB) formatted **XFS**, mounted at `/srv/ctlogs`.
3. Create LV `scratch` (2 GB) formatted **ext4**, mounted at `/var/dcscratch`.
4. Both mounts persistent, by UUID.
5. Grow `ctlogs` to 7 GB total while it is mounted (the filesystem must grow too).

## R02 - Navigate the rack tree, find/grep/copy, links (navigation + file manipulation)

**TEACH**
- Brace expansion builds many paths in one command: `mkdir -p /x/rack{01..03}/{a,b}`.
- `find DIR -name PATTERN -size +10k` lists files by name and size; redirect with `>`.
- `grep -rh TEXT DIR --include=NAME` searches recursively; `-h` hides filenames so you get bare lines.
- `cp -a` copies recursively **and** preserves timestamps/ownership. `ln -s TARGET LINK` = symlink, `ln TARGET LINK` = hard link (same inode, same filesystem only).

**DO** (the data is in `/opt/dcdata/racks/rackNN/nodeNN/{bmc.log,gpu.log,dmesg.txt}`)
1. Create `/srv/ctlogs/rack-reports/rack01..rack04`, each with subdirectories `bmc` and `gpu`, using one command.
2. Write the full path of every `gpu.log` larger than 10 KiB, one per line, to `/root/big-gpu-logs.txt`.
3. Write every line containing `fallen off the bus` from all `gpu.log` files (lines only, no filenames) to `/root/gpu-lost.txt`.
4. Copy the whole `rack04` tree, preserving timestamps, to `/srv/ctlogs/rack-reports/rack04/src`.
5. Make `/srv/ctlogs/latest` a symlink to `/srv/ctlogs/rack-reports/rack04`.
6. Make `/opt/dcdata/rack01-node01-bmc.log` a **hard link** to `/opt/dcdata/racks/rack01/node01/bmc.log`.

## R03 - Users, groups, setgid directory, ACL, sudo (permissions)

**TEACH**
- `groupadd -g GID`, `useradd -u UID -G GROUP -s SHELL`. `-G` = supplementary groups (`-g` would be the primary). `nologin` shell = account cannot log in.
- Directory mode `2770`: the leading `2` is **setgid** - new files inherit the directory's group. `chgrp`, `chmod`.
- ACLs add per-user rules: `setfacl -m u:USER:rx DIR`; with `-d` it sets the **default** ACL that new files inherit. `getfacl DIR` shows it.
- `chage -M DAYS -W DAYS USER` sets password max age / warning. Sudo rules go in `/etc/sudoers.d/NAME` (mode 0440); `visudo -c` checks syntax.

**DO**
1. Group `dcops` with GID 3000.
2. Users `tech1` (UID 3101) and `tech2` (UID 3102): `dcops` as a **supplementary** group.
3. User `noc1` (UID 3201), shell `/bin/bash`, **not** in `dcops`.
4. User `svc-collector` (UID 3001) that cannot log in.
5. Directory `/srv/ctlogs/rma`: owner root, group `dcops`, mode `2770`, new files inherit the group.
6. `noc1` gets read+traverse only (r-x) on that directory via an ACL, and new files inside inherit that (default ACL).
7. `tech1`: password max age 90 days, warning 7 days.
8. Members of `dcops` may run `/usr/bin/ipmitool` as root via sudo without a password - and nothing else.

## R04 - Packages (install and manage software)

**TEACH**
- `dnf install PKG...`, `dnf provides '*/bin/NAME'` finds which package ships a file you do not have yet.
- `rpm -qf /path/to/file` tells which installed package owns a file; add `--qf '%{NAME}\n'` to print just the package name (no version).

**DO**
1. Install `ipmitool`. (`jq` and `lshw` are already present - they must stay.)
2. Find which package provides the command `sensors`; install it and write just its package name to `/root/sensors-pkg.txt`.
3. Write the bare name of the package that owns `/etc/ssh/sshd_config` to `/root/sshd-owner.txt`.

## R05 - Runaway process (process management)

**TEACH**
- `ps -eo pid,ni,pcpu,comm --sort=-pcpu | head` ranks processes by CPU; `top` does it live. `ni` is the nice value.
- `systemctl status PID` shows which unit a process belongs to. A unit with `Restart=always` **respawns** a killed process - stopping the unit is the fix: `systemctl disable --now UNIT`.
- `renice -n 10 -p PID` changes a running process only. To make it permanent, set `Nice=10` in a unit drop-in (`systemctl edit UNIT`) and restart the unit.

**DO**
1. Find the process burning CPU (a leftover from the last shift). Write its **unit name** to `/root/runaway-unit.txt`.
2. Get rid of it so it stays gone, including after reboot.
3. `gpu-soak.service` is legitimate: keep it running and enabled, but give it nice value 10, both now and permanently.

## R06 - Broken service (basic troubleshooting)

**TEACH**
- `systemctl status UNIT` and `journalctl -u UNIT -e` show why a unit failed. Status codes in the log: `217/USER` = the `User=` does not exist, `203/EXEC` = ExecStart cannot be executed (wrong path, or file not executable).
- After editing a unit file run `systemctl daemon-reload`. `systemctl enable --now UNIT` = start now **and** at boot.

**DO**
- `ctlog-sync.service` (in `/etc/systemd/system`) is broken. Do not rewrite the script `/usr/local/sbin/ctlog-sync.sh`. Find every fault using the logs, fix them, and make the service enabled and successful. It must write `/var/lib/ctlog-sync/last-sync`.

## R07 - Nightly archive (bash + systemd timer + tar)

**TEACH**
- `tar -czf OUT.tar.gz -C /base dirname` archives `dirname` with a relative path (no leading `/`). `$(date +%F)` expands to `2026-11-12`.
- A timer needs two units with the same base name: `X.service` (`Type=oneshot`, `ExecStart=`) and `X.timer` (`[Timer] OnCalendar=*-*-* 02:15:00`, `Persistent=true`, `[Install] WantedBy=timers.target`). Enable the **timer**: `systemctl enable --now X.timer`. `systemctl list-timers` shows it.

**DO**
1. Script `/usr/local/bin/ctlog-archive.sh` (executable, with shebang): creates `/var/backups/ctlogs` if needed and writes `/var/backups/ctlogs/ctlogs-YYYY-MM-DD.tar.gz` containing `/srv/ctlogs/rack-reports` stored as `rack-reports/...`.
2. `ctlog-archive.service` runs it; `ctlog-archive.timer` fires daily at 02:15, persistent, enabled and active.
3. Run the service once by hand and check the archive with `tar tzf`.

## R08 - sdr-triage.sh (bash scripting)

**TEACH**
- `ipmitool sdr elist` prints lines like `Fan2 | 31h | cr | 29.2 | 0 RPM`: fields separated by `|`, **third field = status** (`ok`, `nc`, `cr`, `nr`, `ns`...).
- `awk -F'|' '{ print $1, $3 }' FILE` splits on `|`. Trim spaces with `gsub(/^[ \t]+|[ \t]+$/, "", var)`. `END { exit rc }` sets the exit code.
- `$1` is the first script argument; `[[ -r "$f" ]]` tests readability; `exit N` sets the status; `>&2` writes to stderr.

**DO** - write `/usr/local/bin/sdr-triage.sh FILE` (executable, `#!/bin/bash`):
- Print only sensors whose status is **not** `ok`, as `NAME: STATUS` (both trimmed), one per line, in file order. Skip blank lines and lines starting with `#`.
- Exit 1 if it printed anything, 0 if everything was ok.
- No argument or unreadable file: message on stderr, exit 2.
- Samples: `/opt/dcdata/sdr/*.sdr`. Careful: a sensor *name* can contain the text "ok".

## R09 - Serve the logs (SELinux + firewalld)

**TEACH**
- Apache serves only files labelled `httpd_sys_content_t`. A custom path needs a **persistent** rule: `semanage fcontext -a -t httpd_sys_content_t '/path(/.*)?'` then `restorecon -R /path` (`chcon` is not persistent). `ls -Z` shows labels.
- Extra config goes in `/etc/httpd/conf.d/*.conf`: `Listen 8080`, `Alias /url /dir`, `<Directory /dir> Require all granted </Directory>`.
- `firewall-cmd --permanent --add-port=8080/tcp` then `firewall-cmd --reload`. Test from the other node: `curl` from node2.

**DO**
1. Install `httpd`; serve `/srv/ctlogs` at `http://node1:8080/logs/`; enabled and running.
2. SELinux stays **Enforcing**; the label is correct and persistent.
3. Open 8080/tcp permanently and verify from node2 (`ssh node2`, then curl `192.168.56.101`).

## R10 - OOB management NIC (networking)

**TEACH**
- NetworkManager profiles: `nmcli con add type TYPE ifname IF con-name NAME ipv4.method manual ipv4.addresses A.B.C.D/24 ipv4.dns X`. Type `dummy` makes a software NIC - stand-in for a BMC/OOB port. `nmcli con show NAME`, `nmcli dev status` to verify.
- `hostnamectl set-hostname NAME` is persistent. Static name->IP mappings go in `/etc/hosts`; `getent hosts NAME` tests resolution.

**DO**
1. Connection `oob-mgmt` on interface `oob0` (type dummy): static `10.99.0.10/24`, DNS `10.99.0.2`, autoconnect on.
2. Hostname `dcops-node1.dc.example`.
3. `bmc-rack01.oob` must resolve to `10.99.0.50`.
4. Do not disturb `enp0s3` (your NAT link).

## R11 - Persistent journal (logging)

**TEACH**
- Default journald keeps logs in `/run` (lost at reboot). `Storage=persistent` under `[Journal]` in a drop-in `/etc/systemd/journald.conf.d/NAME.conf` keeps them on disk; `SystemMaxUse=200M` caps the size.
- `systemctl restart systemd-journald` re-reads config; `journalctl --flush` moves the runtime journal to `/var/log/journal` (which then gets created). `journalctl -b -p err` = errors from this boot.

**DO**
1. Persistent storage, capped at 200M, via a drop-in file (not by editing the main conf).
2. Make sure journal files exist under `/var/log/journal/<machine-id>/` right now.
3. Save this boot's priority-`err` messages to `/root/boot-errors.txt`.
