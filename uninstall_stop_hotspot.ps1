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
# "Quit" menu item does. This gives pystray a chance to delete its own
# notification-area icon before the process dies. installer.iss's taskkill
# /F step further below does not give it that chance, and was confirmed
# live to leave a stale, unresponsive tray icon behind whenever it ran
# without this step first. Best-effort: if the app already isn't running,
# or config.json is missing, this just does nothing and the taskkill step
# still cleans up the process itself.
try {
    $configPath = Join-Path $PSScriptRoot 'config.json'
    $port = 8000
    if (Test-Path $configPath) {
        $cfg = Get-Content $configPath -Raw | ConvertFrom-Json
        if ($cfg.portal_port) { $port = $cfg.portal_port }
    }
    Invoke-WebRequest -Uri "http://127.0.0.1:$port/_internal/quit" -Method Post -TimeoutSec 2 -UseBasicParsing | Out-Null
    Start-Sleep -Milliseconds 1500
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
