#!/usr/bin/env bash
#
# DC-tech RHCE (EX294) track grader (E01-E08).  Run on node1 (the control node) as root.
#
#   bash grade-e.sh            grade everything
#   bash grade-e.sh -t 4       grade only E04   (also: -t E04)
#   bash grade-e.sh -v         show why each task failed
#
# Runs YOUR playbooks from /root/dclab-ansible and inspects the managed nodes.
# Slow (a few minutes): it executes real ansible-playbook runs, some of them twice.

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
PD=/root/dclab-ansible

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
want() { [[ -z "$ONLY" ]] && return 0; local o="${ONLY#E}"; o="${o#e}"; [[ "$((10#$o))" == "$1" ]]; }
trim() { sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//'; }

# run a command on a node with the lab key, independent of the student's ansible config
rsh() { local h=$1; shift
  ssh -i /root/.ssh/id_ed25519 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o BatchMode=yes \
      -o ConnectTimeout=8 -o LogLevel=ERROR root@"$h" "$@"; }
# run a student playbook; output kept in $LAST
LAST=""; LAST_RC=0
ap() { LAST=$(cd $PD 2>/dev/null && timeout 400 ansible-playbook "$@" 2>&1); LAST_RC=$?; }
tail_of() { tail -n 6 <<<"$LAST" | tr '\n' '~' | cut -c1-300; }
have_ansible() { command -v ansible-playbook >/dev/null 2>&1 && [[ -d $PD ]]; }

BMC_USER_EXPECT="ipmiadmin"; BMC_PASS_EXPECT='Gb200-Rack!7'
BANNER_TEXT="DCOPS AUTHORIZED ACCESS ONLY - all sessions are logged"

echo
echo "DC-tech RHCE track - control node $(hostname)"
echo

# ------------------------------------------------------------------ E01
if want 1; then
task E01 "ansible-core, ansible.cfg, inventory with groups"
check "ansible-core not installed" rpm -q ansible-core
if have_ansible; then
  [[ -f $PD/ansible.cfg ]] || fails "$PD/ansible.cfg missing"
  [[ -f $PD/inventory ]] || fails "$PD/inventory missing"
  cfg=$(cd $PD && ansible-config dump --only-changed 2>/dev/null)
  grep -q "DEFAULT_HOST_LIST.*$PD/inventory" <<<"$cfg" || fails "ansible.cfg does not point 'inventory' at $PD/inventory"
  grep -qi "HOST_KEY_CHECKING.*False" <<<"$cfg" || fails "ansible.cfg: host_key_checking is not disabled"
  grep -q "DEFAULT_REMOTE_USER.*root" <<<"$cfg" || fails "ansible.cfg: remote_user is not root"
  grep -q "DEFAULT_VAULT_PASSWORD_FILE.*vault_pass" <<<"$cfg" || fails "ansible.cfg: vault_password_file not set to .vault_pass"
  grep -q "DEFAULT_ROLES_PATH.*$PD/roles" <<<"$cfg" || fails "ansible.cfg: roles_path should be $PD/roles"
  inv=$(cd $PD && ansible-inventory --list 2>/dev/null)
  if [[ -n "$inv" ]]; then
    python3 -c '
import json,sys
j=json.loads(sys.argv[1])
def hosts(g):
    d=j.get(g,{}); h=set(d.get("hosts",[]))
    for c in d.get("children",[]): h|=hosts(c)
    return h
ok = hosts("logservers")=={"node2"} and hosts("racknodes")=={"node1"} and hosts("dc")=={"node1","node2"}
sys.exit(0 if ok else 1)
' "$inv" || fails "inventory groups wrong (want logservers=[node2], racknodes=[node1], dc = both)"
  else fails "ansible-inventory printed nothing (inventory unreadable)"; fi
  out=$(cd $PD && ansible dc -m ping -o 2>&1)
  [[ $(grep -c 'SUCCESS' <<<"$out") -eq 2 ]] || fails "ansible dc -m ping must succeed on both nodes: $(head -c 200 <<<"$out")"
else fails "ansible not installed / $PD missing"; fi
report
fi

# ------------------------------------------------------------------ E02
if want 2; then
task E02 "Ad-hoc commands only (file, dnf, command)"
for h in node1 node2; do
  checkv "$h /etc/dcops mode+owner" "750 root root" "$(rsh $h "stat -c '%a %U %G' /etc/dcops" 2>/dev/null)"
  rsh $h "rpm -q iperf3" >/dev/null 2>&1 || fails "$h: iperf3 not installed"
done
f=/root/uptime-all.txt
if [[ -s $f ]]; then
  grep -q node1 $f && grep -q node2 $f && grep -q 'load average' $f || fails "$f should hold the uptime output of BOTH nodes"
else fails "$f missing"; fi
report
fi

# ------------------------------------------------------------------ E03
if want 3; then
task E03 "hwreport.yml writes /root/hwreport.txt from facts (NONE when missing)"
if have_ansible && [[ -f $PD/hwreport.yml ]]; then
  ap hwreport.yml
  [[ $LAST_RC -eq 0 ]] || fails "hwreport.yml failed: $(tail_of)"
  tree=$(mktemp -d)
  ANSIBLE_CONFIG=/nonexistent.cfg ANSIBLE_HOST_KEY_CHECKING=False ansible -i node1,node2, all -u root -m setup --tree $tree >/dev/null 2>&1
  for h in node1 node2; do
    exp=$(python3 -c '
import json,sys
f=json.load(open(sys.argv[1]))["ansible_facts"]
print("HOSTNAME=%s" % f["ansible_hostname"])
print("CPUS=%s" % f["ansible_processor_vcpus"])
print("MEMORY_MB=%s" % f["ansible_memtotal_mb"])
for d in ("sda","sdb","sdc"):
    print("%s_SIZE=%s" % (d.upper(), f["ansible_devices"].get(d,{}).get("size","NONE")))
' "$tree/$h")
    got=$(rsh $h "cat /root/hwreport.txt" 2>/dev/null | trim | sort)
    [[ "$got" == "$(sort <<<"$exp")" ]] || fails "$h /root/hwreport.txt wrong. want: $(tr '\n' ' ' <<<"$exp") got: $(tr '\n' ' ' <<<"$got")"
  done
  rm -rf $tree
else fails "hwreport.yml missing in $PD"; fi
report
fi

# ------------------------------------------------------------------ E04
if want 4; then
task E04 "Vault-encrypted bmc_creds.yml feeds a 0600 template"
if have_ansible && [[ -f $PD/bmc.yml ]]; then
  head -1 $PD/bmc_creds.yml 2>/dev/null | grep -q '^\$ANSIBLE_VAULT;' || fails "bmc_creds.yml is not ansible-vault encrypted"
  v=$(cd $PD && ansible-vault view --vault-password-file .vault_pass bmc_creds.yml 2>/dev/null)
  grep -qE "^bmc_user:[[:space:]]*['\"]?$BMC_USER_EXPECT['\"]?[[:space:]]*$" <<<"$v" || fails "vault does not contain bmc_user: $BMC_USER_EXPECT"
  grep -qF "$BMC_PASS_EXPECT" <<<"$v" && grep -q '^bmc_pass:' <<<"$v" || fails "vault does not contain bmc_pass with the required password"
  grep -rIlF "$BMC_PASS_EXPECT" $PD --include='*.yml' --include='*.j2' --include='*.cfg' --exclude=bmc_creds.yml 2>/dev/null | grep -q . \
    && fails "the BMC password appears in plaintext in a playbook/template"
  ls $PD/templates/*.j2 >/dev/null 2>&1 && grep -q 'bmc_user' $PD/templates/*.j2 || fails "no template in $PD/templates uses bmc_user"
  ap bmc.yml
  [[ $LAST_RC -eq 0 ]] || fails "bmc.yml failed: $(tail_of)"
  for h in node1 node2; do
    checkv "$h /etc/dcops/bmc.conf mode+owner" "600 root root" "$(rsh $h "stat -c '%a %U %G' /etc/dcops/bmc.conf" 2>/dev/null)"
    c=$(rsh $h "cat /etc/dcops/bmc.conf" 2>/dev/null)
    grep -qx "BMC_USER=$BMC_USER_EXPECT" <<<"$c" && grep -qxF "BMC_PASS=$BMC_PASS_EXPECT" <<<"$c" || fails "$h bmc.conf must contain BMC_USER=... and BMC_PASS=... lines"
  done
else fails "bmc.yml missing in $PD"; fi
report
fi

# ------------------------------------------------------------------ E05
if want 5; then
task E05 "Role ctlogs builds the log server on [logservers]"
RL=$PD/roles/ctlogs
for f in tasks/main.yml handlers/main.yml defaults/main.yml; do [[ -s $RL/$f ]] || fails "roles/ctlogs/$f missing/empty"; done
ls $RL/templates/*.j2 >/dev/null 2>&1 || fails "roles/ctlogs/templates has no .j2 file"
grep -q 'ctlogs_port' $RL/defaults/main.yml 2>/dev/null || fails "defaults/main.yml must define ctlogs_port"
grep -q 'notify' $RL/tasks/main.yml 2>/dev/null || fails "role tasks never notify a handler"
if have_ansible && [[ -f $PD/logservers.yml ]]; then
  grep -q 'ctlogs' $PD/logservers.yml || fails "logservers.yml does not apply the ctlogs role"
  ap logservers.yml
  [[ $LAST_RC -eq 0 ]] || fails "logservers.yml failed: $(tail_of)"
  rsh node2 "systemctl is-enabled httpd && systemctl is-active httpd" >/dev/null 2>&1 || fails "node2: httpd not enabled+active"
  rsh node2 "ss -ltn | grep -q ':8080 '" >/dev/null 2>&1 || fails "node2: not listening on 8080"
  rsh node2 "ls -Zd /srv/ctlogs" 2>/dev/null | grep -q httpd_sys_content_t || fails "node2: /srv/ctlogs is not httpd_sys_content_t"
  body=$(rsh node2 "curl -s --max-time 5 http://localhost:8080/logs/README.txt" 2>/dev/null)
  grep -q 'node2' <<<"$body" || fails "node2: http://localhost:8080/logs/README.txt should be served and mention node2 (got: $(head -c 80 <<<"$body"))"
else fails "logservers.yml missing in $PD"; fi
report
fi

# ------------------------------------------------------------------ E06
if want 6; then
task E06 "Handler restarts sshd only when the banner changes"
if have_ansible && [[ -f $PD/sshbanner.yml ]]; then
  grep -qE '^\s*handlers:' $PD/sshbanner.yml || fails "sshbanner.yml defines no handlers:"
  ap sshbanner.yml
  [[ $LAST_RC -eq 0 ]] || fails "sshbanner.yml failed: $(tail_of)"
  p1=$(rsh node2 "systemctl show -p MainPID --value sshd")
  ap sshbanner.yml --limit node2
  p2=$(rsh node2 "systemctl show -p MainPID --value sshd")
  [[ "$p1" == "$p2" ]] || fails "sshd was restarted although nothing changed (handler must only fire on change)"
  grep -qE 'changed=0' <<<"$LAST" || fails "second run reported changes"
  rsh node2 "echo tampered > /etc/issue.net"
  ap sshbanner.yml --limit node2
  p3=$(rsh node2 "systemctl show -p MainPID --value sshd")
  [[ "$p2" != "$p3" && -n "$p3" ]] || fails "after changing the banner file, sshd was NOT restarted by the handler"
  rsh node2 "cat /etc/issue.net" 2>/dev/null | grep -qF "$BANNER_TEXT" || fails "/etc/issue.net does not contain the banner text"
  rsh node2 "sshd -T 2>/dev/null | grep -qix 'banner /etc/issue.net'" || fails "node2: sshd is not configured with Banner /etc/issue.net"
  rsh node1 "sshd -T 2>/dev/null | grep -qix 'banner /etc/issue.net'" || fails "node1 has no Banner /etc/issue.net (play must target all of dc)"
else fails "sshbanner.yml missing in $PD"; fi
report
fi

# ------------------------------------------------------------------ E07
if want 7; then
task E07 "Loops + when: tech users only on [racknodes]"
if have_ansible && [[ -f $PD/techusers.yml ]]; then
  grep -q 'techs.yml' $PD/techusers.yml || fails "techusers.yml must load vars/techs.yml"
  grep -qE '^\s*(when|loop|with_items):' $PD/techusers.yml || fails "techusers.yml uses no loop/when"
  ap techusers.yml
  [[ $LAST_RC -eq 0 ]] || fails "techusers.yml failed: $(tail_of)"
  for u in dctech01:4101:/bin/bash dctech02:4102:/bin/bash dctech03:4103:/sbin/nologin; do
    IFS=: read -r n uid sh <<<"$u"
    checkv "node1 $n uid:shell" "$uid:$sh" "$(rsh node1 "getent passwd $n | cut -d: -f3,7" 2>/dev/null)"
    rsh node1 "id -nG $n" 2>/dev/null | tr ' ' '\n' | grep -qx dctechs || fails "node1: $n not in group dctechs"
  done
  for n in dcaudit1 dcaudit2; do rsh node1 "getent passwd $n" >/dev/null 2>&1 && fails "node1: auditor $n must NOT get an account"; done
  for n in dctech01 dctech02 dctech03 dcaudit1 dcaudit2; do rsh node2 "getent passwd $n" >/dev/null 2>&1 && fails "node2 is not in [racknodes] but has user $n"; done
  rsh node2 "getent group dctechs" >/dev/null 2>&1 && fails "node2 should not even have group dctechs"
else fails "techusers.yml missing in $PD"; fi
report
fi

# ------------------------------------------------------------------ E08
if want 8; then
task E08 "site.yml imports everything; second run is changed=0"
if have_ansible && [[ -f $PD/site.yml ]]; then
  for pb in hwreport bmc logservers sshbanner techusers; do
    grep -qE "(import_playbook|include_playbook).*$pb\.yml" $PD/site.yml || fails "site.yml does not import $pb.yml"
  done
  ap site.yml
  [[ $LAST_RC -eq 0 ]] || fails "first site.yml run failed: $(tail_of)"
  ap site.yml
  [[ $LAST_RC -eq 0 ]] || fails "second site.yml run failed: $(tail_of)"
  recap=$(grep -E '^(node1|node2)[[:space:]]+:' <<<"$LAST")
  [[ $(grep -c . <<<"$recap") -ge 2 ]] || fails "recap does not show both nodes"
  while read -r line; do
    [[ -z "$line" ]] && continue
    grep -q 'changed=0' <<<"$line" || fails "NOT idempotent: $(tr -s ' ' <<<"$line")"
    grep -q 'failed=0' <<<"$line" || fails "failures in recap: $line"
    grep -q 'unreachable=0' <<<"$line" || fails "unreachable host: $line"
  done <<<"$recap"
else fails "site.yml missing in $PD"; fi
report
fi

echo
printf "  Result: %d/%d passed" "$PASS" "$TOTAL"
(( TOTAL > 0 )) && printf "  (%d%%, pass mark 70%%)" $(( PASS*100/TOTAL ))
echo
[[ $FAIL -gt 0 ]] && echo "  Failed: ${FAILED_TASKS[*]}"
echo
[[ $FAIL -eq 0 ]]
