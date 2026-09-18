param([string]$Python, [switch]$AllowVisibleGui)
$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if (-not $Python) {
    $Python = @('.venv1/Scripts/python.exe', '.venv/Scripts/python.exe') |
        ForEach-Object { Join-Path $RepoRoot $_ } |
        Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $Python) { $Python = 'python' }
}
$work = Join-Path $RepoRoot 'build/pyinstaller-updater'
$destination = Join-Path $RepoRoot 'dist/FPVS_Toolbox/Updater'
Push-Location -LiteralPath $RepoRoot
try {
    & $Python -m PyInstaller --noconfirm --clean --workpath $work --distpath $destination scripts/packaging/FPVS_Updater.spec
    if ($LASTEXITCODE -ne 0) { throw 'Independent updater compilation failed.' }
    $exe = Join-Path $destination 'FPVS Toolbox Updater.exe'
    $report = Join-Path $work 'packaging-check.json'
    $process = Start-Process -FilePath $exe -WindowStyle Hidden -PassThru -ArgumentList @('--packaging-check', ('"' + $report + '"'))
    try {
        if (-not $process.WaitForExit(60000)) { $process.Kill(); throw 'Updater metadata check timed out.' }
        if ($process.ExitCode -ne 0) { throw 'Updater metadata check failed.' }
    } finally { $process.Dispose() }
    $actual = Get-Content -LiteralPath $report -Raw | ConvertFrom-Json
    $versionData = Join-Path $RepoRoot 'build/updater-metadata/toolbox-updater-version.json'
    $expected = Get-Content -LiteralPath $versionData -Raw | ConvertFrom-Json
    if ($actual.version -ne $expected.version -or -not $actual.frozen -or
        $actual.gui_loaded -or $actual.analysis_loaded -or $actual.protocol_version -ne 1) { throw 'Updater metadata/runtime mismatch.' }
    # Preserve the main bundle's build-time version evidence; never relabel an
    # older executable by overwriting its metadata during helper packaging.
    $internal = Join-Path $RepoRoot 'dist/FPVS_Toolbox/_internal'
    $mainVersionData = Join-Path $internal 'toolbox-updater-version.json'
    if (Test-Path -LiteralPath $mainVersionData) {
        $mainVersion = Get-Content -LiteralPath $mainVersionData -Raw | ConvertFrom-Json
        if ($mainVersion.version -ne $expected.version) { throw 'Main bundle version differs from the updater. Rebuild the main executable first.' }
    } elseif (Test-Path -LiteralPath (Join-Path $RepoRoot 'dist/FPVS_Toolbox/FPVS_Toolbox.exe')) {
        throw 'Main bundle has no build-time updater version metadata. Rebuild the main executable first.'
    }
    if ($AllowVisibleGui) {
        if ($env:QT_QPA_PLATFORM -in @('offscreen', 'minimal')) { throw 'A native visible session is required.' }
        $guiReport = Join-Path $work 'gui-smoke.json'
        $process = Start-Process -FilePath $exe -WindowStyle Normal -PassThru -ArgumentList @('--gui-smoke', ('"' + $guiReport + '"'))
        try {
            if (-not $process.WaitForExit(30000)) { $process.Kill(); throw 'Updater visible smoke timed out.' }
            if ($process.ExitCode -ne 0) { throw 'Updater visible smoke failed.' }
        } finally { $process.Dispose() }
        $gui = Get-Content -LiteralPath $guiReport -Raw | ConvertFrom-Json
        if (-not $gui.passed -or $gui.network -or $gui.installer -or
            -not $gui.standalone_repair -or -not $gui.repair_after_failure) { throw 'Updater visible smoke rejected the result.' }
    }
    Write-Output "Independent Toolbox updater built and verified: $exe"
} finally { Pop-Location }
