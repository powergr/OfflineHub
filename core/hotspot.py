"""
HotspotManager — creates and controls a Windows Wi-Fi hotspot.

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

        ok, msg = self._try_winrt(ssid, pw)
        if not ok:
            ok, msg = self._try_netsh(ssid, pw)

        self._running = ok
        return ok, msg

    def stop(self):
        self._stop_winrt()
        self._stop_netsh()
        self._running = False

    def is_running(self) -> bool:
        return self._running

    def get_local_ip(self) -> str:
        """Return the best non-loopback IPv4 address for this machine."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                return s.getsockname()[0]
        except Exception:
            return "127.0.0.1"

    def list_connected_devices(self) -> list[str]:
        """
        Parse the ARP cache to find devices likely on the hotspot subnet.
        Returns a list of IP / MAC strings.
        """
        try:
            out = subprocess.check_output(["arp", "-a"],
                                          encoding="utf-8", errors="ignore")
            lines   = out.splitlines()
            devices = []
            for line in lines:
                # arp -a format: "  192.168.137.x    xx-xx-…    dynamic"
                match = re.search(
                    r"(192\.168\.137\.\d+)\s+([\w-]+)\s+dynamic", line
                )
                if match:
                    devices.append(f"{match.group(1)}  ({match.group(2)})")
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
        ps_script = f"""
$ErrorActionPreference = 'Stop'
try {{
    # Load WinRT types
    [void][Windows.System.UserProfile.LockScreen,Windows.System.UserProfile,ContentType=WindowsRuntime]
    $asm = [System.Runtime.InteropServices.WindowsRuntime.WindowsRuntimeSystemExtensions]

    $tetheringMgr = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager]
    $profiles = [Windows.Networking.Connectivity.NetworkInformation]::GetConnectionProfiles()
    $internet = $profiles | Where-Object {{ $_.GetNetworkConnectivityLevel() -gt 0 }} | Select-Object -First 1

    if (-not $internet) {{
        Write-Output "NO_INTERNET"
        exit 1
    }}

    $mgr = $tetheringMgr::CreateFromConnectionProfile($internet)
    $cfg = $mgr.GetCurrentAccessPointConfiguration()
    $cfg.Ssid = '{ssid}'
    $cfg.Passphrase = '{pw}'

    $task = $asm::AsTask($mgr.ConfigureAccessPointAsync($cfg))
    $task.Wait(8000)

    $task2 = $asm::AsTask($mgr.StartTetheringAsync())
    $task2.Wait(15000)

    if ($task2.Result.Status -eq [Windows.Networking.NetworkOperators.TetheringOperationStatus]::Success) {{
        Write-Output "OK"
    }} else {{
        Write-Output "FAIL:$($task2.Result.Status)"
    }}
}} catch {{
    Write-Output "ERROR:$($_.Exception.Message)"
}}
"""
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive",
                 "-ExecutionPolicy", "Bypass", "-Command", ps_script],
                capture_output=True, text=True, timeout=25
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
        ps_script = """
$ErrorActionPreference = 'SilentlyContinue'
$asm = [System.Runtime.InteropServices.WindowsRuntime.WindowsRuntimeSystemExtensions]
$profiles = [Windows.Networking.Connectivity.NetworkInformation]::GetConnectionProfiles()
$internet = $profiles | Where-Object { $_.GetNetworkConnectivityLevel() -gt 0 } | Select-Object -First 1
if ($internet) {
    $mgr = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager]::CreateFromConnectionProfile($internet)
    $task = $asm::AsTask($mgr.StopTetheringAsync())
    $task.Wait(10000)
}
"""
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive",
                 "-ExecutionPolicy", "Bypass", "-Command", ps_script],
                capture_output=True, timeout=14
            )
        except Exception:
            pass

    # ── Netsh Hosted Network (legacy fallback) ────────────────────────────────

    def _try_netsh(self, ssid: str, pw: str) -> Tuple[bool, str]:
        """
        Legacy hosted network via netsh.
        Resets the virtual adapter first to fix 'not in correct state' errors.
        """
        # Step 1: stop any existing hosted network, then reset the virtual adapter
        subprocess.run(["netsh", "wlan", "stop", "hostednetwork"],
                       capture_output=True)
        subprocess.run(["netsh", "wlan", "set", "hostednetwork", "mode=disallow"],
                       capture_output=True)

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
                capture_output=True, timeout=10
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
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0:
                err = (r.stdout + r.stderr).strip()
                return False, (
                    f"{err}\n\n"
                    "Tip: The Windows Mobile Hotspot (Settings app) is more\n"
                    "reliable on modern drivers. Click 'Open Hotspot Settings'\n"
                    "to enable it there — the hub will serve content on that\n"
                    "network automatically without needing this toggle."
                )
        return True, "Netsh hotspot started."

    def _stop_netsh(self):
        try:
            subprocess.run(["netsh", "wlan", "stop", "hostednetwork"],
                           capture_output=True, timeout=8)
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