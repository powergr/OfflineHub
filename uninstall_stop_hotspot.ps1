# Run by the uninstaller (see installer.iss [UninstallRun]) before files are
# removed. Best-effort, silent: stops both the WinRT Mobile Hotspot and the
# legacy netsh hosted network, regardless of which one (if either) is active.
#
# This exists because Windows Mobile Hotspot is a system-managed service
# state, not tied to the app process's lifetime. Confirmed directly: starting
# tethering, then letting the controlling process exit without calling
# StopTetheringAsync(), leaves the hotspot broadcasting indefinitely. Simply
# killing OfflineHub.exe during uninstall is not enough on its own.
$ErrorActionPreference = 'SilentlyContinue'

# Ask the running app to quit gracefully first, the same way its own tray
# "Quit" menu item does. This gives it a chance to close every module's
# open file handle (main.py's quit_app - notably TileServer's cached
# .mbtiles connections, which used to never get closed at all) and let
# pystray delete its own notification-area icon, before the process dies.
# installer.iss's taskkill /F step further below does not give it that
# chance: whatever it still has open when it hits, it hits mid-open,
# which was confirmed live to matter. A real uninstall run caught the app
# still alive mid-shutdown and, since only its .mbtiles connections were
# still open at that point, deleted every other installed module fine but
# left the two map modules behind - the opposite of what "keep modules"
# was supposed to mean, and just as wrong the other way if the admin had
# chosen to delete everything.
#
# main.py's own quit_app has a 25-second watchdog that force-exits the
# process no matter what hangs, so poll for it to actually be gone for up
# to that long (plus margin) rather than a fixed short sleep. Best-effort
# throughout: if the app already isn't running, or config.json is
# missing, this just does nothing and the taskkill step still cleans up
# the process itself.
try {
    $configPath = Join-Path $PSScriptRoot 'config.json'
    $port = 8000
    if (Test-Path $configPath) {
        $cfg = Get-Content $configPath -Raw | ConvertFrom-Json
        if ($cfg.portal_port) { $port = $cfg.portal_port }
    }
    Invoke-WebRequest -Uri "http://127.0.0.1:$port/_internal/quit" -Method Post -TimeoutSec 2 -UseBasicParsing | Out-Null

    $deadline = (Get-Date).AddSeconds(28)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 500
        $stillUp = $false
        try {
            Invoke-WebRequest -Uri "http://127.0.0.1:$port/api/ip" -Method Get -TimeoutSec 1 -UseBasicParsing | Out-Null
            $stillUp = $true
        } catch {}
        if (-not $stillUp) { break }
    }
} catch {}

try {
    Add-Type -AssemblyName System.Runtime.WindowsRuntime
    [void][Windows.Networking.Connectivity.NetworkInformation,Windows.Networking.Connectivity,ContentType=WindowsRuntime]
    [void][Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager,Windows.Networking.NetworkOperators,ContentType=WindowsRuntime]

    $asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
        $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
    })[0]

    $profiles = [Windows.Networking.Connectivity.NetworkInformation]::GetConnectionProfiles()
    $internet = $profiles | Where-Object { $_.GetNetworkConnectivityLevel() -gt 0 } | Select-Object -First 1
    if ($internet) {
        $mgr = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager]::CreateFromConnectionProfile($internet)
        if ($mgr.TetheringOperationalState -eq [Windows.Networking.NetworkOperators.TetheringOperationalState]::On) {
            $resultType = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringOperationResult]
            $task = $asTaskGeneric.MakeGenericMethod($resultType).Invoke($null, @($mgr.StopTetheringAsync()))
            $task.Wait(10000) | Out-Null
        }
    }
} catch {}

netsh wlan stop hostednetwork | Out-Null
