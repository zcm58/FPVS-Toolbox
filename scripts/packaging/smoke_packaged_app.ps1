param(
    [string]$ExePath,
    [string]$ExpectedVersion,
    [switch]$AllowVisibleGui,
    [ValidateRange(1, 900)][int]$TimeoutSeconds = 180
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if (-not $ExePath) {
    $ExePath = Join-Path $RepoRoot 'dist/FPVS_Toolbox/FPVS_Toolbox.exe'
}
if (-not (Test-Path -LiteralPath $ExePath -PathType Leaf)) {
    throw "Packaged executable was not found: $ExePath"
}
$ExePath = (Resolve-Path -LiteralPath $ExePath).Path
if (-not $ExpectedVersion) {
    $versionLine = Select-String -LiteralPath (Join-Path $RepoRoot 'src/config.py') `
        -Pattern '^FPVS_TOOLBOX_VERSION:\s*str\s*=\s*"([^"]+)"' | Select-Object -First 1
    if ($null -eq $versionLine) { throw 'Could not find the Toolbox source version.' }
    $ExpectedVersion = $versionLine.Matches[0].Groups[1].Value
}
if ($AllowVisibleGui -and $env:QT_QPA_PLATFORM -match '^(offscreen|minimal)(:|$)') {
    throw 'Packaged GUI verification requires the native visible Qt platform.'
}
$reportDir = Join-Path $RepoRoot 'build/packaged-smoke'
New-Item -ItemType Directory -Force -Path $reportDir | Out-Null

function Invoke-PackagedProbe {
    param([Parameter(Mandatory = $true)][bool]$Visible)

    $mode = if ($Visible) { 'visible' } else { 'dependencies' }
    $reportPath = Join-Path $reportDir ("$mode-" + [guid]::NewGuid().ToString('N') + '.json')
    $argument = if ($Visible) { '--packaged-smoke-output' } else { '--packaging-check' }
    $windowStyle = if ($Visible) { 'Normal' } else { 'Hidden' }
    $previousQtOptIn = $env:FPVS_ALLOW_QT_TESTS
    try {
        if ($Visible) { $env:FPVS_ALLOW_QT_TESTS = '1' }
        $process = Start-Process -FilePath $ExePath -WindowStyle $windowStyle -PassThru `
            -ArgumentList @($argument, ('"' + $reportPath + '"'))
    } finally { $env:FPVS_ALLOW_QT_TESTS = $previousQtOptIn }
    try {
        if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
            $process.Kill()
            throw "Packaged $mode smoke timed out after $TimeoutSeconds seconds."
        }
        if (-not (Test-Path -LiteralPath $reportPath -PathType Leaf)) {
            throw "Packaged $mode smoke did not produce a report (exit $($process.ExitCode))."
        }
        $report = Get-Content -LiteralPath $reportPath -Raw | ConvertFrom-Json
        if ($process.ExitCode -ne 0 -or $report.passed -ne $true) {
            throw "Packaged $mode smoke failed: $($report.error). Report: $reportPath"
        }
    } finally { $process.Dispose() }
    if ($report.schema_version -ne 1 -or $report.mode -ne $mode -or
        $report.frozen -ne $true -or $report.version -cne $ExpectedVersion -or
        $report.metadata_version -cne $ExpectedVersion -or
        $report.executable -ne $ExePath -or $report.network -ne $false -or
        $report.installer -ne $false -or $report.gui_exercised -ne $Visible) {
        throw "Packaged $mode smoke identity/result mismatch. Report: $reportPath"
    }
    if ($Visible) {
        if ($report.main_window_visible -ne $true -or $report.main_window_closed -ne $true -or
            $report.application_version -cne $ExpectedVersion) {
            throw "Packaged Main Window smoke did not confirm its visible version. Report: $reportPath"
        }
    } elseif ($report.qt_widgets_loaded -ne $false) {
        throw "Dependency-only smoke unexpectedly loaded QtWidgets. Report: $reportPath"
    }
    Write-Output "Packaged $mode smoke passed: $reportPath"
}

Invoke-PackagedProbe -Visible $false
if ($AllowVisibleGui) {
    Invoke-PackagedProbe -Visible $true
} else {
    Write-Output 'Visible Main Window validation is pending; rerun with -AllowVisibleGui in an approved native session.'
}
