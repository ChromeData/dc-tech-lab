#!/usr/bin/env bash
#
# DC-tech RHCSA/RHCE lab - environment setup (node1). Idempotent.
# Plants: the rack log tree, sample SDR files, a runaway service, a broken unit,
# the Ansible project skeleton (vault password + tech vars), hosts entries, ssh key.
# Run once, as root, BEFORE taking the dc-lab-clean snapshot.
#
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "run as root"; exit 1; }

# ---------------------------------------------------------------- hosts / ssh
sed -i '/# dclab/d' /etc/hosts
cat >> /etc/hosts <<'EOF'
192.168.56.101 node1 # dclab
192.168.56.102 node2 # dclab
EOF

mkdir -p /root/.ssh && chmod 700 /root/.ssh
[[ -f /root/.ssh/id_ed25519 ]] || ssh-keygen -q -t ed25519 -N "" -f /root/.ssh/id_ed25519 -C "root@dclab-control"
grep -qF "$(cat /root/.ssh/id_ed25519.pub)" /root/.ssh/authorized_keys 2>/dev/null \
  || cat /root/.ssh/id_ed25519.pub >> /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys

# ------------------------------------------------------------- rack log tree
# /opt/dcdata/racks/rackNN/nodeNN/{bmc.log,gpu.log,dmesg.txt}  (deterministic)
rm -rf /opt/dcdata/racks
mkdir -p /opt/dcdata
for r in 01 02 03 04; do
  for n in 01 02 03; do
    d=/opt/dcdata/racks/rack$r/node$n
    mkdir -p "$d"
    R=$((10#$r)); N=$((10#$n))
    # gpu.log: size grows with rack/node so some files are > 10 KiB and some are not
    lines=$(( 35*R*N + 40*R ))
    : > "$d/gpu.log"
    for ((i=1;i<=lines;i++)); do
      case $(( (i*R + N) % 9 )) in
        0) echo "2026-11-0$((i%9+1))T0$((i%10)):1$((i%6)):0$((i%10)) gpu$((i%4)) NVRM: Xid (PCI:0000:$((i%8))b:00): 79, GPU has fallen off the bus" ;;
        1) echo "2026-11-0$((i%9+1))T0$((i%10)):2$((i%6)):1$((i%10)) gpu$((i%4)) NVRM: Xid (PCI:0000:$((i%8))b:00): 63, ECC page retirement recorded" ;;
        *) echo "2026-11-0$((i%9+1))T0$((i%10)):3$((i%6)):2$((i%10)) gpu$((i%4)) nvidia-smi: temp=$((60+i%25))C power=$((300+i%200))W util=$((i%100))%" ;;
      esac
    done >> "$d/gpu.log"
    for ((i=1;i<=12*N;i++)); do
      echo "2026-11-0$((i%9+1)) bmc rack$r/node$n SEL: event $i $( ((i%5==0)) && echo 'Power Supply Failure asserted' || echo 'Temperature normal')"
    done > "$d/bmc.log"
    echo "[    0.000000] Linux version 5.14.0 rack$r node$n" > "$d/dmesg.txt"
    touch -d "2026-11-0$((R+1)) 0$N:00:00" "$d"/*
  done
done

# ------------------------------------------------------------ sample SDR files
mkdir -p /opt/dcdata/sdr
cat > /opt/dcdata/sdr/gb200-rack01-node01.sdr <<'EOF'
# ipmitool sdr elist  --  rack01 / node01
Inlet Temp       | 04h | ok  |  7.1 | 24 degrees C
Exhaust Temp     | 05h | ok  |  7.1 | 38 degrees C
CPU1 Temp        | 01h | ok  |  3.1 | 52 degrees C
CPU2 Temp        | 02h | ok  |  3.2 | 54 degrees C
GPU0 Temp        | 10h | ok  | 41.0 | 61 degrees C
GPU1 Temp        | 11h | nc  | 41.1 | 84 degrees C
GPU2 Temp        | 12h | ok  | 41.2 | 63 degrees C
GPU3 Temp        | 13h | ok  | 41.3 | 60 degrees C
Fan1             | 30h | ok  | 29.1 | 8400 RPM
Fan2             | 31h | cr  | 29.2 | 0 RPM
PSU1 Status      | 50h | ok  | 10.1 | Presence detected
PSU2 Status      | 51h | ns  | 10.2 | No Reading
Pwr Consumption  | 60h | ok  | 11.0 | 5320 Watts
EOF
cat > /opt/dcdata/sdr/gb200-rack02-node02.sdr <<'EOF'
# ipmitool sdr elist  --  rack02 / node02  (healthy)
Inlet Temp       | 04h | ok  |  7.1 | 22 degrees C
CPU1 Temp        | 01h | ok  |  3.1 | 49 degrees C
GPU0 Temp        | 10h | ok  | 41.0 | 58 degrees C
GPU1 Temp        | 11h | ok  | 41.1 | 59 degrees C
Fan1             | 30h | ok  | 29.1 | 8200 RPM
PSU1 Status      | 50h | ok  | 10.1 | Presence detected
PSU2 Status      | 51h | ok  | 10.2 | Presence detected
EOF
cat > /opt/dcdata/sdr/gb200-rack03-node01.sdr <<'EOF'
# ipmitool sdr elist  --  rack03 / node01
Inlet Temp       | 04h | ok  |  7.1 | 23 degrees C
Memory Temp      | 07h | nr  |  8.1 | 105 degrees C

NVLink Switch    | 22h | ok  | 40.1 | Presence detected
Fan3             | 32h | lnc | 29.3 | 2100 RPM
PSU1 Status      | 50h | ok  | 10.1 | Presence detected
Drive Slot 0     | 70h | cr  | 26.0 | Drive Fault
EOF

# ------------------------------------------------- runaway + soak services (R05)
mkdir -p /usr/local/lib/dclab
printf '#!/bin/bash\nwhile :; do :; done\n' > /usr/local/lib/dclab/gpu-burnin
printf '#!/bin/bash\nwhile :; do sleep 5; done\n' > /usr/local/lib/dclab/gpu-soak
chmod 755 /usr/local/lib/dclab/gpu-burnin /usr/local/lib/dclab/gpu-soak
cat > /etc/systemd/system/gpu-burnin.service <<'EOF'
[Unit]
Description=GPU burn-in harness (left running by a previous shift)
[Service]
ExecStart=/usr/local/lib/dclab/gpu-burnin
CPUQuota=35%
Restart=always
RestartSec=2
[Install]
WantedBy=multi-user.target
EOF
cat > /etc/systemd/system/gpu-soak.service <<'EOF'
[Unit]
Description=GPU soak monitor (legitimate, keep running)
[Service]
ExecStart=/usr/local/lib/dclab/gpu-soak
Restart=on-failure
[Install]
WantedBy=multi-user.target
EOF

# ------------------------------------------------------ broken ctlog-sync (R06)
cat > /usr/local/sbin/ctlog-sync.sh <<'EOF'
#!/bin/bash
# DC log sync stub: records a heartbeat so NOC knows the collector ran.
mkdir -p /var/lib/ctlog-sync
echo "ctlog-sync ok $(date -Is)" > /var/lib/ctlog-sync/last-sync
EOF
chmod 644 /usr/local/sbin/ctlog-sync.sh          # deliberately NOT executable
cat > /etc/systemd/system/ctlog-sync.service <<'EOF'
[Unit]
Description=DC CT log sync
After=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
User=ctsync
StateDirectory=ctlog-sync
ExecStart=/usr/local/bin/ctlog-sync.sh

[Install]
WantedBy=multi-user.target
EOF
id ctsync >/dev/null 2>&1 && userdel ctsync || true

systemctl daemon-reload
systemctl enable gpu-burnin.service gpu-soak.service >/dev/null 2>&1

# ------------------------------------------------ ansible project skeleton (E)
mkdir -p /root/dclab-ansible/vars
printf 'Dcops!2026\n' > /root/dclab-ansible/.vault_pass
chmod 600 /root/dclab-ansible/.vault_pass
cat > /root/dclab-ansible/vars/techs.yml <<'EOF'
---
# Rack techs and auditors. Only role "tech" gets an account.
techs:
  - { name: dctech01, uid: 4101, shell: /bin/bash,     role: tech }
  - { name: dctech02, uid: 4102, shell: /bin/bash,     role: tech }
  - { name: dctech03, uid: 4103, shell: /sbin/nologin, role: tech }
  - { name: dcaudit1, uid: 4201, shell: /bin/bash,     role: auditor }
  - { name: dcaudit2, uid: 4202, shell: /bin/bash,     role: auditor }
EOF

# --------------------------------------------------------------- misc
mkdir -p /var/lib/dclab
rm -f /root/big-gpu-logs.txt /root/xid-events.txt
chmod 755 /root/dclab-rh/*.sh 2>/dev/null || true
echo "dclab setup done on $(hostname)"
