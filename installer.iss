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
UninstallDisplayIcon={app}\main.exe

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

[Icons]
; Create Desktop and Start Menu shortcuts
Name: "{commondesktop}\Offline Hub"; Filename: "{app}\main.exe"; IconFilename: "{app}\assets\icons\hub.ico"
Name: "{commonprograms}\Offline Hub"; Filename: "{app}\main.exe"; IconFilename: "{app}\assets\icons\hub.ico"

[Run]
; Option to launch the app immediately after installation
Filename: "{app}\main.exe"; Description: "{cm:LaunchProgram,Offline Knowledge Hub}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; This tells the uninstaller to aggressively delete all generated files and folders
Type: filesandordirs; Name: "{app}\modules"
Type: filesandordirs; Name: "{app}\downloads"
Type: filesandordirs; Name: "{app}\*"
Type: dirifempty; Name: "{app}"