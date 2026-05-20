param(
    [switch]$SkipInstall,
    [string]$InnoCompiler,
    [switch]$SkipSmoke
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
    if ($InnoCompiler -and $SkipSmoke) {
        & $BuildInstallerScript -InnoCompiler $InnoCompiler -SkipSmoke
        Assert-LastCommandSucceeded "$BuildInstallerScript -InnoCompiler $InnoCompiler -SkipSmoke"
    }
    elseif ($InnoCompiler) {
        & $BuildInstallerScript -InnoCompiler $InnoCompiler
        Assert-LastCommandSucceeded "$BuildInstallerScript -InnoCompiler $InnoCompiler"
    }
    elseif ($SkipSmoke) {
        & $BuildInstallerScript -SkipSmoke
        Assert-LastCommandSucceeded "$BuildInstallerScript -SkipSmoke"
    }
    else {
        & $BuildInstallerScript
        Assert-LastCommandSucceeded $BuildInstallerScript
    }

    Write-Output ""
    Write-Output "FPVS Toolbox release build completed successfully."
}
finally {
    Pop-Location
}
