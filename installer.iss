; Single source of truth for the version: the VERSION file at repo root,
; also read at runtime by core/version.py. Keeps the installer, the running
; app, and the Settings page from ever drifting out of sync with each other.
#define MyAppVersion Trim(FileRead(FileOpen("VERSION")))

[Setup]
AppName=Offline Knowledge Hub
AppVersion={#MyAppVersion}
AppPublisher=Offline Hub Team
DefaultDirName=C:\OfflineHub
DisableProgramGroupPage=yes
OutputBaseFilename=OfflineHub_Setup
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=admin
SetupIconFile=assets\icons\hub.ico
UninstallDisplayIcon={app}\OfflineHub.exe

[Dirs]
; Ensure directories exist and grant standard users write access
; This ensures your app can modify config.json without running as Administrator every time
Name: "{app}"; Permissions: users-modify
Name: "{app}\modules"; Permissions: users-modify

[Files]
; 1. Nuitka compiled executable, Python dependencies, and bundled templates/
;    (templates/ is pulled in via build.bat's --include-data-dir, so it's
;    already inside main.dist — no separate copy step needed here)
Source: "main.dist\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; 2. Portal assets (vendored maplibre-gl, icons) — no vendor binaries anymore:
;    libzim and onnxruntime-genai are plain pip dependencies bundled by Nuitka.
Source: "assets\*"; DestDir: "{app}\assets"; Flags: ignoreversion recursesubdirs createallsubdirs

; 3. Default Config
Source: "config.json"; DestDir: "{app}"; Flags: ignoreversion

; 4. Uninstall helper script (stops the hotspot before files are removed —
;    see [UninstallRun] below for why this needs its own step)
Source: "uninstall_stop_hotspot.ps1"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
; Create Desktop and Start Menu shortcuts
Name: "{commondesktop}\Offline Hub"; Filename: "{app}\OfflineHub.exe"; IconFilename: "{app}\assets\icons\hub.ico"
Name: "{commonprograms}\Offline Hub"; Filename: "{app}\OfflineHub.exe"; IconFilename: "{app}\assets\icons\hub.ico"

[Run]
; Allow the app through Windows Firewall by program path (not by port number,
; so it keeps working if the portal port is ever changed in Settings). This
; matters specifically because the app runs windowless and elevated — the
; normal interactive "Allow this app through the firewall?" prompt a console
; or windowed app would trigger on first listen() may never actually surface
; to the user, silently leaving the portal unreachable from any device on the
; hotspot (confirmed live: no firewall rule existed at all pre-install, and
; the default profile inbound action is effectively block-unless-allowed).
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""Offline Knowledge Hub"" dir=in action=allow program=""{app}\OfflineHub.exe"" enable=yes profile=any"; Flags: runhidden waituntilterminated

; Option to launch the app immediately after installation
Filename: "{app}\OfflineHub.exe"; Description: "{cm:LaunchProgram,Offline Knowledge Hub}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; The app has no console and no signal handler, so there's no graceful "please
; quit" short of hitting its own tray menu — the uninstaller can't do that.
; Windows Mobile Hotspot is also a system-managed service, not tied to the
; app process's lifetime (confirmed directly: starting tethering then killing
; the controlling process leaves it broadcasting indefinitely), so stopping
; the hotspot and killing the process are two separate necessary steps, in
; that order — killing the process first would leave an orphaned hotspot with
; nothing left to stop it.
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File ""{app}\uninstall_stop_hotspot.ps1"""; Flags: runhidden waituntilterminated; RunOnceId: "StopHotspot"
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM OfflineHub.exe /T"; Flags: runhidden waituntilterminated; RunOnceId: "StopMainExe"
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""Offline Knowledge Hub"""; Flags: runhidden waituntilterminated; RunOnceId: "RemoveFirewallRule"

[UninstallDelete]
; This tells the uninstaller to aggressively delete all generated files and folders
Type: filesandordirs; Name: "{app}\modules"
Type: filesandordirs; Name: "{app}\downloads"
Type: filesandordirs; Name: "{app}\*"
Type: dirifempty; Name: "{app}"