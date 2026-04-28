$ErrorActionPreference = "Stop"

function Fail([string]$Message, [int]$ExitCode = 1) {
    Write-Error $Message
    exit $ExitCode
}

try {
    $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    $repoRoot = Split-Path -Parent $scriptDir
    $pythonExe = Join-Path $repoRoot ".venv1\Scripts\python.exe"
    $mkdocsConfig = Join-Path $repoRoot "mkdocs.yml"

    Write-Host "Starting MkDocs GitHub Pages deploy..."
    Write-Host "Repo root: $repoRoot"

    if (-not (Test-Path -LiteralPath $mkdocsConfig)) {
        Fail "mkdocs.yml was not found at '$mkdocsConfig'."
    }

    if (-not (Test-Path -LiteralPath $pythonExe)) {
        Fail "Expected repo Python was not found at '$pythonExe'."
    }

    $gitCmd = Get-Command git -ErrorAction SilentlyContinue
    if (-not $gitCmd) {
        Fail "git is not available on PATH."
    }

    Push-Location $repoRoot
    try {
        $originUrl = git remote get-url origin 2>$null
        if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($originUrl)) {
            Fail "Git remote 'origin' is not configured for this repository."
        }

        Write-Host "Python: $pythonExe"
        Write-Host "MkDocs config: $mkdocsConfig"
        Write-Host "Git remote origin: $originUrl"
        Write-Host "Checking MkDocs availability..."

        $env:NO_MKDOCS_2_WARNING = "1"

        & $pythonExe -c "import mkdocs" 2>$null
        if ($LASTEXITCODE -ne 0) {
            Fail "MkDocs is not installed in '.venv1'. Install it with: `"$pythonExe`" -m pip install mkdocs mkdocs-material"
        }

        & $pythonExe -c "import json, mkdocs.utils, sys; sys.exit(0 if 'material' in mkdocs.utils.get_theme_names() else 1)" 2>$null
        if ($LASTEXITCODE -ne 0) {
            Fail "The MkDocs Material theme is not installed in '.venv1'. Install it with: `"$pythonExe`" -m pip install mkdocs-material"
        }

        Write-Host "Running: python -m mkdocs gh-deploy --force"

        & $pythonExe -m mkdocs gh-deploy --force
        if ($LASTEXITCODE -ne 0) {
            Fail "MkDocs deploy failed."
        }

        Write-Host "MkDocs GitHub Pages deploy completed successfully."
        exit 0
    }
    finally {
        Pop-Location
    }
}
catch {
    Fail $_.Exception.Message
}
