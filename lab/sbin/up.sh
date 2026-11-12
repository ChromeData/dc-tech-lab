#!/bin/bash
# Run as root by START-DCLAB.ps1: BMC IP aliases on lo, TLS cert, and the fake BMC web service.
set -e
U=${1:?usage: up.sh <linux-user>}
H=$(getent passwd "$U" | cut -d: -f6)
LAB="$H/dclab"
for i in $(seq 11 28); do ip addr add 192.168.8.$i/32 dev lo 2>/dev/null || true; done
for i in 11 12 13; do ip addr add 192.168.9.$i/32 dev lo 2>/dev/null || true; done
mkdir -p /var/lib/dclab
if [ ! -f /var/lib/dclab/bmc.crt ]; then
  openssl req -x509 -newkey rsa:2048 -nodes -keyout /var/lib/dclab/bmc.key -out /var/lib/dclab/bmc.crt \
    -days 3650 -subj "/CN=dclab-bmc" >/dev/null 2>&1
fi
systemctl stop dclab-bmcd 2>/dev/null || true
systemctl reset-failed dclab-bmcd 2>/dev/null || true
chown -R "$U": "$LAB"
systemd-run --quiet --unit=dclab-bmcd --setenv=DCLAB_HOME="$LAB" --setenv=PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 "$LAB/lib/bmcd.py"
sleep 1
systemctl is-active dclab-bmcd
