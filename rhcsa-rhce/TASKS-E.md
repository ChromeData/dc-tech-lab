# RHCE (EX294) track - Data Center Operations (Ansible)

Scenario: node1 is the **control node**; you manage the data hall with Ansible.
Managed nodes: `node1` (192.168.56.101, manages itself over ssh) and `node2` (192.168.56.102).
Root ssh keys between them are already in place; `node1`/`node2` resolve via /etc/hosts.
Work in **/root/dclab-ansible** on node1 (it already holds `.vault_pass` and `vars/techs.yml`).
Use only `ansible.builtin` modules (no extra collections are installed).

Grade: `bash /root/dclab-rh/grade-e.sh -v` (one task: `-t 4`). It runs your playbooks for real; a full run takes a few minutes.
Stuck? `HINTS.md`: nudge, then walk me, then show me. Try first.

---

## E01 - Install, ansible.cfg, inventory

**TEACH**
- `dnf install ansible-core` gives `ansible`, `ansible-playbook`, `ansible-vault`, `ansible-inventory`.
- `ansible.cfg` in the current directory is read automatically. `[defaults]` keys: `inventory`, `remote_user`, `host_key_checking`, `vault_password_file`, `roles_path`.
- INI inventory: `[group]` then host names; `[big:children]` lists groups-of-groups; `[group:vars]` sets variables. `ansible-inventory --graph` shows the result; `ansible GROUP -m ping` tests connectivity.

**DO** in `/root/dclab-ansible`:
1. Install `ansible-core`.
2. `ansible.cfg`: inventory `./inventory`, remote user `root`, host key checking off, vault password file `./.vault_pass`, roles path `./roles`.
3. `inventory`: group `logservers` = node2; group `racknodes` = node1; group `dc` containing both groups; for `dc` set `ansible_python_interpreter=/usr/bin/python3`.
4. `ansible dc -m ping` must succeed on both.

## E02 - Ad-hoc commands

**TEACH**
- Ad-hoc form: `ansible PATTERN -m MODULE -a "key=value ..."`. Modules: `file` (`path= state=directory mode= owner=`), `dnf` (`name= state=present`), `command` (`-a uptime`).
- Redirect output to a file with `>` like any command.

**DO** - ad-hoc only, no playbook, against group `dc`:
1. Directory `/etc/dcops`, owner/group root, mode `0750`.
2. Install package `iperf3`.
3. Save the output of `uptime` from both nodes to `/root/uptime-all.txt` on node1.

## E03 - Hardware report from facts

**TEACH**
- Facts are gathered automatically: `ansible_hostname`, `ansible_processor_vcpus`, `ansible_memtotal_mb`, `ansible_devices` (a dict keyed `sda`, `sdb`...; each has `.size`). Inspect with `ansible node2 -m setup -a 'filter=ansible_devices'`.
- The `copy` module with `content: |` writes literal text with `{{ variables }}` filled in.
- `{{ something | default('NONE') }}` supplies a value when something is undefined (e.g. a disk that does not exist).

**DO** - `hwreport.yml` (hosts `dc`) writes `/root/hwreport.txt` on each node with exactly these lines (any order):
`HOSTNAME=`, `CPUS=`, `MEMORY_MB=`, `SDA_SIZE=`, `SDB_SIZE=`, `SDC_SIZE=` (`NONE` if the disk is absent - node2 has no sdc).

## E04 - Vault and a 0600 template

**TEACH**
- `ansible-vault encrypt FILE` encrypts a plaintext vars file (password is read from `vault_password_file`); `ansible-vault view FILE` shows it. Load it in a play with `vars_files:`.
- `template` renders `templates/NAME.j2` to `dest` with `owner`, `group`, `mode`. Add `no_log: true` to hide secrets from output.

**DO**
1. `bmc_creds.yml` containing `bmc_user: ipmiadmin` and `bmc_pass: Gb200-Rack!7`, **vault-encrypted**.
2. `templates/bmc.conf.j2` producing two lines `BMC_USER=...` and `BMC_PASS=...` from the variables (no literal password anywhere in plain text).
3. `bmc.yml` (hosts `dc`) writes `/etc/dcops/bmc.conf`, root:root, mode `0600`.

## E05 - Role `ctlogs`

**TEACH**
- A role is a directory `roles/NAME/` with `tasks/main.yml`, `handlers/main.yml`, `templates/`, `defaults/main.yml` (low-priority variables). `ansible-galaxy init NAME` (run inside `roles/`) creates the skeleton. Apply with `roles: [NAME]` in a play.
- `file` accepts `setype: httpd_sys_content_t` to set the SELinux type. A task's `notify: handler name` fires the handler only when the task changed something.

**DO** - role `ctlogs` + playbook `logservers.yml` (hosts `logservers`). On node2 the role must:
1. Install `httpd`, create `/srv/ctlogs` with SELinux type `httpd_sys_content_t`.
2. Template `/etc/httpd/conf.d/ctlogs.conf` using variable `ctlogs_port` (default 8080 in `defaults/main.yml`): `Listen`, `Alias /logs /srv/ctlogs`, `Require all granted`.
3. Template `/srv/ctlogs/README.txt` that mentions the host (`inventory_hostname`).
4. httpd started and enabled; config change restarts httpd through a **handler**.
Check: `curl http://localhost:8080/logs/README.txt` on node2.

## E06 - Handlers: restart only on change

**TEACH**
- `handlers:` is a play-level section. Handlers run once, at the end, only if a notifying task reported `changed`. A second run of an idempotent play changes nothing - so the handler must not run.
- `lineinfile` with `regexp:` and `line:` ensures exactly one matching line in a file (use `^#?Banner` to also catch the commented default).

**DO** - `sshbanner.yml` (hosts `dc`):
1. `/etc/issue.net` contains `DCOPS AUTHORIZED ACCESS ONLY - all sessions are logged`.
2. `/etc/ssh/sshd_config` has `Banner /etc/issue.net`.
3. sshd is restarted by a handler **only** when either of those changed.
The grader alters the banner file and checks sshd restarts once - and not at all on a clean rerun.

## E07 - Loops and conditionals

**TEACH**
- `vars_files: [vars/techs.yml]` loads a list variable. `loop: "{{ techs }}"` runs a task once per element as `item`; `item.name`, `item.uid`...
- `when: item.role == 'tech'` skips elements. Play targeting `hosts: racknodes` limits it to that group.
- `user` module: `name uid shell groups append`; `group` creates the group first.

**DO** - `techusers.yml` (hosts `racknodes` only):
1. Create group `dctechs`.
2. From `vars/techs.yml`, create only the entries with role `tech`: right name, UID, shell, member of `dctechs`. Auditors get no account.
3. node2 must stay untouched.

## E08 - One site playbook, idempotent

**TEACH**
- `- import_playbook: other.yml` entries in a top-level playbook run other playbooks in order.
- Idempotent = a second run reports `changed=0` for every host in `PLAY RECAP`. `command`/`shell` always report changed unless guarded - prefer real modules.

**DO**
- `site.yml` importing `hwreport.yml`, `bmc.yml`, `logservers.yml`, `sshbanner.yml`, `techusers.yml`.
- Run it twice yourself; the second `PLAY RECAP` must show `changed=0 failed=0` for both nodes.
