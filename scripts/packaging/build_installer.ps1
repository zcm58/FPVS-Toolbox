param(
    [string]$InnoCompiler,
    [switch]$SkipSmoke,
    [switch]$AllowVisibleGui,
    [string]$Python,
    [string[]]$BaselineInventory = @(),
    [string[]]$BaselineInventorySha256 = @()
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$SpecPath = Join-Path $RepoRoot "scripts\packaging\FPVS Toolbox Setup Script.iss"
$BundleExePath = Join-Path $RepoRoot "dist\FPVS_Toolbox\FPVS_Toolbox.exe"
$BundleInternalPath = Join-Path $RepoRoot "dist\FPVS_Toolbox\_internal"
$InstallerOutputDir = Join-Path $RepoRoot "installers"
$SmokePackagedAppScript = Join-Path $PSScriptRoot "smoke_packaged_app.ps1"

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

function Get-AppVersion {
    $configPath = Join-Path $RepoRoot "src\config.py"
    $versionLine = Select-String -Path $configPath -Pattern '^FPVS_TOOLBOX_VERSION:\s*str\s*=\s*"([^"]+)"' |
        Select-Object -First 1
    if ($null -eq $versionLine) {
        throw "Could not find FPVS_TOOLBOX_VERSION in src\config.py."
    }
    return $versionLine.Matches[0].Groups[1].Value
}

function Assert-BundleInput {
    if (-not (Test-Path -LiteralPath $BundleExePath)) {
        throw "Expected PyInstaller bundle was not found. Run .\scripts\packaging\build_exe.ps1 first."
    }
    if (-not (Test-Path -LiteralPath $BundleInternalPath)) {
        throw "Expected PyInstaller bundle internals were not found: $BundleInternalPath"
    }
}

function Invoke-PackagedSmoke {
    if (-not (Test-Path -LiteralPath $SmokePackagedAppScript)) {
        throw "Packaged app smoke script was not found: $SmokePackagedAppScript"
    }
    & $SmokePackagedAppScript -ExePath $BundleExePath -ExpectedVersion (Get-AppVersion) -AllowVisibleGui:$AllowVisibleGui
}

function Resolve-InnoCompiler {
    param([string]$ConfiguredPath)

    if ($ConfiguredPath) {
        if (-not (Test-Path -LiteralPath $ConfiguredPath)) {
            throw "Inno Setup compiler was not found at: $ConfiguredPath"
        }
        return (Resolve-Path -LiteralPath $ConfiguredPath).Path
    }

    if ($env:ISCC_EXE) {
        if (-not (Test-Path -LiteralPath $env:ISCC_EXE)) {
            throw "ISCC_EXE points to a missing file: $env:ISCC_EXE"
        }
        return (Resolve-Path -LiteralPath $env:ISCC_EXE).Path
    }

    $command = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
    if ($null -ne $command) {
        return $command.Source
    }

    $candidatePaths = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles}\Inno Setup 6\ISCC.exe",
        "${env:LOCALAPPDATA}\Programs\Inno Setup 6\ISCC.exe"
    )
    foreach ($candidatePath in $candidatePaths) {
        if ($candidatePath -and (Test-Path -LiteralPath $candidatePath)) {
            return (Resolve-Path -LiteralPath $candidatePath).Path
        }
    }

    throw (
        "Inno Setup compiler was not found. Install Inno Setup 6, add ISCC.exe to PATH, " +
        "set ISCC_EXE, or pass -InnoCompiler with the full ISCC.exe path."
    )
}

Push-Location $RepoRoot
try {
    if (-not (Test-Path -LiteralPath $SpecPath)) {
        throw "Inno Setup script was not found: $SpecPath"
    }
    Assert-BundleInput
    if (-not $Python) {
        $Python = @('.venv1/Scripts/python.exe', '.venv/Scripts/python.exe') |
            ForEach-Object { Join-Path $RepoRoot $_ } |
            Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
        if (-not $Python) { $Python = 'python' }
    }
    if ($BaselineInventory.Count -ne $BaselineInventorySha256.Count) { throw 'Each baseline requires its authenticated SHA-256.' }
    & (Join-Path $PSScriptRoot 'build_updater.ps1') -Python $Python -AllowVisibleGui:$AllowVisibleGui
    if ($LASTEXITCODE -ne 0) { throw 'Independent updater build failed.' }
    if (-not $SkipSmoke) {
        Write-Output "Running packaged app smoke check before installer build..."
        Invoke-PackagedSmoke
    } else {
        Write-Warning 'Packaged app smoke explicitly skipped. This is an unverified development installer, not release validation.'
    }

    $appVersion = Get-AppVersion
    $windowsVersion = & $Python (Join-Path $PSScriptRoot 'updater_metadata.py') --windows-version $appVersion
    if ($LASTEXITCODE -ne 0) { throw 'Could not derive the numeric Windows installer version.' }
    $inventoryRoot = Join-Path $RepoRoot 'build/installer-inventory'
    Invoke-Native -File $Python -Arguments @(
        (Join-Path $PSScriptRoot 'build_installer_inventory.py'),
        '--bundle-root', (Join-Path $RepoRoot 'dist/FPVS_Toolbox'),
        '--app-version', $appVersion, '--output-dir', $inventoryRoot
    )
    $isccPath = Resolve-InnoCompiler -ConfiguredPath $InnoCompiler
    New-Item -ItemType Directory -Force -Path $InstallerOutputDir | Out-Null

    Invoke-Native -File $isccPath -Arguments @(
        "/DAppVersion=$appVersion",
        "/DWindowsVersion=$windowsVersion",
        "/DOwnedInventoryRoot=$inventoryRoot",
        "/O$InstallerOutputDir",
        "/FFPVSToolbox-$appVersion-setup",
        $SpecPath
    )

    $installerPath = Join-Path $InstallerOutputDir "FPVSToolbox-$appVersion-setup.exe"
    if (-not (Test-Path -LiteralPath $installerPath)) {
        throw "Expected installer was not created: $installerPath"
    }

    Write-Output ""
    $patchScript = Join-Path $PSScriptRoot 'build_patch.py'
    $manifestArgs = @($patchScript, 'manifest', '--target-version', $appVersion, '--installer-dir', $InstallerOutputDir)
    for ($index = 0; $index -lt $BaselineInventory.Count; $index++) {
        $patchRoot = Join-Path $inventoryRoot ('patch-' + [guid]::NewGuid().ToString('N'))
        Invoke-Native -File $Python -Arguments @(
            $patchScript, 'prepare', '--baseline-inventory', $BaselineInventory[$index],
            '--source-inventory-sha256', $BaselineInventorySha256[$index],
            '--bundle-root', (Join-Path $RepoRoot 'dist/FPVS_Toolbox'),
            '--target-inventory', (Join-Path $inventoryRoot 'current-owned-files.txt'),
            '--target-version', $appVersion, '--output-dir', $patchRoot
        )
        $patchBuild = Join-Path $patchRoot 'patch-build.json'
        $patch = Get-Content -LiteralPath $patchBuild -Raw | ConvertFrom-Json
        Invoke-Native -File $isccPath -Arguments @(
            "/DAppVersion=$appVersion", "/DWindowsVersion=$windowsVersion", "/DOwnedInventoryRoot=$inventoryRoot",
            "/DPatchFromVersion=$($patch.from_version)", "/DPatchRoot=$patchRoot",
            "/DPatchSourceSHA256=$($patch.source_inventory_sha256)",
            "/DPatchTargetSHA256=$($patch.target_inventory_sha256)",
            "/DPatchTransactionSHA256=$($patch.transaction_sha256)",
            "/O$InstallerOutputDir", "/F$([IO.Path]::GetFileNameWithoutExtension($patch.asset_name))", $SpecPath
        )
        $manifestArgs += @('--patch-build', $patchBuild)
    }
    Invoke-Native -File $Python -Arguments $manifestArgs
    Write-Output "FPVS Toolbox installer built successfully:"
    Write-Output "  $installerPath"
}
finally {
    Pop-Location
}
