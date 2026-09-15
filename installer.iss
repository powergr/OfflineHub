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
;    already inside main.dist, no separate copy step needed here)
Source: "main.dist\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; 2. Portal assets (vendored maplibre-gl, icons): no vendor binaries anymore.
;    libzim and onnxruntime-genai are plain pip dependencies bundled by Nuitka.
Source: "assets\*"; DestDir: "{app}\assets"; Flags: ignoreversion recursesubdirs createallsubdirs

; 3. Default Config
Source: "config.json"; DestDir: "{app}"; Flags: ignoreversion

; 4. Uninstall helper script (stops the hotspot before files are removed;
;    see [UninstallRun] below for why this needs its own step)
Source: "uninstall_stop_hotspot.ps1"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
; Create Desktop and Start Menu shortcuts
Name: "{commondesktop}\Offline Hub"; Filename: "{app}\OfflineHub.exe"; IconFilename: "{app}\assets\icons\hub.ico"
Name: "{commonprograms}\Offline Hub"; Filename: "{app}\OfflineHub.exe"; IconFilename: "{app}\assets\icons\hub.ico"

[Run]
; Allow the app through Windows Firewall by program path (not by port number,
; so it keeps working if the portal port is ever changed in Settings). This
; matters specifically because the app runs windowless and elevated. A
; console or windowed app would normally trigger an interactive "Allow this
; app through the firewall?" prompt on first listen(). That prompt may never
; actually surface to the user here. It could silently leave the portal
; unreachable from any device on the hotspot (confirmed live: no firewall
; rule existed at all pre-install, and the default profile inbound action
; is effectively block-unless-allowed).
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""Offline Knowledge Hub"" dir=in action=allow program=""{app}\OfflineHub.exe"" enable=yes profile=any"; Flags: runhidden waituntilterminated

; Option to launch the app immediately after installation
Filename: "{app}\OfflineHub.exe"; Description: "{cm:LaunchProgram,Offline Knowledge Hub}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; uninstall_stop_hotspot.ps1 first asks the running app to quit gracefully
; over its own loopback-only /_internal/quit route (same effect as its tray
; "Quit" menu item), then stops the hotspot, before this taskkill runs.
; Windows Mobile Hotspot is a system-managed service, not tied to the app
; process's lifetime (confirmed directly: starting tethering then killing
; the controlling process leaves it broadcasting indefinitely) - so stopping
; the hotspot has to happen regardless of whether the graceful quit worked.
; taskkill here is now just the fallback for whatever the graceful quit
; missed (app already crashed, port unreachable, etc.), not the primary way
; the process stops. Killing the process before stopping the hotspot would
; leave an orphaned hotspot with nothing left to stop it, so order matters
; even in the fallback case.
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File ""{app}\uninstall_stop_hotspot.ps1"""; Flags: runhidden waituntilterminated; RunOnceId: "StopHotspot"
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM OfflineHub.exe /T"; Flags: runhidden waituntilterminated; RunOnceId: "StopMainExe"
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""Offline Knowledge Hub"""; Flags: runhidden waituntilterminated; RunOnceId: "RemoveFirewallRule"

[UninstallDelete]
; "{app}\modules" is deliberately NOT listed here - see
; CurUninstallStepChanged in [Code] below for why, and do not add it back
; with a Check: parameter. Confirmed live with an instrumented test build:
; Inno evaluates a [UninstallDelete] entry's Check: function too early to
; see anything InitializeUninstall() computes - specifically, BEFORE
; InitializeUninstall() itself has run. A Check function reading KeepModules
; (set inside InitializeUninstall() from the admin's actual Yes/No answer)
; therefore always saw it at its uninitialized default (False) and deleted
; the whole modules folder unconditionally, regardless of what the admin
; answered - a real report of "chose Keep, modules folder is gone anyway"
; traced directly to this. Deleting modules explicitly in code instead, at
; the usPostUninstall step (which reliably runs after InitializeUninstall
; has already finished), sidesteps the ordering problem entirely.
;
; Everything else generated at runtime is still deleted unconditionally
; here: partial/staged downloads, the log directory, and the small JSON
; state files Inno's automatic [Files]-based cleanup doesn't know about.
; Add any future generated file here too - this replaced a "{app}\*"
; catch-all, so nothing here is swept up automatically anymore.
Type: filesandordirs; Name: "{app}\downloads"
Type: filesandordirs; Name: "{app}\logs"
Type: files; Name: "{app}\config.json"
Type: files; Name: "{app}\usage_stats.json"
Type: dirifempty; Name: "{app}"

[Code]
var
  KeepModules: Boolean;

function DirHasFiles(const Dir: String): Boolean;
var
  FindRec: TFindRec;
begin
  Result := False;
  if FindFirst(Dir + '\*', FindRec) then
  begin
    try
      repeat
        if (FindRec.Name <> '.') and (FindRec.Name <> '..') then
        begin
          Result := True;
          break;
        end;
      until not FindNext(FindRec);
    finally
      FindClose(FindRec);
    end;
  end;
end;

function InitializeUninstall(): Boolean;
begin
  Result := True;
  KeepModules := False;
  if DirHasFiles(ExpandConstant('{app}\modules')) then
  begin
    if MsgBox('Keep the downloaded content under ' + ExpandConstant('{app}') +
              '\modules (Wikipedia, maps, the offline assistant, etc.)?' + #13#10#13#10 +
              'Choose Yes to keep it for next time. Choose No to delete it now and free disk space.',
              mbConfirmation, MB_YESNO) = IDYES then
      KeepModules := True;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  // Deletes the modules folder explicitly here rather than through the
  // UninstallDelete section's Check: mechanism - see the comment on that
  // section above for why that doesn't work. usPostUninstall reliably
  // runs after InitializeUninstall() has already set KeepModules from the
  // admin's real answer, unlike a Check: function.
  if CurUninstallStep = usPostUninstall then
  begin
    if not KeepModules then
    begin
      DelTree(ExpandConstant('{app}\modules'), True, True, True);
      // The app folder would otherwise survive as an empty leftover in
      // this branch: dirifempty above already ran earlier in the
      // process, before this DelTree emptied it out, so it never got a
      // second chance to notice.
      if not DirHasFiles(ExpandConstant('{app}')) then
        RemoveDir(ExpandConstant('{app}'));
    end;
  end;
end;