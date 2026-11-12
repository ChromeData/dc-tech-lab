"""Teach cards and drill questions. `slides` topics come from the class notes; `gap` topics fill the postings."""
from core import SITE_NAME

# topic -> (title, [facts])
LEARN = {
    "tags": ("Where the service tags are", [
        "IR7000 rack: back of the rack in the right corner, or top center, or front right corner (newer racks).",
        "Compute tray: luggage tag near the BMC port.",
        "NVLink switch: bottom of the luggage tag, bottom right (N5200) or right side (N5600).",
        "Cable cartridge: left side, middle and top and bottom. Use the NVIDIA SN.",
        "Power trays, power inverters, power capacitance tray: back right side near the bus bar "
        "(capacitance tray can be on the right side).",
    ]),
    "arch": ("GB200 NVL72 architecture", [
        "1 rack = 1 solution. 18 compute trays.",
        "Each compute tray has 2 Bianca boards. Each Bianca board has 2 GPUs. So 4 GPUs per tray x 18 trays = 72.",
        "9 NVLink switch trays. 2 ASICs per tray, so 9 physical switches make 18 logical switches.",
        "144 ACP links run through the cable cartridges. ACP# = access port number.",
        "The cable cartridges are the rack's internal plug-and-play network.",
    ]),
    "safety": ("Considerations when troubleshooting", [
        "Hard power off (holding the power button) or pulling a CT in a rack running production breaks the "
        "NVLink fabric and might need a manual restart of the job.",
        "Even a CT that is not in the job still belongs to the internal fabric.",
        "Do a graceful shutdown: ACPI shutdown in the GB200 power options in the BMC (IPMI: chassis power soft).",
        "One NVLink switch offline will halt production on the whole rack.",
        "Switches must be factory reset before going into production racks, else ZTP will fail.",
        "Switch 1 is the primary or master switch.",
    ]),
    "firmware": ("Firmware", [
        f"Firmware matrix at {SITE_NAME} (GB200): 1.3.6 in all data halls, but 26.01.10001500 for the BMC.",
        "Once a CT is on the 1.3.6 package it CAN NOT be downgraded.",
        "Update order: BMC (10 to 15 min), then BIOS (roughly 15 min), then Bianca (45 min to 1 h 30 min).",
        "The CT should be powered off for each update.",
        "Leak alarms: the BMC needs to be above 25.09.30001500. BlueField-3 PXE: firmware v1.3 or above.",
    ]),
    "fru": ("FRU parts for the compute tray", [
        "The whole CT, M.2 riser/drive, NVMe drives, backplane, control panel, OSFP headers, LOM.",
        "BMC (run fixBMC.sh before powering on the CT), HMC, PDB / PDB heatsink, IPEX (GB200 only).",
        "BlueField-3, fans, various cables, CMOS battery. Bianca boards are a FRU only on GB300 MaxQ.",
    ]),
    "layout": ("Compute tray layout (XE9712)", [
        "Front: BlueField-3, OSFP headers, LOM port, drive slots.",
        "Drive slots 0 to 3 are the only ones usable in the base configuration. Slots 4 to 7 need another "
        "BF3 or a PSB installed.",
        "Inside: HMC, TPM, M.2 riser/drive, fans, IPEX, interposer board and BMC, PDB, OSFP header, front IO "
        "board, BlueField-3. Also: backplanes, GPUs, CPU/memory, CX7/8 mezz.",
    ]),
    "console": ("Getting a console", [
        "SOL from WSL: ipmitool -H <BMC_IP> -U admin -P admin -I lanplus sol activate. Deactivate from another "
        "window with sol deactivate.",
        "Paste with ctrl+v or right-click. F2 = BIOS, F11 = Boot Override Menu. It keeps you in one window.",
        "USB to Micro-USB cable with PuTTY: each CT is its own serial device (find the COM port in Device "
        "Manager). Serial line = COM#, speed = 115200. Right-click pastes.",
        "BMC virtual console: finicky and tends to disconnect. DisplayPort: unreliable, worse with the "
        "StarTech KVM.",
        "SOL and USB serial are reliable, work in BIOS and text live images, show the complete POST and Linux "
        "boot, and the text can be saved with `script <file>.txt` (type exit to stop).",
        "Downside of SOL: wait 3 to 5 minutes after unplugging for the session to end, or run sol deactivate.",
    ]),
    "post": ("POST", [
        "If nothing is found to boot from PXE, the system boots to an EFI shell. This is normal.",
        "A CT sitting at the EFI Shell prompt has completed POST. It does not rule out PXE issues.",
        "Type `exit` to leave the shell and attempt the boot again.",
        "Plug in a USB flash drive before typing exit and it boots from the USB drive. No restart needed.",
    ]),
    "logs": ("Log collection", [
        "Collect logs whenever you work on a CT.",
        "BIOS POST output: from your SOL session.",
        "SEL: ipmitool -I lanplus -H <BMC_IP> -U admin -P admin sel -v list | tee -a <ServiceTag>-sel.txt",
        "SDR: ipmitool -I lanplus -H <BMC_IP> -U admin -P admin sdr elist | tee -a <ServiceTag>-sdr.txt",
        "HMC: curl -k -u 'admin:admin' https://<BMC_IP>/redfish/v1/Systems/HGX_Baseboard_0/LogServices/"
        "EventLog/Entries | jq | tee -a <ServiceTag>-HMCevents.txt",
        "ezBMC captures all of these and more.",
    ]),
    "nopower": ("No power", [
        "Causes: voltage errors, leak detection errors, HMC, PDB.",
        "Voltage errors: internal busbar not torqued properly. Open the CT, get down to the busbar, loosen all "
        "the screws, re-torque to 20 in-lb in the order back, front, middle.",
        "HMC: reseat the slimline cables and the card.",
        "PDB: inspect and gather logs. HMC logs will show errors.",
    ]),
    "leak": ("Leak detection errors", [
        "Leak errors prevent power on. Drives flash amber but the system powers off. The CT shows some boot, "
        "then stops.",
        "Leak sensors read OK from 1.70 to 1.75 volts.",
        "Ch0LeaDet0ColPla = M0_0, Cha0LeaDete0Mani = M0_1, Ch0LeaDet1ColPla = M1_0, Cha0LeaDete1Mani = M1_1.",
        "Fix order: verify the BMC revision is above 25.09.30001500, check with a UV light (no coolant), "
        "clean the leak sensors. If a sensor touches the cold plate, use a zip tie.",
    ]),
    "pci": ("PCI errors, ConnectX and BlueField-3", [
        "The HMC log shows PCI errors for the CX7/8 mezzanine, BlueField-3 and GPUs. Collect ezBMC logs, or "
        "the HMC log if that is all that is requested.",
        "CX-7/8 (RoCE): OSFP cables to the mezz not seated. Tension bar not torqued, foam pad not in place, "
        "bent pins on the OSFP header cable. Or cables on the wrong mezz port. Check the OSFP header power cables.",
        "BF3 PXE fails and the port shows in BIOS and mlxlink_info: update BF3 firmware to v1.3 or above.",
        "BF3 not in BIOS or mlxlink_info: pull the HMC log; support checks PCI errors and sends parts or a new POA.",
    ]),
    "swap": ("CT swaps and the RMA process", [
        "Sometimes the CT cannot be fixed: Bianca board issues (GPUs, memory, CPUs, CX7/8 mezz) after all "
        "troubleshooting steps.",
        "If the CT is in production and healthy CTs are in the hospital, move it from the production rack to "
        "the hospital for the next POAs or replacement.",
        "Support opens a 'Part Only' work order and ships a replacement CT.",
        "Move from the defective CT to the replacement: handles, rails, drives (internal drive and front "
        "drives). Then submit the swap form.",
    ]),
    "diag": ("CT diagnostics", [
        "Support Live Image (bootable): the Valet script auto-runs, 5 to 10 minutes.",
        "Mellanox mlxlink_info log: state and health of the network ports.",
        "NVIDIA bug report: GPU health at a snapshot level. Remapped rows and ECC errors.",
        "NVIDIA Field Diagnostics (also known as 629): a detailed check of the GPUs. A little over 3 hours.",
        "ezBMC: installed in WSL as a global utility. 3 to 5 minutes. Gathers HMC, SEL, SDR, firmware. Makes a "
        "zip in the ezBMC_Logs folder in the WSL home directory, with a viewer inside.",
        "nvdebug.sh: similar to a TSR. Collects in-band (OS) and out-of-band (BMC and HMC) logs. It does not "
        "replace an NVIDIA bug report.",
    ]),
    "fiber": ("Fiber and optics (gap fill)", [
        "Inspect, clean, inspect. Never plug in an uninspected connector. Never look into a live fiber.",
        "Single-mode OS2 jacket: yellow. Multimode OM3/OM4: aqua.",
        "DOM light levels are in dBm (log scale). More negative means less light.",
        "Label both ends of every cable run before you move on.",
    ]),
    "power": ("Power and cooling (gap fill)", [
        "Three-phase: P = 1.732 x V x I x PF.",
        "Breakers carry 80% of their rating as continuous load.",
        "A and B feeds: each one must carry the whole rack alone.",
        "1 W = 3.412 BTU/hr. Cold plates move heat to the CDU; the rest goes to room air.",
    ]),
    "ops": ("Operations (gap fill)", [
        "MTTD = average of (detected - fault start). MTTR = average of (repaired - detected).",
        "Receiving is a three-way match: PO, packing slip, physical scan.",
        "Min/max spares: reorder below min, order up to max.",
        "An SOP has Purpose, Scope, Safety, Tools, Procedure, Verification, Records.",
    ]),
}

# (topic, question, answer shown after, [key groups]; each group = alternatives separated by |)
CARDS = [
    ("arch", "How many GPUs are on one Bianca board?", "2", ["2|two"]),
    ("arch", "How many Bianca boards are in one compute tray?", "2", ["2|two"]),
    ("arch", "How many compute trays are in one GB200 NVL72 rack?", "18", ["18"]),
    ("arch", "Total GPUs in the rack, and the math?", "4 per tray x 18 trays = 72", ["72"]),
    ("arch", "How many NVLink switch trays, and how many logical switches?", "9 trays, 18 logical (2 ASICs per tray)", ["9", "18"]),
    ("arch", "How many ACP links go through the cable cartridges?", "144", ["144"]),
    ("tags", "Where is the service tag on a compute tray?", "On the luggage tag near the BMC port", ["luggage", "bmc"]),
    ("tags", "Where is the tag on an N5200 NVLink switch?", "Bottom of the luggage tag, bottom right", ["bottom", "right"]),
    ("tags", "Where is the tag on an N5600 NVLink switch?", "Bottom of the luggage tag, on the right side", ["right side|right-side"]),
    ("tags", "Cable cartridge: where is the label, and which number do you use?", "Left side (middle, top, bottom). Use the NVIDIA SN", ["left", "nvidia|sn"]),
    ("tags", "Where are the tags for power trays and power inverters?", "Back right side near the bus bar", ["back", "right", "bus"]),
    ("tags", "Name one of the three places for the IR7000 rack tag.", "Back right corner, top center, or front right corner", ["back|top|front", "corner|center"]),
    ("safety", "What does holding the power button on a CT in a running rack break?", "The NVLink network fabric (job may need a manual restart)", ["nvlink|fabric"]),
    ("safety", "What is the correct way to shut down a CT in a production rack?", "Graceful ACPI shutdown from the BMC power options", ["graceful|acpi|soft"]),
    ("safety", "One NVLink switch goes offline. What happens to the rack?", "Production halts on the whole rack", ["whole|entire|all", "halt|stop"]),
    ("safety", "What must be done to a switch before it goes into a production rack, and why?", "Factory reset, or ZTP will fail", ["factory reset|factory-reset", "ztp"]),
    ("safety", "Which switch is the primary (master)?", "Switch 1", ["1|one"]),
    ("firmware", f"Which package does {SITE_NAME} run in all data halls, and which BMC build?", "1.3.6, BMC 26.01.10001500", ["1.3.6", "26.01.10001500"]),
    ("firmware", "Can a CT on the 1.3.6 package be downgraded?", "No. It can not be downgraded", ["no|cannot|can not|can't|never"]),
    ("firmware", "Give the CT firmware update order.", "BMC, then BIOS, then Bianca", ["bmc", "bios", "bianca"]),
    ("firmware", "What power state must the CT be in for each firmware update?", "Powered off", ["off"]),
    ("firmware", "How long does the Bianca update take?", "45 minutes to 1 hour 30 minutes", ["45", "1.5|90|1 h|1h|hour"]),
    ("firmware", "How long do the BMC and BIOS updates take?", "BMC 10 to 15 min, BIOS about 15 min", ["10", "15"]),
    ("fru", "What must you run after replacing a BMC, and when?", "fixBMC.sh, before powering on the CT", ["fixbmc", "before"]),
    ("fru", "Which FRU is GB200 only?", "IPEX", ["ipex"]),
    ("fru", "Name five compute tray FRUs.", "CT, M.2 riser, NVMe, backplane, control panel, OSFP headers, LOM, BMC, HMC, PDB, IPEX, BF3, fans, cables, CMOS battery", ["bmc|hmc|pdb|fan|nvme|m.2|m2|backplane|lom|ipex|bf3|bluefield|cmos|osfp|cable|control"]),
    ("layout", "Which three things are marked on the front of the 9712a?", "BlueField-3, OSFP headers, LOM port", ["bluefield|bf3", "osfp", "lom"]),
    ("layout", "Which drive slots work in the base configuration?", "Slots 0 to 3", ["0", "3"]),
    ("layout", "What is needed to use drive slots 4 to 7?", "Another BF3 or a PSB installed", ["bf3|bluefield|psb"]),
    ("layout", "Which board shares a location with the BMC inside the tray?", "The interposer board", ["interposer"]),
    ("console", "Type the SOL activate command for BMC 192.168.8.17.", "ipmitool -H 192.168.8.17 -U admin -P admin -I lanplus sol activate", ["ipmitool", "lanplus", "192.168.8.17", "sol activate"]),
    ("console", "A SOL session is stuck. What do you run, and where?", "The same command with sol deactivate, in another window", ["deactivate"]),
    ("console", "How long does a dropped SOL session hang if you do nothing?", "3 to 5 minutes", ["3", "5"]),
    ("console", "PuTTY serial settings for a CT over USB to Micro-USB?", "Serial line COM#, speed 115200", ["com", "115200"]),
    ("console", "Where do you find a CT's COM port number on Windows?", "Device Manager", ["device manager"]),
    ("console", "Which keys open BIOS and the Boot Override Menu?", "F2 and F11", ["f2", "f11"]),
    ("console", "How do you save SOL output to a file in WSL, and how do you stop?", "script <file>.txt, then exit", ["script", "exit"]),
    ("console", "Which two console methods are unreliable or finicky?", "BMC virtual console and the DisplayPort (worse with the StarTech KVM)", ["virtual|bmc", "display"]),
    ("post", "A CT sits at Shell>. What does that tell you?", "POST completed. Normal when PXE finds nothing to boot. PXE issues not ruled out", ["post", "complete|finish|done|normal|pass"]),
    ("post", "What do you type at Shell> to try booting again?", "exit", ["exit"]),
    ("post", "How do you boot a USB live image without restarting?", "Plug in the USB before typing exit at Shell>", ["usb", "exit"]),
    ("logs", "Type the SEL collection command (BMC 192.168.8.21, tag ABC1234).", "ipmitool -I lanplus -H 192.168.8.21 -U admin -P admin sel -v list | tee -a ABC1234-sel.txt", ["sel -v list", "tee -a", "abc1234-sel.txt"]),
    ("logs", "Type the SDR collection command (BMC 192.168.8.21, tag ABC1234).", "ipmitool -I lanplus -H 192.168.8.21 -U admin -P admin sdr elist | tee -a ABC1234-sdr.txt", ["sdr elist", "tee -a", "abc1234-sdr.txt"]),
    ("logs", "Which Redfish path holds the HMC event log?", "/redfish/v1/Systems/HGX_Baseboard_0/LogServices/EventLog/Entries", ["hgx_baseboard_0", "eventlog", "entries"]),
    ("logs", "When do you collect logs on a CT?", "Whenever you work on a CT", ["whenever|every|always|any time|each time"]),
    ("nopower", "Name the four causes of no power.", "Voltage errors, leak detection errors, HMC, PDB", ["voltage|busbar", "leak", "hmc", "pdb"]),
    ("nopower", "Busbar re-torque: value and order?", "20 in-lb: back, front, middle", ["20", "back", "front", "middle"]),
    ("nopower", "What do you do before re-torquing the busbar screws?", "Loosen all the screws", ["loosen"]),
    ("nopower", "HMC causes no power. What do you reseat?", "The slimline cables and the card", ["slimline", "card"]),
    ("leak", "What voltage range means a leak sensor is OK?", "1.70 to 1.75 volts", ["1.70|1.7", "1.75"]),
    ("leak", "Which position is sensor Ch0LeaDet1ColPla?", "M1_0", ["m1_0"]),
    ("leak", "Which position is sensor Cha0LeaDete0Mani?", "M0_1", ["m0_1"]),
    ("leak", "What does a leak error do to power, and what do the drives show?", "Prevents power on; drives flash amber, then the system powers off", ["amber", "off|prevent"]),
    ("leak", "The BMC must be above which revision before you trust a leak alarm?", "25.09.30001500", ["25.09.30001500"]),
    ("leak", "No coolant under UV, but the sensor touches the cold plate. Fix?", "Clean the sensor and use a zip tie", ["zip"]),
    ("pci", "Which log shows PCI errors for CX7/8, BF3 and GPUs?", "The HMC log", ["hmc"]),
    ("pci", "Name three reasons an OSFP cable is not seated at the mezz.", "Tension bar not torqued, foam pad out of place, bent pins on the OSFP header cable", ["tension", "foam", "pin"]),
    ("pci", "BF3 PXE fails; the port shows in BIOS and mlxlink_info. Fix?", "Update the BF3 firmware to v1.3 or above", ["1.3"]),
    ("pci", "BF3 does not show in BIOS or mlxlink_info. What do you do?", "Pull the HMC log and let support check for PCI errors", ["hmc", "support"]),
    ("swap", "Which parts move from the defective CT to the replacement?", "Handles, rails, drives (internal drive and front drives)", ["handle", "rail", "drive"]),
    ("swap", "What kind of work order does support open for a CT swap?", "A 'Part Only' work order", ["part only|part-only"]),
    ("swap", "CT in production fails and the hospital has healthy CTs. Where does the bad CT go?", "From the production rack to the hospital", ["hospital"]),
    ("swap", "What is the last paperwork step of a CT swap?", "Submit the swap form", ["swap form"]),
    ("diag", "What auto-runs on the Support Live Image, and for how long?", "The Valet script, 5 to 10 minutes", ["valet", "5", "10"]),
    ("diag", "What does mlxlink_info check?", "State and health of the network ports", ["network|port|link"]),
    ("diag", "Which two things does the NVIDIA bug report check on the GPUs?", "Remapped rows and ECC errors", ["remap", "ecc"]),
    ("diag", "NVIDIA Field Diagnostics: other name and run time?", "629; a little over 3 hours", ["629", "3"]),
    ("diag", "What does ezBMC gather, and where is the zip?", "HMC, SEL, SDR, firmware; ezBMC_Logs in the WSL home directory", ["hmc|sel|sdr|firmware", "ezbmc_logs|home"]),
    ("diag", "Does nvdebug.sh replace an NVIDIA bug report?", "No", ["no|not"]),
    ("fiber", "What are the three steps before you connect any fiber?", "Inspect, clean, inspect", ["inspect", "clean"]),
    ("fiber", "Jacket color of single-mode OS2 fiber?", "Yellow", ["yellow"]),
    ("fiber", "Which is weaker light: -9 dBm or -2 dBm?", "-9 dBm", ["-9|9"]),
    ("power", "Three-phase power formula?", "P = 1.732 x V x I x PF", ["1.732|sqrt|root", "pf|power factor"]),
    ("power", "Continuous load allowed on a 60 A breaker?", "48 A (80%)", ["48"]),
    ("power", "Watts to BTU per hour?", "Multiply by 3.412", ["3.41"]),
    ("ops", "Define MTTD.", "Mean time to detect: average of detected minus fault start", ["detect"]),
    ("ops", "Define MTTR.", "Mean time to repair: average of repaired minus detected", ["repair"]),
    ("ops", "What three things do you match when receiving?", "PO, packing slip, physical scan", ["po|purchase", "slip|packing", "scan|serial|physical"]),
    ("ops", "Name five SOP sections.", "Purpose, Scope, Safety, Tools, Procedure, Verification, Records", ["purpose|scope|safety|tools|procedure|verification|records"]),
]
