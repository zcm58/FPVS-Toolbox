; --- FPVS Toolbox Inno Setup Script (no code signing) ---
; I run this script AFTER I have compiled the app to an .exe using Pyinstaller. This allows me to automatically create shortcuts 
;   on the user's desktop, creates the folder structure needed by the app, and and auto launches the app after installing. 
;   Every time the user downloads a new version of the app, it will automatically overwrite the old files but will NOT change the user's settings. 

#define MyAppName "FPVS Toolbox"
#ifndef AppVersion
#define AppVersion "2.1.0"
#endif
#define MyAppVersion AppVersion
#define MyAppPublisher "Zack Murphy"
#define MyAppExeName "FPVS_Toolbox.exe"

[Setup]
; Identity & versioning
AppId={{77E578C2-2B30-4015-AE3F-9CE6191423F4}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
VersionInfoVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL=https://github.com/zcm58/FPVS-Toolbox-Repo
AppMutex=FPVS_Toolbox_Install_Mutex
SourceDir=..\..

; Install scope & UX
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UsePreviousAppDir=yes
AllowNoIcons=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
CloseApplications=yes
RestartApplications=no
DisableWelcomePage=no
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyMemo=no

; Packaging & output
OutputDir=installers
OutputBaseFilename=FPVSToolbox-{#MyAppVersion}-setup
SetupIconFile=assets\ToolBox_Icon.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

; Upgrades: do NOT wipe {app} (protects logs/config if any landed there).
; If your app writes to AppData, you can clean it on uninstall below.

[Files]
; Copy the PyInstaller one-folder output
Source: "dist\FPVS_Toolbox\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\FPVS_Toolbox\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName,'&','&&')}}"; Flags: nowait postinstall skipifsilent; Check: not RelaunchRequested
Filename: "{app}\{#MyAppExeName}"; Flags: nowait skipifsilent; Check: RelaunchRequested

[Code]
function RelaunchRequested: Boolean;
begin
  Result := Pos('/RELAUNCH=1', Uppercase(GetCmdTail)) > 0;
end;

[UninstallDelete]
; If your app stores user data under LocalAppData, clean it on uninstall:
; Adjust the path if your app uses a different folder name.
Type: filesandordirs; Name: "{localappdata}\FPVS Toolbox"
