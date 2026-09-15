// Lock/handle protocol: src/Main_App/updates/cache_io.py.
// Recognized payload/receipt names: src/Main_App/updates/cache.py.
// Normal operation never removes the lock. Final uninstall may remove it only
// after an exclusive handle proves there are no holders or pre-opened waiters.

const
  UpdateInstallerPrefix = 'fpvstoolbox-';
  UpdatePatchPrefix = 'fpvstoolbox-patch-';

type
  TUpdateLockOverlapped = record
    Internal: THandle;
    InternalHigh: THandle;
    Offset: Cardinal;
    OffsetHigh: Cardinal;
    Event: THandle;
  end;

function UpdateLockFile(Handle: THandle; Flags, Reserved, Low, High: Cardinal;
  var Overlapped: TUpdateLockOverlapped): Boolean;
  external 'LockFileEx@kernel32.dll stdcall';
function UpdateUnlockFile(Handle: THandle; Reserved, Low, High: Cardinal;
  var Overlapped: TUpdateLockOverlapped): Boolean;
  external 'UnlockFileEx@kernel32.dll stdcall';

function UpdateInstallerName(const Name: String): Boolean;
var
  LowerName, Version, SourceVersion: String;
  Separator: Integer;
begin
  Result := False;
  if Length(Name) > 200 then
    Exit;
  LowerName := Lowercase(Name);
  if Copy(LowerName, Length(LowerName) - 3, 4) <> '.exe' then
    Exit;
  if Copy(LowerName, 1, Length(UpdatePatchPrefix)) = UpdatePatchPrefix then begin
    Version := Copy(LowerName, Length(UpdatePatchPrefix) + 1,
      Length(LowerName) - Length(UpdatePatchPrefix) - 4);
    Separator := Pos('-to-', Version);
    if Separator < 2 then
      Exit;
    SourceVersion := Copy(Version, 1, Separator - 1);
    Version := Copy(Version, Separator + 4, Length(Version));
    Result := (SourceVersion <> Version) and (Pos('-to-', Version) = 0) and
      OwnedValidVersion(SourceVersion) and OwnedValidVersion(Version);
    Exit;
  end;
  if Copy(LowerName, 1, Length(UpdateInstallerPrefix)) <> UpdateInstallerPrefix then
    Exit;
  if Copy(LowerName, Length(LowerName) - 9, 10) <> '-setup.exe' then
    Exit;
  Version := Copy(LowerName, Length(UpdateInstallerPrefix) + 1,
    Length(LowerName) - Length(UpdateInstallerPrefix) - 10);
  Result := OwnedValidVersion(Version);
end;

function UpdateHexUuid(const Text: String): Boolean;
var
  I: Integer;
begin
  Result := False;
  if Length(Text) <> 32 then
    Exit;
  for I := 1 to Length(Text) do
    if Pos(Lowercase(Text[I]), '0123456789abcdef') = 0 then
      Exit;
  Result := True;
end;

function UpdateCacheOwnedName(const Name: String): Boolean;
var
  Stem: String;
begin
  Result := UpdateInstallerName(Name);
  if Result then
    Exit;
  Stem := Lowercase(Name);
  if Copy(Stem, Length(Stem) - 13, 14) = '.verified.json' then begin
    Result := UpdateInstallerName(Copy(Name, 1, Length(Name) - 14));
    Exit;
  end;
  if Copy(Stem, Length(Stem) - 4, 5) = '.part' then begin
    Stem := Copy(Name, 1, Length(Name) - 5);
    if UpdateInstallerName(Stem) then begin
      Result := True;
      Exit;
    end;
    if Length(Stem) > 33 then
      if (Stem[Length(Stem) - 32] = '.') and
        UpdateHexUuid(Copy(Stem, Length(Stem) - 31, 32)) then
        Result := UpdateInstallerName(Copy(Stem, 1, Length(Stem) - 33));
    Exit;
  end;
  if Copy(Stem, Length(Stem) - 3, 4) = '.tmp' then begin
    Stem := Copy(Name, 1, Length(Name) - 4);
    if Length(Stem) <= 42 then
      Exit;
    if (Stem[Length(Stem) - 32] <> '.') or
      (not UpdateHexUuid(Copy(Stem, Length(Stem) - 31, 32))) then
      Exit;
    Stem := Copy(Stem, 1, Length(Stem) - 33);
    if Lowercase(Copy(Stem, Length(Stem) - 8, 9)) = '.verified' then
      Result := UpdateInstallerName(Copy(Stem, 1, Length(Stem) - 9));
  end;
end;

function UpdateHelperOwnedName(const Name: String): Boolean;
var
  Stem: String;
begin
  Result := False;
  if (Name <> Lowercase(Name)) or (Copy(Name, 1, 8) <> 'updater-') then
    Exit;
  Stem := Copy(Name, 9, Length(Name) - 8);
  if (Length(Stem) = 68) and (Copy(Stem, 65, 4) = '.exe') then
    Result := OwnedValidHash(Copy(Stem, 1, 64))
  else if (Length(Stem) = 37) and (Copy(Stem, 33, 5) = '.part') then
    Result := UpdateHexUuid(Copy(Stem, 1, 32));
end;

function UpdateOwnedPayloadName(const Name: String; Helpers: Boolean): Boolean;
begin
  if Helpers then
    Result := UpdateHelperOwnedName(Name)
  else
    Result := UpdateCacheOwnedName(Name);
end;

procedure UpdateDeleteCachePayload(const Root, Name: String; Helpers: Boolean);
var
  Path: String;
  Handle: THandle;
  Guards: TOwnedHandles;
  Missing: Boolean;
  DeleteFlag: Byte;
begin
  if not UpdateOwnedPayloadName(Name, Helpers) then
    Exit;
  Path := OwnedTarget(Root, Name);
  if SameText(Path, ExpandFileName(ParamStr(0))) then begin
    Log('Update cache: preserving the currently running executable.');
    Exit;
  end;
  if not OwnedOpenRegular(Path, True, Handle, Guards, Missing) then begin
    if not Missing then
      Log('Update cache: retaining inaccessible/linked payload: ' + Name);
    Exit;
  end;
  try
    DeleteFlag := 1;
    if OwnedSetDisposition(Handle, 4, DeleteFlag, 1) then
      Log('Update cache: removed ' + Name)
    else
      Log('Update cache: retained locked payload: ' + Name);
  finally
    OwnedCloseHandle(Handle);
    OwnedReleaseGuards(Guards);
  end;
end;

procedure UpdateRemoveQuiescentCache(const Root: String);
var
  LockHandle: THandle;
  Guards, ParentGuards: TOwnedHandles;
  Info: TOwnedFileInfo;
  DeleteFlag: Byte;
  Removed: Boolean;
begin
  Removed := False;
  if not OwnedGuardDirectories(Root, False, Guards) then
    Exit;
  try
    // share=0 excludes every existing protocol handle, including a lock waiter.
    // Once opened, no peer can attach to this identity until its deletion commits.
    LockHandle := OwnedCreateFile(OwnedTarget(Root, '.fpvs-update.lock'),
      OwnedReadAccess or OwnedDeleteAccess, 0, 0, OwnedOpenExisting, OwnedOpenReparsePoint, 0);
    if LockHandle = OwnedInvalidHandle then begin
      Log('Update cache: retaining lock metadata because another handle may be active.');
      Exit;
    end;
    try
      if (not OwnedGetFileInfo(LockHandle, Info)) or
        ((Info.Attributes and (OwnedDirectoryAttribute or OwnedReparseAttribute)) <> 0) or
        (Info.LinkCount <> 1) then
        Exit;
      DeleteFlag := 1;
      Removed := OwnedSetDisposition(LockHandle, 4, DeleteFlag, 1);
    finally
      OwnedCloseHandle(LockHandle);
    end;
  finally
    OwnedReleaseGuards(Guards);
  end;
  if not Removed then
    Exit;
  if not OwnedGuardDirectories(ExtractFileDir(Root), False, ParentGuards) then
    Exit;
  try
    if (OwnedGetAttributes(Root) and OwnedReparseAttribute) = 0 then
      if not RemoveDir(Root) then
        Log('Update cache: directory retained because it is nonempty or a new writer pinned it.');
  finally
    OwnedReleaseGuards(ParentGuards);
  end;
end;

procedure UpdateCleanupCacheRoot(const Root: String; Helpers: Boolean);
var
  LockPath: String;
  Guards: TOwnedHandles;
  LockHandle: THandle;
  Info: TOwnedFileInfo;
  Overlapped: TUpdateLockOverlapped;
  FindRec: TFindRec;
begin
  if not DirExists(Root) then
    Exit;
  if not OwnedGuardDirectories(Root, False, Guards) then begin
    Log('Update cache: cleanup skipped for an unsafe/unavailable cache root.');
    Exit;
  end;
  try
    LockPath := OwnedTarget(Root, '.fpvs-update.lock');
    LockHandle := OwnedCreateFile(LockPath, OwnedReadAccess or OwnedWriteAccess,
      OwnedShareRead or OwnedShareWrite, 0, OwnedOpenAlways, OwnedOpenReparsePoint, 0);
    if LockHandle = OwnedInvalidHandle then begin
      Log('Update cache: lock could not be opened; no files were removed.');
      Exit;
    end;
    try
      if (not OwnedGetFileInfo(LockHandle, Info)) or
        ((Info.Attributes and (OwnedDirectoryAttribute or OwnedReparseAttribute)) <> 0) or
        (Info.LinkCount <> 1) then begin
        Log('Update cache: unsafe lock identity; no files were removed.');
        Exit;
      end;
      Overlapped.Internal := 0;
      Overlapped.InternalHigh := 0;
      Overlapped.Offset := 0;
      Overlapped.OffsetHigh := 0;
      Overlapped.Event := 0;
      // LOCKFILE_EXCLUSIVE_LOCK | LOCKFILE_FAIL_IMMEDIATELY; byte [0, 1).
      if not UpdateLockFile(LockHandle, 3, 0, 1, 0, Overlapped) then begin
        Log('Update cache: updater is busy; no files were removed.');
        Exit;
      end;
      try
        if FindFirst(AddBackslash(Root) + '*', FindRec) then begin
          try
            repeat
              if ((FindRec.Attributes and (OwnedDirectoryAttribute or OwnedReparseAttribute)) = 0) and
                UpdateOwnedPayloadName(FindRec.Name, Helpers) then begin
                try
                  UpdateDeleteCachePayload(Root, FindRec.Name, Helpers);
                except
                  Log('Update cache: nonfatal cleanup error: ' + GetExceptionMessage);
                end;
              end;
            until not FindNext(FindRec);
          finally
            FindClose(FindRec);
          end;
        end;
      finally
        UpdateUnlockFile(LockHandle, 0, 1, 0, Overlapped);
      end;
    finally
      OwnedCloseHandle(LockHandle);
    end;
  finally
    OwnedReleaseGuards(Guards);
  end;
  UpdateRemoveQuiescentCache(Root);
  // Unknown files remain; a busy cleanup may retain small lock metadata. Never recurse.
end;

procedure UpdateCleanupCacheOnUninstall;
begin
  // These exact app-owned roots are independent of project and temporary trees.
  try
    UpdateCleanupCacheRoot(RemoveBackslashUnlessRoot(
      ExpandConstant('{localappdata}\FPVS Toolbox\updates')), False);
  except
    Log('Update cache: nonfatal payload cleanup error: ' + GetExceptionMessage);
  end;
  try
    UpdateCleanupCacheRoot(RemoveBackslashUnlessRoot(
      ExpandConstant('{localappdata}\FPVS Toolbox\updater-helper')), True);
  except
    Log('Update cache: nonfatal helper cleanup error: ' + GetExceptionMessage);
  end;
  try
    // The installation coordinator stores only its lock here. Never enumerate or
    // remove payloads; unknown files prevent removal of the containing directory.
    UpdateRemoveQuiescentCache(RemoveBackslashUnlessRoot(
      ExpandConstant('{localappdata}\FPVS Toolbox\updater-install')));
  except
    Log('Update cache: nonfatal installation lock cleanup error: ' + GetExceptionMessage);
  end;
end;
