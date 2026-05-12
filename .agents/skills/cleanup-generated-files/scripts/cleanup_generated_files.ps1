param(
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..\..\..")).Path
$preservedRelPaths = @(
    ".venv1",
    ".idea",
    "src\quarantine"
)

$rootTargets = @(
    "build",
    "site",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    ".codex-pytest-tmp",
    ".codex-tmp",
    ".tmp",
    "codex_pytest_tmp",
    "test_tmp",
    "__pycache__",
    "src\fsaverage",
    "src\quarantine\Tools\LORETA\fsaverage",
    "src\fpvs_cache"
)

function Resolve-RepoPath {
    param([string]$RelativePath)

    $candidate = Join-Path $repoRoot $RelativePath
    if (-not (Test-Path -LiteralPath $candidate)) {
        return $null
    }

    $resolved = (Resolve-Path -LiteralPath $candidate).Path
    if (-not $resolved.StartsWith($repoRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing path outside repository: $resolved"
    }

    return $resolved
}

function Remove-Target {
    param(
        [string]$RelativePath,
        [string]$FullPath
    )

    if ($preservedRelPaths -contains $RelativePath) {
        throw "Refusing preserved path: $RelativePath"
    }

    if ($DryRun) {
        Write-Output "DRY-RUN $RelativePath"
        return
    }

    Remove-Item -LiteralPath $FullPath -Recurse -Force
    Write-Output "REMOVED $RelativePath"
}

function Get-PycacheDirs {
    param([string]$Directory)

    foreach ($child in Get-ChildItem -LiteralPath $Directory -Force -Directory -ErrorAction Stop) {
        $relative = $child.FullName.Substring($repoRoot.Length + 1)
        $isPreserved = $false
        foreach ($preserved in $preservedRelPaths) {
            if ($relative.Equals($preserved, [System.StringComparison]::OrdinalIgnoreCase) -or
                $relative.StartsWith("$preserved\", [System.StringComparison]::OrdinalIgnoreCase)) {
                $isPreserved = $true
                break
            }
        }

        if ($isPreserved) {
            continue
        }

        if ($child.Name -eq "__pycache__") {
            $child
            continue
        }

        Get-PycacheDirs -Directory $child.FullName
    }
}

foreach ($target in $rootTargets) {
    $resolved = Resolve-RepoPath -RelativePath $target
    if ($null -ne $resolved) {
        Remove-Target -RelativePath $target -FullPath $resolved
    }
}

foreach ($dir in Get-PycacheDirs -Directory $repoRoot) {
    $relative = $dir.FullName.Substring($repoRoot.Length + 1)
    Remove-Target -RelativePath $relative -FullPath $dir.FullName
}
