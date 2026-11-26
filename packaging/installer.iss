; Inno Setup script for the PwMan Windows installer.
; Build the app with PyInstaller first (dist\PwMan), then:
;     iscc /DMyAppVersion=0.1.0 packaging\installer.iss
; The installer is written to dist\PwMan-Setup-<version>.exe

#define MyAppName "PwMan"
#ifndef MyAppVersion
  #define MyAppVersion "0.1.0"
#endif
#define MyAppExeName "PwMan.exe"

[Setup]
AppId={{8F6C1F7E-5B7A-4C1E-9C55-2B7C2E0A9D41}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher=PwMan
VersionInfoVersion={#MyAppVersion}
VersionInfoDescription={#MyAppName} offline password manager setup
; Per-user install by default (no administrator rights needed);
; the user can choose "install for all users" in the first dialog.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=PwMan-Setup-{#MyAppVersion}
SetupIconFile=pwman.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
CloseApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\PwMan\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Only program files are removed. The vault in %APPDATA%\PwMan is intentionally kept.
Type: filesandordirs; Name: "{app}"

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usPostUninstall) and (not UninstallSilent) then
    MsgBox('PwMan was removed.' + #13#10#13#10 +
           'Your password vault was NOT deleted. It is still in:' + #13#10 +
           ExpandConstant('{userappdata}\PwMan') + #13#10#13#10 +
           'Delete that folder yourself if you no longer need it.', mbInformation, MB_OK);
end;
