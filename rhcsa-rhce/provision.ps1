<#
.SYNOPSIS
    MAINTAINER SCRIPT. Installs the DC-tech RHCSA/RHCE lab onto running nodes.
    You do NOT need this to practise - dc-lab-clean already contains everything.

.DESCRIPTION
    Copies setup/graders/tasks to node1:/root/dclab-rh/, runs setup.sh, then wires
    node1's ssh key into node1 and node2 (the Ansible control-node trust) and adds
    the node1/node2 hosts entries on node2. Run it on clean-install nodes, then shut
    down and snapshot dc-lab-clean.
#>
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$key  = if ($env:RHCSA_LAB_KEY) { $env:RHCSA_LAB_KEY } else { [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..\rhcsa-lab\.ssh\lab_key')) }
$so   = @('-i', $key, '-o', 'StrictHostKeyChecking=no', '-o', "UserKnownHostsFile=$env:TEMP/dclab_known_hosts", '-o', 'BatchMode=yes', '-o', 'LogLevel=ERROR')
function S1 { ssh @so -p 2201 root@127.0.0.1 @args }
function S2 { ssh @so -p 2202 root@127.0.0.1 @args }

S1 'mkdir -p /root/dclab-rh'
foreach ($f in 'setup.sh','grade-r.sh','grade-e.sh','TASKS-R.md','TASKS-E.md','HINTS.md') {
    scp @so -P 2201 (Join-Path $here $f) "root@127.0.0.1:/root/dclab-rh/$f"
}
S1 "sed -i 's/\r$//' /root/dclab-rh/*.sh /root/dclab-rh/*.md; chmod 755 /root/dclab-rh/*.sh; bash /root/dclab-rh/setup.sh"

# node1 control key -> node2 (and node1 itself, done by setup.sh)
$pub = (S1 'cat /root/.ssh/id_ed25519.pub').Trim()
S2 "mkdir -p /root/.ssh; chmod 700 /root/.ssh; grep -qF '$pub' /root/.ssh/authorized_keys 2>/dev/null || echo '$pub' >> /root/.ssh/authorized_keys; chmod 600 /root/.ssh/authorized_keys; sed -i '/# dclab/d' /etc/hosts; printf '192.168.56.101 node1 # dclab\n192.168.56.102 node2 # dclab\n' >> /etc/hosts"
S1 'ssh -o StrictHostKeyChecking=no -o BatchMode=yes node2 hostname; ssh -o StrictHostKeyChecking=no -o BatchMode=yes node1 hostname; rm -f /root/.ssh/known_hosts'
Write-Host "provisioned. Now: shut both nodes down cleanly and take snapshot dc-lab-clean." -ForegroundColor Green
