// Compiled only for a sparse patch. The ordinary installer remains self-contained.
// A durable fingerprint marker permits a known-byte retry after interrupted copying.
// Corrupt or unrecognized bytes require the full installer; they are never trusted.

const
  PatchMarkerName = 'fpvs-patch-transaction-v1.txt';
  PatchRegistration = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{{#AppIdGuid}}_is1';

var
  PatchRootPath: String;
  PatchSourceRecords, PatchTargetRecords, PatchPayloadRecords: TStringList;
  PatchVerificationFailed: Boolean;

function PatchRegisteredRoot(var Root, Version: String): Boolean;
begin
  Result := RegQueryStringValue(HKCU64, PatchRegistration, 'InstallLocation', Root) and
    RegQueryStringValue(HKCU64, PatchRegistration, 'DisplayVersion', Version);
  Root := RemoveBackslashUnlessRoot(Root);
end;

function InitializeSetup: Boolean;
var
  Root, Version: String;
begin
  Result := PatchRegisteredRoot(Root, Version) and OwnedSafeInstallRoot(Root);
  if not Result then
    MsgBox('This patch requires an existing FPVS Toolbox installation. Use the full installer.',
      mbError, MB_OK);
end;

function PatchRecordHash(const RecordText: String): String;
begin
  Result := Copy(RecordText, Pos('|', RecordText) + 1, Length(RecordText));
end;

function PatchContainsPath(Records: TStringList; const Path: String): Boolean;
var
  Index: Integer;
begin
  Records.Find(Path + '|', Index);
  Result := Index < Records.Count;
  if Result then
    Result := SameText(OwnedRecordPath(Records[Index]), Path);
end;

function PatchVerifyRecords(Records: TStringList): Boolean;
var
  I: Integer;
  Hash: String;
begin
  Result := False;
  for I := 0 to Records.Count - 1 do begin
    if (not OwnedHashFile(OwnedTarget(PatchRootPath, OwnedRecordPath(Records[I])), Hash)) or
      (Hash <> PatchRecordHash(Records[I])) then
      Exit;
  end;
  Result := True;
end;

function PatchKnownRecoveryState: Boolean;
var
  I: Integer;
  Path, Hash, FullPath: String;
begin
  Result := False;
  for I := 0 to PatchSourceRecords.Count - 1 do begin
    Path := OwnedRecordPath(PatchSourceRecords[I]);
    FullPath := OwnedTarget(PatchRootPath, Path);
    if OwnedGetAttributes(FullPath) = OwnedInvalidAttributes then begin
      // Inno rollback can remove a replaced file; only shipped payload can repair it.
      // An obsolete source may already be removed after a successful commit.
      if (not PatchContainsPath(PatchPayloadRecords, Path)) and
        PatchContainsPath(PatchTargetRecords, Path) then
        Exit;
    end
    else begin
      if not OwnedHashFile(FullPath, Hash) then
        Exit;
      if PatchSourceRecords.IndexOf(Path + '|' + Hash) < 0 then
        if (not PatchContainsPath(PatchPayloadRecords, Path)) or
          (PatchTargetRecords.IndexOf(Path + '|' + Hash) < 0) then
          Exit;
    end;
  end;
  for I := 0 to PatchPayloadRecords.Count - 1 do begin
    Path := OwnedRecordPath(PatchPayloadRecords[I]);
    if not PatchContainsPath(PatchSourceRecords, Path) then begin
      FullPath := OwnedTarget(PatchRootPath, Path);
      if OwnedGetAttributes(FullPath) <> OwnedInvalidAttributes then
        if (not OwnedHashFile(FullPath, Hash)) or
          (PatchTargetRecords.IndexOf(Path + '|' + Hash) < 0) then
          Exit;
    end;
  end;
  Result := True;
end;

function PatchWriteMarker: Boolean;
var
  Temporary, Hash: String;
  Handle: THandle;
  Guards: TOwnedHandles;
  Missing: Boolean;
begin
  Result := False;
  Temporary := GenerateUniqueName(PatchRootPath, '.fpvs-patch.tmp');
  if not FileCopy(ExpandConstant('{tmp}\patch-transaction.txt'), Temporary, True) then
    Exit;
  try
    if (not OwnedHashFile(Temporary, Hash)) or (Hash <> '{#PatchTransactionSHA256}') then
      Exit;
    // Flush before the same-volume atomic rename; a power loss cannot precede this marker
    // while leaving the later file replacement durably committed.
    if not OwnedOpenRegular(Temporary, False, Handle, Guards, Missing) then
      Exit;
    OwnedCloseHandle(Handle);
    OwnedReleaseGuards(Guards);
    Handle := OwnedCreateFile(Temporary, OwnedWriteAccess, 0, 0,
      OwnedOpenExisting, OwnedOpenReparsePoint, 0);
    if Handle = OwnedInvalidHandle then
      Exit;
    try
      if not OwnedFlushFile(Handle) then
        Exit;
    finally
      OwnedCloseHandle(Handle);
    end;
    Result := OwnedMoveFile(Temporary, OwnedTarget(PatchRootPath, PatchMarkerName), 8);
  finally
    DeleteFile(Temporary);
  end;
end;

function PatchPrepare: String;
var
  RegisteredRoot, Version, Hash, Marker, Manifest: String;
  Guards: TOwnedHandles;
  Recovery: Boolean;
  I: Integer;
  Path: String;
begin
  Result := 'This installation does not match the patch source. Use the full FPVS Toolbox installer to repair or update it.';
  PatchRootPath := RemoveBackslashUnlessRoot(ExpandConstant('{app}'));
  if (not PatchRegisteredRoot(RegisteredRoot, Version)) or
    (not SameText(PatchRootPath, RegisteredRoot)) or
    (not OwnedSafeInstallRoot(PatchRootPath)) or
    (not OwnedGuardDirectories(PatchRootPath, False, Guards)) then
    Exit;
  try
    ExtractTemporaryFile('source-owned-files.txt');
    ExtractTemporaryFile('current-owned-files.txt');
    ExtractTemporaryFile('patch-payload-files.txt');
    ExtractTemporaryFile('patch-transaction.txt');
    if PatchSourceRecords = nil then begin
      PatchSourceRecords := OwnedNewList;
      PatchTargetRecords := OwnedNewList;
      PatchPayloadRecords := OwnedNewList;
    end;
    if (not OwnedReadManifest(ExpandConstant('{tmp}\source-owned-files.txt'), 'current', PatchSourceRecords)) or
      (not OwnedReadManifest(ExpandConstant('{tmp}\current-owned-files.txt'), 'current', PatchTargetRecords)) or
      (not OwnedReadManifest(ExpandConstant('{tmp}\patch-payload-files.txt'), 'pending', PatchPayloadRecords)) then
      Exit;
    Marker := OwnedTarget(PatchRootPath, PatchMarkerName);
    Recovery := OwnedGetAttributes(Marker) <> OwnedInvalidAttributes;
    Manifest := OwnedTarget(PatchRootPath, OwnedCurrentName);
    if Recovery then begin
      if (Version <> '{#PatchFromVersion}') and (Version <> '{#AppVersion}') then
        Exit;
      if (not OwnedHashFile(Marker, Hash)) or (Hash <> '{#PatchTransactionSHA256}') then
        Exit;
      if OwnedGetAttributes(Manifest) <> OwnedInvalidAttributes then
        if (not OwnedHashFile(Manifest, Hash)) or
          ((Hash <> '{#PatchSourceSHA256}') and (Hash <> '{#PatchTargetSHA256}')) then
          Exit;
      if not PatchKnownRecoveryState then
        Exit;
      Log('Patch: verified a known interrupted transaction; retrying its sparse payload.');
    end
    else begin
      if Version <> '{#PatchFromVersion}' then
        Exit;
      if (not OwnedHashFile(Manifest, Hash)) or (Hash <> '{#PatchSourceSHA256}') then
        Exit;
      if not PatchVerifyRecords(PatchSourceRecords) then
        Exit;
      // Newly introduced paths must be absent; never overwrite unrelated user files.
      for I := 0 to PatchPayloadRecords.Count - 1 do begin
        Path := OwnedRecordPath(PatchPayloadRecords[I]);
        if (not PatchContainsPath(PatchSourceRecords, Path)) and
          (OwnedGetAttributes(OwnedTarget(PatchRootPath, Path)) <> OwnedInvalidAttributes) then
          Exit;
      end;
      if not PatchWriteMarker then begin
        Result := 'Could not save the patch recovery marker. Close other programs and retry.';
        Exit;
      end;
    end;
    Result := '';
  finally
    OwnedReleaseGuards(Guards);
  end;
end;

function PatchVerifyInstalledTarget: Boolean;
var
  Hash: String;
begin
  // Inno callbacks can swallow exceptions. An explicit failure flag controls exit/launch.
  PatchVerificationFailed := True;
  try
#ifdef IsLifecycleFixture
#ifdef PatchTestRaiseVerification
    RaiseException('Synthetic target hash I/O failure.');
#endif
#endif
    Result := PatchVerifyRecords(PatchTargetRecords);
    if Result then
      Result := OwnedHashFile(OwnedTarget(PatchRootPath, OwnedCurrentName), Hash) and
        (Hash = '{#PatchTargetSHA256}');
  except
    Log('Patch verification could not finish: ' + GetExceptionMessage);
    Result := False;
  end;
#ifdef IsLifecycleFixture
#ifdef PatchTestFailVerification
  Result := False;
#endif
#endif
  PatchVerificationFailed := not Result;
  if not Result then begin
    Log('Patch target verification failed. Recovery marker retained; application launch disabled.');
    SuppressibleMsgBox('The patch needs repair. Run this patch again or use the full FPVS Toolbox installer. Windows may already show the new version, but the application files could not be verified.',
      mbError, MB_OK, IDOK);
  end;
end;

function GetCustomSetupExitCode: Integer;
begin
  Result := 0;
  if PatchVerificationFailed then
    Result := 12;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if (CurPageID = wpFinished) and PatchVerificationFailed then begin
    WizardForm.FinishedHeadingLabel.Caption := 'FPVS Toolbox update needs repair';
    WizardForm.FinishedLabel.Caption := 'The application files could not be verified. Run this patch again or use the full installer before opening FPVS Toolbox.';
    WizardForm.RunList.Visible := False;
  end;
end;

procedure PatchFinish;
var
  Handle: THandle;
  Guards: TOwnedHandles;
  Missing: Boolean;
  Stream: THandleStream;
  Hash: String;
  DeleteFlag: Byte;
begin
  // Delete only our authenticated transaction marker, through the same hashed handle.
  if not OwnedOpenRegular(OwnedTarget(PatchRootPath, PatchMarkerName), True,
    Handle, Guards, Missing) then
    Exit;
  try
    Stream := THandleStream.Create(Handle);
    try
      Hash := Lowercase(GetSHA256OfStream(Stream));
    finally
      Stream.Free;
    end;
    if Hash = '{#PatchTransactionSHA256}' then begin
      DeleteFlag := 1;
      if not OwnedSetDisposition(Handle, 4, DeleteFlag, 1) then
        Log('Patch: completed recovery marker remains for a safe retry.');
    end;
  finally
    OwnedCloseHandle(Handle);
    OwnedReleaseGuards(Guards);
  end;
end;
