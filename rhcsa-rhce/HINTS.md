# Hints - open only the level you need

Levels: **nudge** (one line) -> **walk me** (steps, no exact commands) -> **show me** (full commands).
Say the level out loud before you scroll. Try the task first.

---
# R-track (node1)

## R01
- **nudge:** Three layers: PV, VG, LV. Then filesystem, then fstab.
- **walk me:** Make PVs on both disks; the VG gets only sdb first, then add sdc. Create two LVs. mkfs each with the right type. Create mountpoints. Add fstab lines using each LV's UUID from blkid. Test with mount -a. Finally extend ctlogs with the resize-filesystem flag.
- **show me:**
```
pvcreate /dev/sdb /dev/sdc
vgcreate dcvg /dev/sdb && vgextend dcvg /dev/sdc
lvcreate -n ctlogs -L 4G dcvg ; lvcreate -n scratch -L 2G dcvg
mkfs.xfs /dev/dcvg/ctlogs ; mkfs.ext4 /dev/dcvg/scratch
mkdir -p /srv/ctlogs /var/dcscratch
echo "UUID=$(blkid -s UUID -o value /dev/dcvg/ctlogs) /srv/ctlogs xfs defaults 0 0" >> /etc/fstab
echo "UUID=$(blkid -s UUID -o value /dev/dcvg/scratch) /var/dcscratch ext4 defaults 0 0" >> /etc/fstab
systemctl daemon-reload ; mount -a
lvextend -r -L 7G /dev/dcvg/ctlogs
```

## R02
- **nudge:** One mkdir with two brace groups; find/grep output goes to files with `>`.
- **walk me:** mkdir -p with {01..04} and {bmc,gpu}. find on /opt/dcdata/racks by name and size (+10k). grep recursively with the file filter and no filenames. cp in archive mode. ln -s for the symlink, plain ln for the hard link.
- **show me:**
```
mkdir -p /srv/ctlogs/rack-reports/rack{01..04}/{bmc,gpu}
find /opt/dcdata/racks -name gpu.log -size +10k > /root/big-gpu-logs.txt
grep -rh --include=gpu.log 'fallen off the bus' /opt/dcdata/racks > /root/gpu-lost.txt
cp -a /opt/dcdata/racks/rack04 /srv/ctlogs/rack-reports/rack04/src
ln -s /srv/ctlogs/rack-reports/rack04 /srv/ctlogs/latest
ln /opt/dcdata/racks/rack01/node01/bmc.log /opt/dcdata/rack01-node01-bmc.log
```

## R03
- **nudge:** Supplementary group = `-G`; the leading 2 in 2770 is setgid; ACLs need `-d` for the inherited kind.
- **walk me:** groupadd with fixed GID; useradd with fixed UIDs, -G for the two techs; noc1 without -G; svc-collector with nologin shell. mkdir rma, chgrp, chmod 2770. setfacl twice (normal and default). chage -M -W. One sudoers.d file with a %group rule limited to the ipmitool path; check with visudo -c.
- **show me:**
```
groupadd -g 3000 dcops
useradd -u 3101 -G dcops tech1 ; useradd -u 3102 -G dcops tech2
useradd -u 3201 -s /bin/bash noc1
useradd -u 3001 -s /sbin/nologin svc-collector
mkdir /srv/ctlogs/rma ; chgrp dcops /srv/ctlogs/rma ; chmod 2770 /srv/ctlogs/rma
setfacl -m u:noc1:rx /srv/ctlogs/rma ; setfacl -d -m u:noc1:rx /srv/ctlogs/rma
chage -M 90 -W 7 tech1
echo '%dcops ALL=(root) NOPASSWD: /usr/bin/ipmitool' > /etc/sudoers.d/dcops
chmod 440 /etc/sudoers.d/dcops ; visudo -c
```

## R04
- **nudge:** `dnf provides` for a file you do not have; `rpm -qf` with a query format for one you do.
- **walk me:** Ask dnf which package provides */bin/sensors, install that and ipmitool. Echo the name into the file. For the owner, rpm -qf with --qf printing only the name tag.
- **show me:**
```
dnf provides '*/bin/sensors'
dnf -y install ipmitool lm_sensors
echo lm_sensors > /root/sensors-pkg.txt
rpm -qf /etc/ssh/sshd_config --qf '%{NAME}\n' > /root/sshd-owner.txt
```

## R05
- **nudge:** Killing the PID is pointless - something restarts it. Ask systemd who owns the PID.
- **walk me:** ps sorted by CPU; systemctl status on the PID; record the unit; disable and stop it in one command. For gpu-soak create a drop-in with Nice=10, reload, restart.
- **show me:**
```
ps -eo pid,ni,pcpu,comm --sort=-pcpu | head -3
systemctl status $(pgrep -x gpu-burnin)
echo gpu-burnin.service > /root/runaway-unit.txt
systemctl disable --now gpu-burnin.service
mkdir -p /etc/systemd/system/gpu-soak.service.d
printf '[Service]\nNice=10\n' > /etc/systemd/system/gpu-soak.service.d/nice.conf
systemctl daemon-reload ; systemctl restart gpu-soak
```

## R06
- **nudge:** Fix one fault, read the log again - the next error appears.
- **walk me:** status/journalctl -u shows 217/USER (no such user) - create a system user ctsync with nologin. Next 203/EXEC: the unit points at the wrong directory (bin vs sbin). Then the script lacks the x bit. daemon-reload, enable --now.
- **show me:**
```
journalctl -u ctlog-sync -e
useradd -r -s /sbin/nologin ctsync
sed -i 's#/usr/local/bin/ctlog-sync.sh#/usr/local/sbin/ctlog-sync.sh#' /etc/systemd/system/ctlog-sync.service
chmod 755 /usr/local/sbin/ctlog-sync.sh
systemctl daemon-reload ; systemctl enable --now ctlog-sync.service
```

## R07
- **nudge:** Script first, then a .service, then a .timer with the same base name; enable the timer.
- **walk me:** Script: mkdir -p, tar -czf with date in the name and -C /srv/ctlogs rack-reports; chmod +x. Service: Type=oneshot + ExecStart. Timer: OnCalendar daily 02:15:00, Persistent=true, WantedBy=timers.target. daemon-reload, enable --now the timer, start the service once.
- **show me:**
```
cat > /usr/local/bin/ctlog-archive.sh <<'X'
#!/bin/bash
mkdir -p /var/backups/ctlogs
tar -czf /var/backups/ctlogs/ctlogs-$(date +%F).tar.gz -C /srv/ctlogs rack-reports
X
chmod 755 /usr/local/bin/ctlog-archive.sh
printf '[Unit]\nDescription=Archive DC rack reports\n[Service]\nType=oneshot\nExecStart=/usr/local/bin/ctlog-archive.sh\n' > /etc/systemd/system/ctlog-archive.service
printf '[Unit]\nDescription=Nightly archive\n[Timer]\nOnCalendar=*-*-* 02:15:00\nPersistent=true\n[Install]\nWantedBy=timers.target\n' > /etc/systemd/system/ctlog-archive.timer
systemctl daemon-reload ; systemctl enable --now ctlog-archive.timer
systemctl start ctlog-archive.service ; tar tzf /var/backups/ctlogs/*.tar.gz | head
```

## R08
- **nudge:** awk with `-F'|'`; trim fields; the status is field 3, and don't grep for "ok" - names can contain it.
- **walk me:** Check $1 readable else usage to stderr and exit 2. awk: skip comment/blank lines, trim field 1 and 3, print "name: status" when status != ok and remember it, END exit with that flag.
- **show me:**
```
cat > /usr/local/bin/sdr-triage.sh <<'X'
#!/bin/bash
f=$1
[[ -r $f ]] || { echo "usage: ${0##*/} sdr-file" >&2; exit 2; }
awk -F'|' '
/^[[:space:]]*(#|$)/ { next }
{ n=$1; s=$3; gsub(/^[ \t]+|[ \t]+$/, "", n); gsub(/^[ \t]+|[ \t]+$/, "", s)
  if (s != "ok") { print n ": " s; rc=1 } }
END { exit rc }' "$f"
X
chmod 755 /usr/local/bin/sdr-triage.sh
```

## R09
- **nudge:** Three layers must agree: httpd config, SELinux label, firewall - all persistent.
- **walk me:** dnf install httpd. conf.d file with Listen/Alias/Directory. semanage fcontext + restorecon on /srv/ctlogs. enable --now httpd. firewall-cmd permanent add-port then reload. Test from node2.
- **show me:**
```
dnf -y install httpd
printf 'Listen 8080\nAlias /logs /srv/ctlogs\n<Directory /srv/ctlogs>\n    Require all granted\n</Directory>\n' > /etc/httpd/conf.d/ctlogs.conf
semanage fcontext -a -t httpd_sys_content_t '/srv/ctlogs(/.*)?'
restorecon -R /srv/ctlogs
systemctl enable --now httpd
firewall-cmd --permanent --add-port=8080/tcp ; firewall-cmd --reload
ssh node2 curl -s http://192.168.56.101:8080/logs/
```

## R10
- **nudge:** `nmcli con add type dummy ...` with ipv4.method manual.
- **walk me:** One nmcli con add (type, ifname, con-name, method, address, dns, autoconnect). hostnamectl set-hostname. Append the mapping line to /etc/hosts. Verify with ip a, getent hosts.
- **show me:**
```
nmcli con add type dummy ifname oob0 con-name oob-mgmt ipv4.method manual ipv4.addresses 10.99.0.10/24 ipv4.dns 10.99.0.2 connection.autoconnect yes
hostnamectl set-hostname dcops-node1.dc.example
echo '10.99.0.50 bmc-rack01.oob' >> /etc/hosts
getent hosts bmc-rack01.oob ; ip -br a show oob0
```

## R11
- **nudge:** Drop-in file with [Journal]; then something has to move the journal to disk.
- **walk me:** mkdir journald.conf.d, write Storage and SystemMaxUse under [Journal], restart journald, run journalctl --flush, then journalctl -b -p err to a file.
- **show me:**
```
mkdir -p /etc/systemd/journald.conf.d
printf '[Journal]\nStorage=persistent\nSystemMaxUse=200M\n' > /etc/systemd/journald.conf.d/dc.conf
systemctl restart systemd-journald ; journalctl --flush
journalctl -b -p err --no-pager > /root/boot-errors.txt
ls /var/log/journal/*/
```

---
# E-track (node1, in /root/dclab-ansible)

## E01
- **nudge:** Everything relative to the project dir; ansible.cfg is read from cwd.
- **walk me:** dnf install; write ansible.cfg [defaults] with five keys; inventory with two groups, a children group and a vars section; test with ansible-inventory --graph and ping.
- **show me:**
```
dnf -y install ansible-core ; cd /root/dclab-ansible
printf '[defaults]\ninventory = ./inventory\nremote_user = root\nhost_key_checking = False\nvault_password_file = ./.vault_pass\nroles_path = ./roles\n' > ansible.cfg
printf '[logservers]\nnode2\n\n[racknodes]\nnode1\n\n[dc:children]\nlogservers\nracknodes\n\n[dc:vars]\nansible_python_interpreter=/usr/bin/python3\n' > inventory
ansible-inventory --graph ; ansible dc -m ping
```

## E02
- **nudge:** Three one-liners: file, dnf, command.
- **walk me:** file module with state directory, mode, owner, group. dnf with name and state present. command module running uptime, redirect to the file.
- **show me:**
```
ansible dc -m file -a "path=/etc/dcops state=directory mode=0750 owner=root group=root"
ansible dc -m dnf -a "name=iperf3 state=present"
ansible dc -m command -a uptime > /root/uptime-all.txt
```

## E03
- **nudge:** `ansible_devices.sdc.size | default('NONE')`.
- **walk me:** One play, hosts dc, one copy task with content block of six KEY={{ fact }} lines; disks use default filter.
- **show me:**
```
---
- hosts: dc
  tasks:
    - ansible.builtin.copy:
        dest: /root/hwreport.txt
        content: |
          HOSTNAME={{ ansible_hostname }}
          CPUS={{ ansible_processor_vcpus }}
          MEMORY_MB={{ ansible_memtotal_mb }}
          SDA_SIZE={{ ansible_devices.sda.size | default('NONE') }}
          SDB_SIZE={{ ansible_devices.sdb.size | default('NONE') }}
          SDC_SIZE={{ ansible_devices.sdc.size | default('NONE') }}
```

## E04
- **nudge:** Write the plain vars file, then encrypt it - the password file is already in ansible.cfg.
- **walk me:** Create bmc_creds.yml with two vars; ansible-vault encrypt. Template with two lines. Playbook: vars_files for the vault file; template task with owner/group/mode 0600 and no_log.
- **show me:**
```
printf 'bmc_user: ipmiadmin\nbmc_pass: Gb200-Rack!7\n' > bmc_creds.yml ; ansible-vault encrypt bmc_creds.yml
mkdir -p templates ; printf 'BMC_USER={{ bmc_user }}\nBMC_PASS={{ bmc_pass }}\n' > templates/bmc.conf.j2
# bmc.yml
- hosts: dc
  vars_files: [bmc_creds.yml]
  tasks:
    - ansible.builtin.file: {path: /etc/dcops, state: directory, mode: "0750"}
    - ansible.builtin.template: {src: bmc.conf.j2, dest: /etc/dcops/bmc.conf, owner: root, group: root, mode: "0600"}
      no_log: true
```

## E05
- **nudge:** Skeleton first (`ansible-galaxy init`), then fill tasks/handlers/templates/defaults.
- **walk me:** defaults: ctlogs_port and ctlogs_root. Tasks: dnf httpd; file dir with setype; template conf (notify); template README; service started+enabled. Handler: restart httpd. logservers.yml: hosts logservers, roles ctlogs.
- **show me:**
```
# tasks/main.yml
- ansible.builtin.dnf: {name: httpd, state: present}
- ansible.builtin.file: {path: "{{ ctlogs_root }}", state: directory, mode: "0755", setype: httpd_sys_content_t}
- ansible.builtin.template: {src: ctlogs.conf.j2, dest: /etc/httpd/conf.d/ctlogs.conf}
  notify: restart httpd
- ansible.builtin.template: {src: README.txt.j2, dest: "{{ ctlogs_root }}/README.txt", setype: httpd_sys_content_t}
- ansible.builtin.service: {name: httpd, state: started, enabled: true}
# handlers/main.yml
- name: restart httpd
  ansible.builtin.service: {name: httpd, state: restarted}
# defaults/main.yml
ctlogs_port: 8080
ctlogs_root: /srv/ctlogs
# templates/ctlogs.conf.j2:  Listen {{ ctlogs_port }} / Alias /logs {{ ctlogs_root }} / <Directory ...> Require all granted </Directory>
# templates/README.txt.j2:   CT logs served by {{ inventory_hostname }}
# logservers.yml
- hosts: logservers
  roles: [ctlogs]
```

## E06
- **nudge:** Both tasks notify the same handler; handlers sit at play level.
- **walk me:** copy task for /etc/issue.net, lineinfile task for Banner; each with notify; handlers section with service name sshd state restarted.
- **show me:**
```
- hosts: dc
  tasks:
    - ansible.builtin.copy:
        dest: /etc/issue.net
        content: "DCOPS AUTHORIZED ACCESS ONLY - all sessions are logged\n"
      notify: restart sshd
    - ansible.builtin.lineinfile:
        path: /etc/ssh/sshd_config
        regexp: '^#?Banner'
        line: Banner /etc/issue.net
      notify: restart sshd
  handlers:
    - name: restart sshd
      ansible.builtin.service: {name: sshd, state: restarted}
```

## E07
- **nudge:** `loop` + `when`, play limited to racknodes.
- **walk me:** vars_files; group task; user task looping over techs with when role equals tech; groups dctechs with append.
- **show me:**
```
- hosts: racknodes
  vars_files: [vars/techs.yml]
  tasks:
    - ansible.builtin.group: {name: dctechs}
    - ansible.builtin.user:
        name: "{{ item.name }}"
        uid: "{{ item.uid }}"
        shell: "{{ item.shell }}"
        groups: dctechs
        append: true
      loop: "{{ techs }}"
      when: item.role == 'tech'
```

## E08
- **nudge:** Five import_playbook lines; then run it twice and read PLAY RECAP.
- **walk me:** site.yml with the five imports in order. Run, run again; any changed>0 on run two means a non-idempotent task - fix that module use.
- **show me:**
```
printf -- '---\n- import_playbook: hwreport.yml\n- import_playbook: bmc.yml\n- import_playbook: logservers.yml\n- import_playbook: sshbanner.yml\n- import_playbook: techusers.yml\n' > site.yml
ansible-playbook site.yml ; ansible-playbook site.yml
```
