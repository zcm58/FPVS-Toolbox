#define AppName "FPVS Toolbox"
#ifndef AppVersion
  #error AppVersion is required. Use scripts/packaging/build_installer.ps1.
#endif
#ifndef WindowsVersion
  #error WindowsVersion is required. Use scripts/packaging/build_installer.ps1.
#endif
#define AppPublisher "Zack Murphy"
#define AppExeName "FPVS_Toolbox.exe"
#define UpdaterExeName "Updater\FPVS Toolbox Updater.exe"
#ifndef AppIdGuid
  #define AppIdGuid "77E578C2-2B30-4015-AE3F-9CE6191423F4"
#else
  // Only synthetic lifecycle fixtures override the application identity.
  #define IsLifecycleFixture
#endif
#if VER < 0x06050000
  #error Inno Setup 6.5 or later is required for handle-bound SHA-256 cleanup.
#endif
#ifndef BundleRoot
  #define BundleRoot "..\..\dist\FPVS_Toolbox"
#endif
#ifndef OwnedInventoryRoot
  #define OwnedInventoryRoot "..\..\build\installer-inventory"
#endif

[Setup]
AppId={{{#AppIdGuid}}
AppName={#AppName}
AppVersion={#AppVersion}
VersionInfoVersion={#WindowsVersion}
VersionInfoTextVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL=https://github.com/zcm58/FPVS-Toolbox-Repo
AppMutex=FPVS_Toolbox_Install_Mutex
UsePreviousAppDir=yes
DefaultDirName={localappdata}\Programs\{#AppName}
#ifdef PatchFromVersion
DisableDirPage=yes
#endif
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\..\installers
OutputBaseFilename=FPVSToolbox-{#AppVersion}-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#AppExeName}
SetupIconFile=..\..\assets\ToolBox_Icon.ico
#ifdef IsLifecycleFixture
CloseApplications=no
#else
CloseApplications=yes
#endif
UninstallLogMode=append

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
#ifdef PatchFromVersion
Source: "{#PatchRoot}\payload\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#PatchRoot}\source-owned-files.txt"; Flags: dontcopy
Source: "{#PatchRoot}\patch-payload-files.txt"; Flags: dontcopy
Source: "{#PatchRoot}\patch-transaction.txt"; Flags: dontcopy
#else
Source: "{#BundleRoot}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
#endif
Source: "{#OwnedInventoryRoot}\current-owned-files.txt"; DestDir: "{app}"; DestName: "fpvs-owned-files-v1.txt"; Flags: ignoreversion
Source: "{#OwnedInventoryRoot}\current-owned-files.txt"; Flags: dontcopy
Source: "{#OwnedInventoryRoot}\legacy-owned-files.txt"; Flags: dontcopy

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Check: ShortcutsRequested
Name: "{group}\FPVS Toolbox Update & Repair"; Filename: "{app}\{#UpdaterExeName}"; WorkingDir: "{app}"; Check: UpdaterShortcutRequested
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"; Check: ShortcutsRequested
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon; Check: ShortcutsRequested

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent; Check: NormalLaunchRequested

[Code]
#include "owned_files.iss"
#include "updater_cache.iss"
#ifdef PatchFromVersion
#include "patch_upgrade.iss"
#endif

function RelaunchRequested: Boolean; forward;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  try
#ifdef PatchFromVersion
    Result := PatchPrepare;
    if Result <> '' then
      Exit;
#endif
    Result := OwnedPrepareUpgrade;
  except
    Result := 'Could not safely prepare the application upgrade: ' + GetExceptionMessage;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  // Inno has committed here. Relaunch only after obsolete metadata is reconciled.
  if CurStep = ssPostInstall then begin
#ifdef PatchFromVersion
    if not PatchVerifyInstalledTarget then
      Exit;
#endif
    try
      OwnedReconcileAfterSuccess;
    except
      Log('Ownership cleanup remains pending: ' + GetExceptionMessage);
    end;
#ifdef PatchFromVersion
    PatchFinish;
#else
    OwnedRemoveRecoveredPatchMarker;
#endif
    if RelaunchRequested and (not WizardSilent) then
      if not Exec(OwnedTarget(ExpandConstant('{app}'), '{#AppExeName}'), '', ExpandConstant('{app}'),
        SW_SHOWNORMAL, ewNoWait, ResultCode) then
        Log('Application relaunch failed: ' + IntToStr(ResultCode));
  end;
end;

procedure DeinitializeSetup;
begin
  OwnedDisposeState;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then begin
    try
      OwnedRemovePendingOnUninstall;
    except
      Log('Nonfatal ownership-journal uninstall cleanup error: ' + GetExceptionMessage);
    end;
    try
#ifndef IsLifecycleFixture
      UpdateCleanupCacheOnUninstall;
#endif
    except
      Log('Nonfatal update-cache uninstall cleanup error: ' + GetExceptionMessage);
    end;
  end;
end;

function RelaunchRequested: Boolean;
begin
  Result := (Pos('/RELAUNCH=1', Uppercase(GetCmdTail)) > 0) and
    (Pos('/NOLAUNCH=1', Uppercase(GetCmdTail)) = 0);
#ifdef PatchFromVersion
  Result := Result and (not PatchVerificationFailed);
#endif
end;

function NormalLaunchRequested: Boolean;
begin
  Result := (not RelaunchRequested) and
    (Pos('/NOLAUNCH=1', Uppercase(GetCmdTail)) = 0);
#ifdef PatchFromVersion
  Result := Result and (not PatchVerificationFailed);
#endif
end;

function ShortcutsRequested: Boolean;
begin
  Result := Pos('/NOSHORTCUTS=1', Uppercase(GetCmdTail)) = 0;
end;

function UpdaterShortcutRequested: Boolean;
begin
  Result := ShortcutsRequested and FileExists(ExpandConstant('{app}') + '\{#UpdaterExeName}');
end;
