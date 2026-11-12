# DC-tech RHCSA + RHCE track

Data-center-themed practice on the Rocky 9.8 VMs `rhcsa-node1` / `rhcsa-node2`
(GPU-server log collector scenario). 11 RHCSA tasks (R01-R11) + 8 RHCE tasks (E01-E08).

**Start:** `.\START-RH.ps1` (headless boot, waits for ssh). `-Fresh` restores snapshot `dc-lab-clean` first.

**ssh:** `ssh -i <lab key> -p 2201 root@127.0.0.1` (node2 = port 2202). `START-RH.ps1` prints the exact command.
The key is looked up at `..\..\rhcsa-lab\.ssh\lab_key`; set `$env:RHCSA_LAB_KEY` to use another one.

**You need:** two Rocky 9 VMs in VirtualBox named `rhcsa-node1` and `rhcsa-node2`, root ssh on
127.0.0.1:2201 and :2202 with that key. `provision.ps1` installs the tasks and graders onto them; take a
snapshot called `dc-lab-clean` afterwards.

**Work:** on node1 read `/root/dclab-rh/TASKS-R.md` and `TASKS-E.md` (copies are in this folder).
Each task = TEACH facts, then DO steps. Hints in `HINTS.md`: nudge, walk me, show me.
Ansible project dir: `/root/dclab-ansible`.

**Grade (on node1):**
```
bash /root/dclab-rh/grade-r.sh -v      # -t 5 = one task
bash /root/dclab-rh/grade-e.sh -v      # runs your playbooks; takes minutes
```
Grade, `reboot`, grade the R-track again - the second run counts.

**Reset:** `.\START-RH.ps1 -Fresh`. Power off when done: `VBoxManage controlvm rhcsa-node1 acpipowerbutton` (same for node2).

Maintainer files: `setup.sh` (plants the scenario), `provision.ps1` (installs everything onto clean-install nodes before snapshotting).
