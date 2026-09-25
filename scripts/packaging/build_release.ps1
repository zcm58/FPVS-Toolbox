param(
    [switch]$SkipInstall,
    [string]$InnoCompiler,
    [switch]$SkipSmoke,
    [switch]$AllowVisibleGui,
    [string[]]$BaselineInventory = @(),
    [string[]]$BaselineInventorySha256 = @()
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$BuildExeScript = Join-Path $PSScriptRoot "build_exe.ps1"
$BuildInstallerScript = Join-Path $PSScriptRoot "build_installer.ps1"

function Assert-LastCommandSucceeded {
    param([Parameter(Mandatory = $true)][string]$CommandLabel)

    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $CommandLabel"
    }
}

Push-Location $RepoRoot
try {
    Write-Output "Building FPVS Toolbox executable bundle..."
    if (-not $SkipInstall) {
        Write-Output (
            "Network access may be required because the executable stage refreshes " +
            "requirements.txt before running PyInstaller. Use -SkipInstall when the " +
            "packaging environment is already prepared."
        )
    }

    if ($SkipInstall) {
        & $BuildExeScript -SkipInstall
        Assert-LastCommandSucceeded "$BuildExeScript -SkipInstall"
    }
    else {
        & $BuildExeScript
        Assert-LastCommandSucceeded $BuildExeScript
    }

    Write-Output ""
    Write-Output "Building FPVS Toolbox installer..."
    & $BuildInstallerScript -InnoCompiler $InnoCompiler -SkipSmoke:$SkipSmoke -AllowVisibleGui:$AllowVisibleGui `
        -BaselineInventory $BaselineInventory -BaselineInventorySha256 $BaselineInventorySha256
    Assert-LastCommandSucceeded $BuildInstallerScript
    Write-Output ""
    if ($SkipSmoke) {
        Write-Warning 'Development artifacts built with -SkipSmoke; packaged-app validation is still required.'
    } elseif (-not $AllowVisibleGui) {
        Write-Output 'FPVS Toolbox artifacts built with dependency checks. Visible packaged-app acceptance remains pending.'
    } else {
        Write-Output 'FPVS Toolbox release build and packaged-app smoke completed successfully.'
    }
}
finally {
    Pop-Location
}
