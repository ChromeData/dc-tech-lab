# START-DCLAB.ps1 : install/update the lab in WSL, start it, open it in your browser.
#   .\START-DCLAB.ps1              start + open the lab page (3D hall, two terminals, quiz)
#   .\START-DCLAB.ps1 -Terminals   also open two classic terminal windows
#   .\START-DCLAB.ps1 -NoOpen      start only (no browser)
param([switch]$Terminals, [switch]$NoOpen, [switch]$NoTerminal, [string]$Distro = "Ubuntu")
$ErrorActionPreference = "Stop"

$src   = Join-Path $PSScriptRoot "lab"
$user  = (wsl -d $Distro -e whoami).Trim()
$lhome = (wsl -d $Distro -e bash -c 'echo $HOME').Trim()
$wsrc  = (wsl -d $Distro -e wslpath -a "$src").Trim()

Write-Host "Installing lab into WSL ($Distro) at $lhome/dclab ..."
wsl -d $Distro -e bash -c "mkdir -p ~/dclab/state ~/dclab/work && cp -r '$wsrc/.' ~/dclab/ && chmod +x ~/dclab/bin/* ~/dclab/sbin/* && find ~/dclab -maxdepth 2 \( -name '*.py' -o -name '*.sh' -o -name dclabrc \) | xargs sed -i 's/\r$//'"

# The web server runs inside a hidden WSL session. That session also keeps WSL from shutting the
# lab down while you work (WSL stops a distro when nothing is attached to it).
wsl -d $Distro -e bash -c "pkill -f 'dclab/lib/webd.py' 2>/dev/null; true"
Start-Process wsl.exe -WindowStyle Hidden -ArgumentList "-d $Distro -e bash -lc `"python3 ~/dclab/lib/webd.py >> ~/dclab/state/web.log 2>&1`""
Start-Sleep -Seconds 2

Write-Host "Starting the simulated BMC web service (as root in WSL) ..."
$state = (wsl -d $Distro -u root -e bash "$lhome/dclab/sbin/up.sh" $user | Select-Object -Last 1)
Write-Host "  BMC service: $state"

$url = (wsl -d $Distro -e bash -lc "~/dclab/bin/dclab web").Trim()
Write-Host "Lab page: $url"
if (-not $NoOpen -and -not $NoTerminal) { Start-Process $url }

if ($Terminals) {
    $cmd = "wsl.exe -d $Distro --cd ~ -- bash --rcfile $lhome/dclab/dclabrc -i"
    if (Get-Command wt.exe -ErrorAction SilentlyContinue) {
        Start-Process wt.exe -ArgumentList "-w new nt --title `"DC Lab 1`" $cmd ; nt --title `"DC Lab 2`" $cmd"
    } else {
        Start-Process wsl.exe -ArgumentList "-d $Distro --cd ~ -- bash --rcfile $lhome/dclab/dclabrc -i"
    }
}
