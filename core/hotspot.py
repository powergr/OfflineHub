"""
HotspotManager: creates and controls a Windows Wi-Fi hotspot.

Strategy:
  1. Try the Windows 10/11 WinRT Mobile Hotspot API via PowerShell.
  2. Fall back to the legacy 'netsh wlan hosted network' command.
  Both methods require admin rights. If not running as admin, the manager
  offers to relaunch the app with UAC elevation.
"""

import os
import re
import sys
import ctypes
import socket
import subprocess
from typing import Tuple

# All console-app subprocesses (powershell.exe, netsh.exe, arp.exe) must be
# started with CREATE_NO_WINDOW. Otherwise, since this app itself runs
# windowless (no console of its own), Windows pops up a brand-new visible
# console window for every single one of them. Confirmed live: without this,
# a single "Start Hotspot" click that falls through WinRT -> netsh can pop
# five or more PowerShell/cmd windows.
_NO_WINDOW = subprocess.CREATE_NO_WINDOW

# Windows Mobile Hotspot / ICS has used this subnet by long-standing default
# for years, regardless of whether it was started via the WinRT API or the
# legacy netsh hosted network. Confirmed live on this machine (192.168.137.1).
_HOTSPOT_SUBNET_PREFIX = "192.168.137."

# Loads the WinRT tethering types and the reflection-based Await helpers
# PowerShell needs to call their async (IAsyncAction / IAsyncOperation<T>)
# methods. Verified live against this exact machine's PowerShell 5.1. The
# previous version of this script referenced the WindowsRuntimeSystemExtensions
# type under the wrong namespace (System.Runtime.InteropServices.WindowsRuntime
# instead of just System), never loaded the System.Runtime.WindowsRuntime
# assembly that type actually lives in, and never explicitly loaded the
# Windows.Networking.Connectivity / Windows.Networking.NetworkOperators WinRT
# namespaces. Each WinRT namespace needs its own explicit
# "[Type,Namespace,ContentType=WindowsRuntime]" load before its types are
# usable, loading one unrelated namespace (as the old script did) does not
# make others available. All three mistakes made every WinRT call fail
# silently, so the app always fell through to the legacy netsh path. Many
# modern Wi-Fi drivers (this machine's Realtek RTL8852BE included, per
# `netsh wlan show drivers` -> "Hosted network supported: No") have dropped
# support for entirely, hence the "group or resource is not in the correct
# state" error. Fixing this so WinRT actually works removes the need to fall
# back to netsh at all on hardware like this.
_WINRT_PRELUDE = """
Add-Type -AssemblyName System.Runtime.WindowsRuntime
[void][Windows.Networking.Connectivity.NetworkInformation,Windows.Networking.Connectivity,ContentType=WindowsRuntime]
[void][Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager,Windows.Networking.NetworkOperators,ContentType=WindowsRuntime]

$__asTaskAction = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and -not $_.IsGenericMethod -and $_.GetParameters().Count -eq 1
})[0]
$__asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
})[0]

function Await-Action($winrtAction) {
    $task = $__asTaskAction.Invoke($null, @($winrtAction))
    $task.Wait(-1) | Out-Null
}
function Await-Operation($winrtOperation, $resultType) {
    $task = $__asTaskGeneric.MakeGenericMethod($resultType).Invoke($null, @($winrtOperation))
    $task.Wait(-1) | Out-Null
    return $task.Result
}

function Get-InternetProfile {
    $profiles = [Windows.Networking.Connectivity.NetworkInformation]::GetConnectionProfiles()
    return $profiles | Where-Object { $_.GetNetworkConnectivityLevel() -gt 0 } | Select-Object -First 1
}
"""


def is_admin() -> bool:
    """Return True if the current process has administrator privileges."""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def restart_as_admin():
    """
    Relaunch the current process with UAC elevation.
    When running from source, uses pythonw.exe to avoid a console window.
    When running as a frozen EXE, relaunches the same EXE (already windowless).
    """
    if getattr(sys, "frozen", False):
        exe  = sys.executable
        args = ""
    else:
        # Prefer pythonw.exe (no console window) over python.exe
        py_dir = os.path.dirname(sys.executable)
        pythonw = os.path.join(py_dir, "pythonw.exe")
        exe  = pythonw if os.path.exists(pythonw) else sys.executable
        args = " ".join(f'"{a}"' for a in sys.argv)

    # SW_SHOWDEFAULT = 10 lets the new window decide; works for both GUI and EXE
    ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, args, None, 10)


class HotspotManager:

    def __init__(self, config: dict):
        self.config   = config
        self._running = False

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self) -> Tuple[bool, str]:
        if not is_admin():
            return (
                False,
                "Administrator rights are required to start the hotspot.\n\n"
                "Click 'Restart as Admin' in the Hotspot tab, or right-click "
                "OfflineHub.exe and choose 'Run as administrator'."
            )

        ssid = self.config["hotspot"].get("ssid", "SchoolHub")
        pw   = self.config["hotspot"].get("password", "schoolhub2024")

        ok, winrt_msg = self._try_winrt(ssid, pw)
        if ok:
            self._running = True
            return True, winrt_msg

        ok, netsh_msg = self._try_netsh(ssid, pw)
        self._running = ok
        if ok:
            return True, netsh_msg
        return False, f"Mobile Hotspot: {winrt_msg}\n\nLegacy hosted network: {netsh_msg}"

    def stop(self):
        self._stop_winrt()
        self._stop_netsh()
        self._running = False

    def is_running(self) -> bool:
        return self._running

    def get_local_ip(self) -> str:
        """
        Return the IP address students should actually connect to.

        On a machine with both an internet uplink (Ethernet/Wi-Fi station)
        and an active hotspot, those are two different adapters on two
        different subnets. Confirmed live: Ethernet at 172.20.147.29,
        hotspot AP at 192.168.137.1. The naive "connect a UDP socket to
        8.8.8.8 and read the source address" trick always returns whichever
        adapter has the default route (the internet uplink), which is
        exactly the one address a phone connected to the hotspot cannot
        reach. Prefer the hotspot's own subnet (same 192.168.137.0/24
        convention _HOTSPOT_SUBNET_PREFIX already assumes in
        list_connected_devices below) when it's present.
        """
        try:
            addrs = socket.gethostbyname_ex(socket.gethostname())[2]
        except Exception:
            addrs = []

        for addr in addrs:
            if addr.startswith(_HOTSPOT_SUBNET_PREFIX):
                return addr

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                return s.getsockname()[0]
        except Exception:
            return "127.0.0.1"

    def list_connected_devices(self) -> list[str]:
        """
        Parse the ARP cache to find devices on the hotspot subnet.
        Returns a list of IP / MAC strings.
        """
        try:
            out = subprocess.check_output(
                ["arp", "-a"], encoding="utf-8", errors="ignore",
                creationflags=_NO_WINDOW,
            )
            lines   = out.splitlines()
            devices = []
            # Confirmed live: Windows Mobile Hotspot clients show up as
            # "static" in arp -a, not "dynamic" (matching the old regex here
            # meant this always returned empty, even with a phone connected).
            # Match either type, but skip the gateway itself (.1) and the
            # broadcast entry (ff-ff-ff-ff-ff-ff / .255).
            pattern = re.compile(
                r"(" + re.escape(_HOTSPOT_SUBNET_PREFIX) + r"\d+)\s+([\w-]+)\s+(?:dynamic|static)"
            )
            for line in lines:
                # arp -a format: "  192.168.137.x    xx-xx-…    dynamic|static"
                match = pattern.search(line)
                if not match:
                    continue
                ip, mac = match.group(1), match.group(2)
                if mac.lower() == "ff-ff-ff-ff-ff-ff" or ip.endswith(".1"):
                    continue
                devices.append(f"{ip}  ({mac})")
            return devices
        except Exception:
            return []

    # ── WinRT Mobile Hotspot via PowerShell ──────────────────────────────────

    def _try_winrt(self, ssid: str, pw: str) -> Tuple[bool, str]:
        """
        Control the Windows 10/11 Mobile Hotspot (Settings app hotspot) via
        PowerShell. This is more reliable than the raw WinRT COM approach
        in an elevated process.
        """
        ps_script = _WINRT_PRELUDE + f"""
try {{
    $internet = Get-InternetProfile
    if (-not $internet) {{
        Write-Output "NO_INTERNET"
        exit 1
    }}

    $mgr = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager]::CreateFromConnectionProfile($internet)
    $cfg = $mgr.GetCurrentAccessPointConfiguration()
    $cfg.Ssid = '{ssid}'
    $cfg.Passphrase = '{pw}'
    Await-Action ($mgr.ConfigureAccessPointAsync($cfg))

    $resultType = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringOperationResult]
    $result = Await-Operation ($mgr.StartTetheringAsync()) $resultType

    if ($result.Status -eq [Windows.Networking.NetworkOperators.TetheringOperationStatus]::Success) {{
        Write-Output "OK"
    }} else {{
        Write-Output "FAIL:$($result.Status)"
    }}
}} catch {{
    Write-Output "ERROR:$($_.Exception.Message)"
}}
"""
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive",
                 "-ExecutionPolicy", "Bypass", "-Command", ps_script],
                capture_output=True, text=True, timeout=25,
                creationflags=_NO_WINDOW,
            )
            out = result.stdout.strip()
            if "OK" in out:
                return True, "Mobile hotspot started."
            return False, out or result.stderr
        except subprocess.TimeoutExpired:
            return False, "Hotspot start timed out."
        except Exception as e:
            return False, str(e)

    def _stop_winrt(self):
        ps_script = _WINRT_PRELUDE + """
try {
    $internet = Get-InternetProfile
    if ($internet) {
        $mgr = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager]::CreateFromConnectionProfile($internet)
        $resultType = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringOperationResult]
        Await-Operation ($mgr.StopTetheringAsync()) $resultType | Out-Null
    }
} catch {}
"""
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive",
                 "-ExecutionPolicy", "Bypass", "-Command", ps_script],
                capture_output=True, timeout=14,
                creationflags=_NO_WINDOW,
            )
        except Exception:
            pass

    # ── Netsh Hosted Network (legacy fallback) ────────────────────────────────

    def _try_netsh(self, ssid: str, pw: str) -> Tuple[bool, str]:
        """
        Legacy hosted network via netsh. Only relevant on older Wi-Fi drivers
        that still implement it. Many current drivers report "Hosted
        network supported: No" (check with `netsh wlan show drivers`), and
        no amount of adapter resetting here will change that. It's a driver
        capability, not app or Windows-service state.
        """
        # Step 1: stop any existing hosted network, then reset the virtual adapter
        subprocess.run(["netsh", "wlan", "stop", "hostednetwork"],
                       capture_output=True, creationflags=_NO_WINDOW)
        subprocess.run(["netsh", "wlan", "set", "hostednetwork", "mode=disallow"],
                       capture_output=True, creationflags=_NO_WINDOW)

        reset_ps = """
Get-NetAdapter -IncludeHidden |
  Where-Object { $_.InterfaceDescription -like '*Hosted Network*' -or
                 $_.InterfaceDescription -like '*Virtual WiFi*' } |
  ForEach-Object {
      Disable-NetAdapter -Name $_.Name -Confirm:$false -ErrorAction SilentlyContinue
      Start-Sleep -Milliseconds 500
      Enable-NetAdapter  -Name $_.Name -Confirm:$false -ErrorAction SilentlyContinue
  }
"""
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive",
                 "-ExecutionPolicy", "Bypass", "-Command", reset_ps],
                capture_output=True, timeout=10,
                creationflags=_NO_WINDOW,
            )
        except Exception:
            pass

        import time
        time.sleep(1)   # give the adapter a moment to settle

        # Step 2: configure and start
        cmds = [
            ["netsh", "wlan", "set", "hostednetwork",
             "mode=allow", f"ssid={ssid}", f"key={pw}"],
            ["netsh", "wlan", "start", "hostednetwork"],
        ]
        for cmd in cmds:
            r = subprocess.run(cmd, capture_output=True, text=True,
                               creationflags=_NO_WINDOW)
            if r.returncode != 0:
                err = (r.stdout + r.stderr).strip()
                return False, (
                    f"{err}\n\n"
                    "Tip: run 'netsh wlan show drivers' and check \"Hosted "
                    "network supported\". Many current Wi-Fi drivers report "
                    "No, meaning this legacy method can never work here "
                    "regardless of adapter state. Mobile Hotspot (above) is "
                    "the supported path on those drivers."
                )
        return True, "Netsh hotspot started."

    def _stop_netsh(self):
        try:
            subprocess.run(["netsh", "wlan", "stop", "hostednetwork"],
                           capture_output=True, timeout=8,
                           creationflags=_NO_WINDOW)
        except Exception:
            pass

    def open_windows_hotspot_settings(self):
        """Open the Windows Mobile Hotspot settings page directly."""
        try:
            subprocess.Popen(["ms-settings:network-mobilehotspot"],
                             shell=True)
        except Exception:
            subprocess.Popen(["start", "ms-settings:network-mobilehotspot"],
                             shell=True)
