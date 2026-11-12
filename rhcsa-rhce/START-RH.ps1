<#
.SYNOPSIS
    Starts the DC-tech RHCSA + RHCE practice nodes (headless) and waits for ssh.
.EXAMPLE
    .\START-RH.ps1
    .\START-RH.ps1 -Fresh     # restore snapshot dc-lab-clean first (wipes all your work)
#>
[CmdletBinding()]
param([switch]$Fresh)

$vbm = 'C:\Program Files\Oracle\VirtualBox\VBoxManage.exe'
$key = if ($env:RHCSA_LAB_KEY) { $env:RHCSA_LAB_KEY } else { [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..\rhcsa-lab\.ssh\lab_key')) }
$nodes = @{ 'rhcsa-node1' = 2201; 'rhcsa-node2' = 2202 }
function State { param($vm)
  ((& $vbm showvminfo $vm --machinereadable 2>$null | Select-String '^VMState=') -replace 'VMState=','' -replace '"','').Trim() }

if ($Fresh) {
    Write-Host "`nRestoring dc-lab-clean on both nodes..." -ForegroundColor Yellow
    foreach ($vm in $nodes.Keys) {
        if ((State $vm) -ne 'poweroff') { & $vbm controlvm $vm poweroff 2>&1 | Out-Null; Start-Sleep 4 }
        & $vbm snapshot $vm restore dc-lab-clean 2>&1 | Out-Null
        Write-Host "  $vm reset" -ForegroundColor DarkGray
    }
}
foreach ($vm in $nodes.Keys) {
    if ((State $vm) -ne 'running') { & $vbm startvm $vm --type headless 2>&1 | Out-Null }
    Write-Host "  $vm starting" -ForegroundColor DarkGray
}
foreach ($port in $nodes.Values) {
    $ok = $false
    for ($i = 0; $i -lt 60 -and -not $ok; $i++) {
        ssh -i $key -p $port -o StrictHostKeyChecking=no -o UserKnownHostsFile="$env:TEMP/dclab_known_hosts" -o BatchMode=yes -o ConnectTimeout=5 -o LogLevel=ERROR root@127.0.0.1 true 2>$null
        if ($LASTEXITCODE -eq 0) { $ok = $true } else { Start-Sleep 5 }
    }
    if (-not $ok) { Write-Host "  port $port: ssh did not come up" -ForegroundColor Red }
}
Write-Host @"

=== DC-TECH RHCSA + RHCE LAB READY ===

  Connect with the lab key:
    ssh -i "$key" -p 2201 root@127.0.0.1      # node1 (work here)
    ssh -i "$key" -p 2202 root@127.0.0.1      # node2

  On node1:
    cat /root/dclab-rh/TASKS-R.md             # RHCSA track  (R01-R11)
    cat /root/dclab-rh/TASKS-E.md             # RHCE track   (E01-E08)
    bash /root/dclab-rh/grade-r.sh -v         # then REBOOT and grade again
    bash /root/dclab-rh/grade-e.sh -v
    hints: /root/dclab-rh/HINTS.md (nudge -> walk me -> show me)

"@ -ForegroundColor Cyan
