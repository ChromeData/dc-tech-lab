#!/usr/bin/env bash
#
# DC-tech RHCSA track grader (R01-R11).  Run on node1 as root.
#
#   bash grade-r.sh            grade everything
#   bash grade-r.sh -t 5       grade only R05   (also: -t R05)
#   bash grade-r.sh -v         show why each task failed
#
# Checks LIVE SYSTEM STATE, not history. Grade once, REBOOT, grade again:
# the second run is the real score.

set -uo pipefail

VERBOSE=0; ONLY=""
while getopts "t:vh" opt; do
  case $opt in
    t) ONLY="$OPTARG" ;;
    v) VERBOSE=1 ;;
    h) sed -n '2,12p' "$0"; exit 0 ;;
    *) exit 2 ;;
  esac
done
[[ $EUID -ne 0 ]] && { echo "Run as root: sudo bash $0"; exit 1; }

if [[ -t 1 ]]; then R=$'\e[31m'; G=$'\e[32m'; D=$'\e[2m'; N=$'\e[0m'; else R=""; G=""; D=""; N=""; fi

PASS=0; FAIL=0; TOTAL=0; FAILED_TASKS=()
CUR_ID=""; CUR_NAME=""; CUR_ERRS=()

task()  { CUR_ID="$1"; CUR_NAME="$2"; CUR_ERRS=(); }
check() { local d="$1"; shift; "$@" >/dev/null 2>&1 || CUR_ERRS+=("$d"); }
checkv(){ [[ "$2" == "$3" ]] || CUR_ERRS+=("$1 (want '$2', got '${3:-<empty>}')"); }
fails() { CUR_ERRS+=("$1"); }
report() {
  TOTAL=$((TOTAL+1))
  if [[ ${#CUR_ERRS[@]} -eq 0 ]]; then
    PASS=$((PASS+1)); printf "  %sPASS%s  %s %s\n" "$G" "$N" "$CUR_ID" "$CUR_NAME"
  else
    FAIL=$((FAIL+1)); FAILED_TASKS+=("$CUR_ID")
    printf "  %sFAIL%s  %s %s\n" "$R" "$N" "$CUR_ID" "$CUR_NAME"
    if [[ $VERBOSE -eq 1 ]]; then for e in "${CUR_ERRS[@]}"; do printf "        %s- %s%s\n" "$D" "$e" "$N"; done; fi
  fi
}
want() {  # want 5  -> true if no filter or filter is 5 / 05 / R05
  [[ -z "$ONLY" ]] && return 0
  local o="${ONLY#R}"; o="${o#r}"; [[ "$((10#$o))" == "$1" ]]
}
unit_ok() { systemctl is-enabled "$1" >/dev/null 2>&1 && systemctl is-active "$1" >/dev/null 2>&1; }
trim() { sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//'; }

echo
echo "DC-tech RHCSA track - $(hostname)"
echo

# ------------------------------------------------------------------ R01
if want 1; then
task R01 "Log store on LVM: XFS + ext4, mounted by UUID, extended online"
check "VG dcvg missing" vgs dcvg
check "PV /dev/sdb not in dcvg" bash -c "pvs --noheadings -o pv_name,vg_name | grep -qE '/dev/sdb[[:space:]]+dcvg'"
check "PV /dev/sdc not added to dcvg" bash -c "pvs --noheadings -o pv_name,vg_name | grep -qE '/dev/sdc[[:space:]]+dcvg'"
check "LV dcvg/ctlogs missing" lvs dcvg/ctlogs
check "LV dcvg/scratch missing" lvs dcvg/scratch
checkv "/srv/ctlogs filesystem" xfs "$(findmnt -no FSTYPE /srv/ctlogs 2>/dev/null)"
checkv "/var/dcscratch filesystem" ext4 "$(findmnt -no FSTYPE /var/dcscratch 2>/dev/null)"
checkv "/srv/ctlogs source" /dev/mapper/dcvg-ctlogs "$(findmnt -no SOURCE /srv/ctlogs 2>/dev/null)"
checkv "/var/dcscratch source" /dev/mapper/dcvg-scratch "$(findmnt -no SOURCE /var/dcscratch 2>/dev/null)"
for pair in "ctlogs:/srv/ctlogs:xfs" "scratch:/var/dcscratch:ext4"; do
  IFS=: read -r lv mp ft <<<"$pair"
  uuid=$(blkid -s UUID -o value "/dev/dcvg/$lv" 2>/dev/null)
  if [[ -z "$uuid" ]] || ! grep -qE "^UUID=$uuid[[:space:]]+$mp[[:space:]]+$ft[[:space:]]" /etc/fstab; then
    fails "/etc/fstab has no UUID= line for $mp ($ft)"
  fi
done
sz=$(lvs --noheadings --nosuffix --units b -o lv_size dcvg/ctlogs 2>/dev/null | tr -d ' ')
(( ${sz:-0} >= 7500000000 )) || fails "LV ctlogs should be extended to 7G (is ${sz:-0} bytes)"
fsz=$(df -B1 --output=size /srv/ctlogs 2>/dev/null | tail -1 | tr -d ' ')
(( ${fsz:-0} >= 7000000000 )) || fails "/srv/ctlogs FILESYSTEM not grown with the LV (df shows ${fsz:-0} bytes)"
ssz=$(lvs --noheadings --nosuffix --units b -o lv_size dcvg/scratch 2>/dev/null | tr -d ' ')
(( ${ssz:-0} >= 2000000000 && ${ssz:-0} < 2300000000 )) || fails "LV scratch should be 2G (is ${ssz:-0} bytes)"
report
fi

# ------------------------------------------------------------------ R02
if want 2; then
task R02 "Navigate the rack tree, find/grep/copy, links"
RK=/opt/dcdata/racks; RR=/srv/ctlogs/rack-reports
mountpoint -q /srv/ctlogs || fails "/srv/ctlogs is not a mounted LV - finish R01 first"
miss=0
for r in 01 02 03 04; do for s in bmc gpu; do [[ -d $RR/rack$r/$s ]] || miss=$((miss+1)); done; done
(( miss == 0 )) || fails "$miss of the 8 report dirs $RR/rackNN/{bmc,gpu} are missing"
if [[ -s /root/big-gpu-logs.txt ]]; then
  diff -q <(sort /root/big-gpu-logs.txt | trim) <(find $RK -name gpu.log -size +10k | sort) >/dev/null \
    || fails "/root/big-gpu-logs.txt does not list exactly the gpu.log files larger than 10 KiB"
else fails "/root/big-gpu-logs.txt missing or empty"; fi
if [[ -s /root/gpu-lost.txt ]]; then
  diff -q <(sort /root/gpu-lost.txt) <(grep -rh --include=gpu.log 'fallen off the bus' $RK | sort) >/dev/null \
    || fails "/root/gpu-lost.txt is not exactly the matching lines (no filenames, every gpu.log)"
else fails "/root/gpu-lost.txt missing or empty"; fi
cp4=$RR/rack04/src/node03/gpu.log
if [[ -f $cp4 ]]; then
  cmp -s $cp4 $RK/rack04/node03/gpu.log || fails "copied gpu.log differs from the original"
  [[ "$(stat -c %Y $cp4)" == "$(stat -c %Y $RK/rack04/node03/gpu.log)" ]] || fails "copy did not preserve timestamps (use archive mode)"
  [[ -f $RR/rack04/src/node01/bmc.log && -f $RR/rack04/src/node02/dmesg.txt ]] || fails "rack04 copy is not the whole tree"
else fails "$RR/rack04/src/node03/gpu.log missing (copy rack04 -> $RR/rack04/src)"; fi
checkv "symlink /srv/ctlogs/latest" "$RR/rack04" "$(readlink /srv/ctlogs/latest 2>/dev/null)"
if [[ -e /opt/dcdata/rack01-node01-bmc.log ]]; then
  [[ /opt/dcdata/rack01-node01-bmc.log -ef $RK/rack01/node01/bmc.log && ! -L /opt/dcdata/rack01-node01-bmc.log ]] \
    || fails "/opt/dcdata/rack01-node01-bmc.log is not a HARD link to rack01/node01/bmc.log"
else fails "hard link /opt/dcdata/rack01-node01-bmc.log missing"; fi
report
fi

# ------------------------------------------------------------------ R03
if want 3; then
task R03 "dcops group, setgid RMA dir, ACL, aging, sudo"
checkv "group dcops GID" 3000 "$(getent group dcops | cut -d: -f3)"
for u in tech1:3101 tech2:3102; do
  n=${u%%:*}; id_=${u##*:}
  checkv "$n UID" "$id_" "$(id -u $n 2>/dev/null)"
  id -nG $n 2>/dev/null | tr ' ' '\n' | grep -qx dcops || fails "$n is not in dcops"
  [[ "$(id -gn $n 2>/dev/null)" != dcops ]] || fails "$n has dcops as PRIMARY group (must be supplementary)"
done
checkv "noc1 UID" 3201 "$(id -u noc1 2>/dev/null)"
id -nG noc1 2>/dev/null | tr ' ' '\n' | grep -qx dcops && fails "noc1 must NOT be in dcops"
checkv "noc1 shell" /bin/bash "$(getent passwd noc1 | cut -d: -f7)"
checkv "svc-collector UID" 3001 "$(id -u svc-collector 2>/dev/null)"
case "$(getent passwd svc-collector | cut -d: -f7)" in /sbin/nologin|/usr/sbin/nologin|/bin/false) ;; *) fails "svc-collector must have a non-login shell";; esac
if [[ -d /srv/ctlogs/rma ]]; then
  checkv "/srv/ctlogs/rma mode+group" "2770 dcops" "$(stat -c '%a %G' /srv/ctlogs/rma)"
  checkv "/srv/ctlogs/rma owner" root "$(stat -c %U /srv/ctlogs/rma)"
  acl=$(getfacl -p /srv/ctlogs/rma 2>/dev/null)
  grep -qE '^user:noc1:r-x' <<<"$acl" || fails "no ACL user:noc1:r-x on /srv/ctlogs/rma"
  grep -qE '^default:user:noc1:r-x' <<<"$acl" || fails "no DEFAULT ACL for noc1 on /srv/ctlogs/rma"
  if id tech1 >/dev/null 2>&1 && id noc1 >/dev/null 2>&1; then
    p=/srv/ctlogs/rma/.gradeprobe
    rm -f $p
    runuser -u tech1 -- bash -c "echo x > $p" 2>/dev/null || fails "tech1 cannot create files in the RMA dir"
    if [[ -f $p ]]; then
      checkv "new file inherits group" dcops "$(stat -c %G $p)"
      getfacl -p $p 2>/dev/null | grep -q '^user:noc1:' || fails "new files do not inherit noc1's ACL (default ACL)"
      runuser -u noc1 -- cat $p >/dev/null 2>&1 || fails "noc1 cannot read files in the RMA dir"
    fi
    runuser -u noc1 -- touch /srv/ctlogs/rma/.noc1probe 2>/dev/null && fails "noc1 can WRITE to the RMA dir (should be read-only)"
    rm -f $p /srv/ctlogs/rma/.noc1probe
  fi
else fails "/srv/ctlogs/rma missing"; fi
ch=$(chage -l tech1 2>/dev/null)
grep -qE 'Maximum number of days between password change[[:space:]]*:[[:space:]]*90$' <<<"$ch" || fails "tech1 max password age is not 90"
grep -qE 'Number of days of warning before password expires[[:space:]]*:[[:space:]]*7$' <<<"$ch" || fails "tech1 password warning is not 7"
sl=$(sudo -l -U tech1 2>/dev/null)
grep -q 'NOPASSWD' <<<"$sl" && grep -q '/usr/bin/ipmitool' <<<"$sl" || fails "dcops members cannot run /usr/bin/ipmitool via sudo without a password"
grep -q 'ALL) NOPASSWD: ALL' <<<"$sl" && fails "sudo rule is too broad (only ipmitool allowed)"
visudo -c >/dev/null 2>&1 || fails "sudoers has a syntax error"
report
fi

# ------------------------------------------------------------------ R04
if want 4; then
task R04 "Install ipmitool + lm_sensors, query package ownership"
check "ipmitool not installed" rpm -q ipmitool
check "lm_sensors not installed" rpm -q lm_sensors
check "jq/lshw were removed" rpm -q jq lshw
checkv "/root/sensors-pkg.txt" lm_sensors "$(cat /root/sensors-pkg.txt 2>/dev/null | trim)"
checkv "/root/sshd-owner.txt" openssh-server "$(cat /root/sshd-owner.txt 2>/dev/null | trim)"
report
fi

# ------------------------------------------------------------------ R05
if want 5; then
task R05 "Find the runaway service, kill it for good, nice the soak monitor"
if pgrep -x gpu-burnin >/dev/null; then fails "gpu-burnin is still running"; fi
st=$(systemctl is-enabled gpu-burnin.service 2>&1)
[[ "$st" == enabled ]] && fails "gpu-burnin.service is still enabled (it will come back at boot)"
systemctl is-active -q gpu-burnin.service && fails "gpu-burnin.service is active"
grep -qE '^gpu-burnin(\.service)?$' <(cat /root/runaway-unit.txt 2>/dev/null | trim) || fails "/root/runaway-unit.txt should name the offending unit"
unit_ok gpu-soak.service || fails "gpu-soak.service must stay enabled and running"
checkv "gpu-soak unit Nice= (persistent)" 10 "$(systemctl show -p Nice --value gpu-soak.service 2>/dev/null)"
pid=$(systemctl show -p MainPID --value gpu-soak.service 2>/dev/null)
checkv "gpu-soak running process nice value" 10 "$(ps -o ni= -p "${pid:-0}" 2>/dev/null | tr -d ' ')"
report
fi

# ------------------------------------------------------------------ R06
if want 6; then
task R06 "Debug ctlog-sync.service with journalctl/systemctl"
check "ctlog-sync.service is not enabled" systemctl is-enabled ctlog-sync.service
check "ctlog-sync.service is not active" systemctl is-active ctlog-sync.service
checkv "ctlog-sync Result" success "$(systemctl show -p Result --value ctlog-sync.service 2>/dev/null)"
grep -q '^ctlog-sync ok ' /var/lib/ctlog-sync/last-sync 2>/dev/null || fails "/var/lib/ctlog-sync/last-sync was not written by the script"
grep -q 'last-sync' /usr/local/sbin/ctlog-sync.sh 2>/dev/null || fails "the sync script itself was replaced (fix the unit/permissions, not the script)"
report
fi

# ------------------------------------------------------------------ R07
if want 7; then
task R07 "Nightly tar archive with a systemd timer"
S=/usr/local/bin/ctlog-archive.sh
[[ -x $S ]] || fails "$S missing or not executable"
head -1 $S 2>/dev/null | grep -q '^#!' || fails "$S has no shebang"
check "ctlog-archive.timer not enabled" systemctl is-enabled ctlog-archive.timer
check "ctlog-archive.timer not active" systemctl is-active ctlog-archive.timer
systemctl show -p TimersCalendar ctlog-archive.timer 2>/dev/null | grep -q '02:15:00' || fails "timer does not fire daily at 02:15"
systemctl cat ctlog-archive.service >/dev/null 2>&1 || fails "ctlog-archive.service missing"
systemctl show -p Persistent --value ctlog-archive.timer 2>/dev/null | grep -qi yes || fails "timer is not Persistent=true"
if [[ -x $S ]] && mountpoint -q /srv/ctlogs; then
  systemctl start ctlog-archive.service >/dev/null 2>&1 || fails "ctlog-archive.service failed to run"
  a=$(ls /var/backups/ctlogs/ctlogs-$(date +%F).tar.gz 2>/dev/null | head -1)
  if [[ -n "$a" ]]; then
    lst=$(tar tzf "$a" 2>/dev/null)
    grep -q '^rack-reports/' <<<"$lst" || fails "archive members must start with rack-reports/ (use -C, no absolute paths)"
    grep -q '^/' <<<"$lst" && fails "archive contains absolute paths"
  else fails "service ran but /var/backups/ctlogs/ctlogs-$(date +%F).tar.gz was not created"; fi
fi
report
fi

# ------------------------------------------------------------------ R08
if want 8; then
task R08 "sdr-triage.sh prints only sensors that are not ok"
S=/usr/local/bin/sdr-triage.sh
if [[ -x $S ]]; then
  bash -n $S 2>/dev/null || fails "syntax error in $S"
  head -1 $S | grep -q '^#!.*bash' || fails "$S needs a #!/bin/bash shebang"
  t=$(mktemp)
  cat > $t <<'EOF'
# header comment | 00h | cr | x | y

Inlet Temp       | 04h | ok  |  7.1 | 24 degrees C
Disk ok Slot 3   | 70h | cr  | 26.0 | Drive Fault
  GPU7 Temp  	| 17h | nc  | 41.7 | 91 degrees C
Fan1  | 30h | ok  | 29.1 | 8400 RPM
PSU9 Status|51h|ns|10.2|No Reading
Look ok sensor | 99h | ok | 1.1 | fine
EOF
  want_out=$'Disk ok Slot 3: cr\nGPU7 Temp: nc\nPSU9 Status: ns'
  got=$($S $t 2>/dev/null); rc=$?
  checkv "output for mixed file" "$want_out" "$got"
  checkv "exit code when problems found" 1 "$rc"
  printf 'Inlet | 04h | ok | 7.1 | 20 degrees C\nFan1 | 30h | ok | 1 | 1 RPM\n' > $t
  got=$($S $t 2>/dev/null); rc=$?
  checkv "output for all-ok file" "" "$got"
  checkv "exit code when all ok" 0 "$rc"
  $S /nonexistent.sdr >/dev/null 2>&1; rc=$?; checkv "exit code for missing file" 2 "$rc"
  $S >/dev/null 2>&1; rc=$?; checkv "exit code with no argument" 2 "$rc"
  got=$($S /opt/dcdata/sdr/gb200-rack01-node01.sdr 2>/dev/null)
  checkv "sample rack01 file" $'GPU1 Temp: nc\nFan2: cr\nPSU2 Status: ns' "$got"
  rm -f $t
else fails "$S missing or not executable"; fi
report
fi

# ------------------------------------------------------------------ R09
if want 9; then
task R09 "Serve /srv/ctlogs over httpd:8080 with the right SELinux label + firewalld"
check "httpd not installed" rpm -q httpd
unit_ok httpd || fails "httpd must be enabled and running"
ss -ltn 2>/dev/null | grep -qE ':8080[[:space:]]' || fails "nothing listening on TCP 8080"
checkv "SELinux mode (runtime)" Enforcing "$(getenforce)"
grep -qE '^SELINUX=enforcing' /etc/selinux/config || fails "SELinux config is not enforcing"
echo "dclab-probe-$$" 2>/dev/null > /srv/ctlogs/gradeprobe.txt
body=$(curl -s --max-time 5 http://localhost:8080/logs/gradeprobe.txt 2>/dev/null)
[[ "$body" == "dclab-probe-$$" ]] || fails "http://localhost:8080/logs/gradeprobe.txt did not return the file (check Alias, Require, SELinux label)"
semanage fcontext -l -C 2>/dev/null | grep -q '/srv/ctlogs.*httpd_sys_content_t' || fails "no PERSISTENT fcontext rule (semanage fcontext) for /srv/ctlogs"
matchpathcon -V /srv/ctlogs 2>/dev/null | grep -q 'verified' || fails "on-disk label of /srv/ctlogs does not match policy"
ls -Z /srv/ctlogs/gradeprobe.txt 2>/dev/null | grep -q httpd_sys_content_t || fails "files under /srv/ctlogs are not httpd_sys_content_t"
fw=$(firewall-cmd --permanent --list-all 2>/dev/null)
grep -qE '(ports:.*8080/tcp|services:.*\bhttp-alt\b)' <<<"$fw" || fails "firewalld PERMANENT config does not open 8080/tcp"
firewall-cmd --query-port=8080/tcp >/dev/null 2>&1 || firewall-cmd --query-service=http-alt >/dev/null 2>&1 || fails "8080/tcp is not open in the RUNTIME firewall"
unit_ok firewalld || fails "firewalld must stay enabled and running"
r=$(ssh -i /root/.ssh/id_ed25519 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o BatchMode=yes -o ConnectTimeout=5 -o LogLevel=ERROR node2 \
    "curl -s --max-time 5 http://192.168.56.101:8080/logs/gradeprobe.txt" 2>/dev/null)
[[ "$r" == "dclab-probe-$$" ]] || fails "node2 cannot fetch http://192.168.56.101:8080/logs/gradeprobe.txt (firewall? host-only NIC?)"
rm -f /srv/ctlogs/gradeprobe.txt
report
fi

# ------------------------------------------------------------------ R10
if want 10; then
task R10 "OOB management NIC (nmcli), hostname, static host entry"
checkv "connection oob-mgmt type" dummy "$(nmcli -g connection.type con show oob-mgmt 2>/dev/null)"
checkv "oob-mgmt interface-name" oob0 "$(nmcli -g connection.interface-name con show oob-mgmt 2>/dev/null)"
checkv "oob-mgmt ipv4.method" manual "$(nmcli -g ipv4.method con show oob-mgmt 2>/dev/null)"
checkv "oob-mgmt ipv4.addresses" 10.99.0.10/24 "$(nmcli -g ipv4.addresses con show oob-mgmt 2>/dev/null)"
checkv "oob-mgmt ipv4.dns" 10.99.0.2 "$(nmcli -g ipv4.dns con show oob-mgmt 2>/dev/null)"
checkv "oob-mgmt autoconnect" yes "$(nmcli -g connection.autoconnect con show oob-mgmt 2>/dev/null)"
ip -4 -o addr show dev oob0 2>/dev/null | grep -q '10.99.0.10/24' || fails "oob0 is not UP with 10.99.0.10/24 right now"
checkv "static hostname" dcops-node1.dc.example "$(hostnamectl --static 2>/dev/null)"
checkv "/etc/hostname" dcops-node1.dc.example "$(cat /etc/hostname 2>/dev/null)"
checkv "bmc-rack01.oob resolves to" 10.99.0.50 "$(getent hosts bmc-rack01.oob | awk '{print $1}')"
nmcli -t -f DEVICE,STATE dev 2>/dev/null | grep -q '^enp0s3:connected' || fails "management NAT NIC enp0s3 got disconnected - don't break it"
report
fi

# ------------------------------------------------------------------ R11
if want 11; then
task R11 "Persistent journald with a size cap"
cfg=$(systemd-analyze cat-config systemd/journald.conf 2>/dev/null | grep -vE '^\s*#')
checkv "effective Storage=" persistent "$(grep -E '^Storage=' <<<"$cfg" | tail -1 | cut -d= -f2)"
checkv "effective SystemMaxUse=" 200M "$(grep -E '^SystemMaxUse=' <<<"$cfg" | tail -1 | cut -d= -f2)"
[[ -d /var/log/journal ]] || fails "/var/log/journal does not exist"
mid=$(cat /etc/machine-id 2>/dev/null)
ls /var/log/journal/$mid/*.journal >/dev/null 2>&1 || fails "journal files are not being written to /var/log/journal/<machine-id>/"
[[ -f /root/boot-errors.txt ]] || fails "/root/boot-errors.txt (journalctl -b -p err output) missing"
check "journald not running" systemctl is-active systemd-journald
report
fi

echo
printf "  Result: %d/%d passed" "$PASS" "$TOTAL"
(( TOTAL > 0 )) && printf "  (%d%%, pass mark 70%%)" $(( PASS*100/TOTAL ))
echo
[[ $FAIL -gt 0 ]] && echo "  Failed: ${FAILED_TASKS[*]}"
echo
[[ $FAIL -eq 0 ]]
