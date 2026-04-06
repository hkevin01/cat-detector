; =============================================================================
; ID:       CAT-DETECTOR-ISS-001
; Purpose:  Inno Setup 6 installer script — creates cat-detector-installer.exe,
;           a GUI Windows installer for Cat Detector v2.0.0.
; Requirement: Inno Setup 6.x  (preinstalled on GitHub Actions windows-latest)
; Usage:    ISCC.exe installer\cat-detector.iss
; Output:   dist\cat-detector-installer-2.0.0-windows-x64.exe
; =============================================================================

#define MyAppName      "Cat Detector"
#define MyAppVersion   "2.0.0"
#define MyAppPublisher "hkevin01"
#define MyAppURL       "https://github.com/hkevin01/cat-detector"
#define MyAppExeName   "cat-detector.exe"

[Setup]
; NOTE: Double-brace {{ }} is Inno Setup's escape for a literal {
AppId={{F3C2B1A0-D4E5-6789-ABCD-012345678901}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
; Install per-user by default (no UAC prompt); dialog lets user elevate for
; an all-users install if preferred.
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
; Output location and filename (relative to this .iss file)
OutputDir=..\dist
OutputBaseFilename=cat-detector-installer-{#MyAppVersion}-windows-x64
Compression=lzma
SolidCompression=yes
WizardStyle=modern
; Per-user install requires no elevation; allow dialog to offer all-users
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
; Optional: add cat-detector to the Windows startup registry key
Name: "startup"; \
  Description: "Start {#MyAppName} automatically when Windows starts"; \
  GroupDescription: "Startup options:"; \
  Flags: unchecked

[Files]
; Main executable — built by PyInstaller before running this script
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
; README for in-installer reading (shown on the InfoAfter page)
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion isreadme

[Icons]
; Start Menu shortcuts
Name: "{group}\{#MyAppName}";              Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{#MyAppName} (high sensitivity)"; \
  Filename: "{app}\{#MyAppExeName}";       Parameters: "--sensitivity high"
Name: "{group}\{#MyAppName} (toddler mode)"; \
  Filename: "{app}\{#MyAppExeName}";       Parameters: "--toddler"
Name: "{group}\Uninstall {#MyAppName}";    Filename: "{uninstallexe}"

[Registry]
; Per-user startup registry key — only written when the "startup" task is selected
Root: HKCU; \
  Subkey: "SOFTWARE\Microsoft\Windows\CurrentVersion\Run"; \
  ValueType: string; \
  ValueName: "{#MyAppName}"; \
  ValueData: """{app}\{#MyAppExeName}"""; \
  Flags: uninsdeletevalue; \
  Tasks: startup

[Run]
; Optional post-install launch (checkbox shown to user, unchecked by default)
Filename: "{app}\{#MyAppExeName}"; \
  Description: "Launch {#MyAppName} now (runs in the background)"; \
  Flags: nowait postinstall skipifsilent; \
  Parameters: "--sensitivity medium"
