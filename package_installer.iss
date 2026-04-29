; package_installer.iss — Windows installer replacing package_dmg.sh
; Builds a standard Windows .exe installer via Inno Setup
;
; Download Inno Setup: https://jrsoftware.org/isinfo.php
; Then: "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" package_installer.iss

#define MyAppName "Locus"
#define MyAppVersion "1.0.1"
#define MyAppPublisher "K-man1"
#define MyAppURL "https://locusfocusapp.netlify.app"
#define MyAppExeName "Locus.exe"
#define DaemonExeName "locusd.exe"

[Setup]
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=dist\installer
OutputBaseFilename=LocusSetup-{#MyAppVersion}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon";    Description: "Create a desktop shortcut"; GroupDescription: "Additional icons"
Name: "startupentry";   Description: "Start Locus automatically at login"; GroupDescription: "Startup"

[Files]
; Main tray UI
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
; Daemon
Source: "dist\{#DaemonExeName}"; DestDir: "{app}"; Flags: ignoreversion
; Default config (only installed if user has no existing config)
Source: "config.example.json"; DestDir: "{userappdata}\Locus"; DestName: "config.json"; Flags: onlyifdoesntexist uninsneveruninstall

[Icons]
Name: "{group}\{#MyAppName}";        Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{commondesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; Auto-start at login
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueType: string; ValueName: "{#MyAppName}"; \
    ValueData: "{app}\{#MyAppExeName}"; \
    Flags: uninsdeletevalue; Tasks: startupentry

[Run]
Filename: "{app}\{#MyAppExeName}"; \
    Description: "Launch {#MyAppName}"; \
    Flags: nowait postinstall skipifsilent
