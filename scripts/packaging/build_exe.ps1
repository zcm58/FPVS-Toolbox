param(
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$Python = Join-Path $RepoRoot ".venv1\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    $Python = "python"
}

function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)]
        [string]$File,
        [string[]]$Arguments = @()
    )

    & $File @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $File $($Arguments -join ' ')"
    }
}

function Remove-RepoOutput {
    param([Parameter(Mandatory = $true)][string]$RelativePath)

    $target = Join-Path $RepoRoot $RelativePath
    if (-not (Test-Path -LiteralPath $target)) {
        return
    }

    $resolvedRepo = (Resolve-Path -LiteralPath $RepoRoot).Path
    $resolvedTarget = (Resolve-Path -LiteralPath $target).Path
    if (-not $resolvedTarget.StartsWith($resolvedRepo, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove path outside repo: $resolvedTarget"
    }

    Remove-Item -LiteralPath $resolvedTarget -Recurse -Force
}

function Get-AppVersion {
    $configPath = Join-Path $RepoRoot "src\config.py"
    $versionLine = Select-String -Path $configPath -Pattern '^FPVS_TOOLBOX_VERSION:\s*str\s*=\s*"([^"]+)"' |
        Select-Object -First 1
    if ($null -eq $versionLine) {
        throw "Could not find FPVS_TOOLBOX_VERSION in src\config.py."
    }
    return $versionLine.Matches[0].Groups[1].Value
}

function Assert-SourceVersion {
    param([Parameter(Mandatory = $true)][string]$ExpectedVersion)

    $sourceVersion = & $Python -c "import sys; sys.path.insert(0, 'src'); from config import FPVS_TOOLBOX_VERSION; sys.stdout.write(FPVS_TOOLBOX_VERSION)"
    if ($LASTEXITCODE -ne 0) {
        throw "Could not import FPVS_TOOLBOX_VERSION from src\config.py."
    }
    if ($sourceVersion.Trim() -ne $ExpectedVersion) {
        throw "Version drift before PyInstaller build. config.py=$ExpectedVersion, imported=$($sourceVersion.Trim())."
    }
}

function Assert-BundledMetadataVersion {
    param([Parameter(Mandatory = $true)][string]$ExpectedVersion)

    $bundleRoot = Join-Path $RepoRoot "dist\FPVS_Toolbox"
    $metadataDirs = @(
        Get-ChildItem -Path $bundleRoot -Recurse -Directory -Filter "fpvs_toolbox-*.dist-info" -ErrorAction SilentlyContinue
    )
    if ($metadataDirs.Count -eq 0) {
        Write-Output "No bundled fpvs_toolbox dist-info directory found; source version was verified before packaging."
        return
    }
    if ($metadataDirs.Count -ne 1) {
        throw "Expected at most one bundled fpvs_toolbox dist-info directory; found $($metadataDirs.Count)."
    }

    $metadataPath = Join-Path $metadataDirs[0].FullName "METADATA"
    $versionLine = Select-String -Path $metadataPath -Pattern '^Version: (.+)$' |
        Select-Object -First 1
    if ($null -eq $versionLine) {
        throw "Bundled fpvs_toolbox metadata has no Version field: $metadataPath"
    }
    $metadataVersion = $versionLine.Matches[0].Groups[1].Value.Trim()
    if ($metadataVersion -ne $ExpectedVersion) {
        throw "Bundled fpvs_toolbox metadata version drift. config.py=$ExpectedVersion, bundled metadata=$metadataVersion."
    }
}

Push-Location $RepoRoot
try {
    $pythonExecutable = & $Python -c "import sys; sys.stdout.write(sys.executable)"
    if ($LASTEXITCODE -ne 0) {
        throw "Could not run Python executable: $Python"
    }
    Write-Output "Using Python: $pythonExecutable"

    if (-not $SkipInstall) {
        Invoke-Native -File $Python -Arguments @("-m", "pip", "install", "-r", "requirements.txt")
    }

    $appVersion = Get-AppVersion
    Assert-SourceVersion -ExpectedVersion $appVersion

    Remove-RepoOutput "build\pyinstaller"
    Remove-RepoOutput "dist\FPVS_Toolbox"

    Invoke-Native -File $Python -Arguments @(
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--workpath",
        "build\pyinstaller",
        "--distpath",
        "dist",
        "scripts\packaging\FPVS_Toolbox.spec"
    )

    $exePath = Join-Path $RepoRoot "dist\FPVS_Toolbox\FPVS_Toolbox.exe"
    if (-not (Test-Path -LiteralPath $exePath)) {
        throw "Expected packaged executable was not created: $exePath"
    }
    Assert-BundledMetadataVersion -ExpectedVersion $appVersion

    Write-Output ""
    Write-Output "FPVS Toolbox executable built successfully:"
    Write-Output "  $exePath"
}
finally {
    Pop-Location
}
