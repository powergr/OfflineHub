# Run by the uninstaller (see installer.iss [UninstallRun]) before files are
# removed. Best-effort, silent: stops both the WinRT Mobile Hotspot and the
# legacy netsh hosted network, regardless of which one (if either) is active.
#
# This exists because Windows Mobile Hotspot is a system-managed service
# state, not tied to the app process's lifetime — confirmed directly: starting
# tethering, then letting the controlling process exit without calling
# StopTetheringAsync(), leaves the hotspot broadcasting indefinitely. Simply
# killing OfflineHub.exe during uninstall is not enough on its own.
$ErrorActionPreference = 'SilentlyContinue'

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
