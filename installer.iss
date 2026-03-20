[Setup]
AppName=Offline Knowledge Hub
AppVersion=0.1.2
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
Name: "{app}\bin"; Permissions: users-modify

[Files]
; 1. Nuitka compiled executable and Python dependencies
Source: "main.dist\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; 2. Portal HTML, Icons, and Assets
Source: "assets\*"; DestDir: "{app}\assets"; Flags: ignoreversion recursesubdirs createallsubdirs

; 3. Vendor Binaries (Kiwix, Kolibri)
Source: "vendor\*"; DestDir: "{app}\bin"; Flags: ignoreversion recursesubdirs createallsubdirs

; 4. Default Config
Source: "config.json"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
; Create Desktop and Start Menu shortcuts
Name: "{commondesktop}\Offline Hub"; Filename: "{app}\main.exe"; IconFilename: "{app}\assets\icons\hub.ico"
Name: "{commonprograms}\Offline Hub"; Filename: "{app}\main.exe"; IconFilename: "{app}\assets\icons\hub.ico"

[Run]
; Option to launch the app immediately after installation
Filename: "{app}\main.exe"; Description: "{cm:LaunchProgram,Offline Knowledge Hub}"; Flags: nowait postinstall skipifsilent