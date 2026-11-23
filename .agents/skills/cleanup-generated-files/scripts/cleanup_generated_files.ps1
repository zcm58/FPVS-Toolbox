param(
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "../../../..")).Path
$separator = [System.IO.Path]::DirectorySeparatorChar
$repoPrefix = "$repoRoot$separator"
$pathComparison = [System.StringComparison]::Ordinal
$gitPathspec = ":(literal)"
if ($separator -eq '\') {
    $pathComparison = [System.StringComparison]::OrdinalIgnoreCase
    $gitPathspec = ":(icase,literal)"
}
$preservedDirNames = @(".git", ".venv", ".venv1", ".fpvs_cache", ".idea")
$preservedRelPaths = @(
    "src/quarantine",
    "src/Standalone_Scripts",
    "tests/standalone_scripts"
)

$rootTargets = @(
    "build",
    "site",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    ".codex-pytest-tmp",
    ".codex-tmp",
    ".codex_pytest_phase1_a",
    ".codex_pytest_phase1_b",
    ".codex_pytest_tmp",
    ".tmp",
    "codex_pytest_tmp",
    "test_tmp_processing_output.txt",
    "test_tmp",
    "__pycache__",
    "src/fsaverage",
    "src/quarantine/Tools/LORETA/fsaverage",
    "src/fpvs_cache"
)

function Test-ProjectDirectory {
    param([string]$Directory)
    return Test-Path -LiteralPath (Join-Path $Directory "project.json")
}

function Test-PreservedDirectory {
    param([System.IO.DirectoryInfo]$Directory)
    return ($preservedDirNames -contains $Directory.Name) -or
        (Test-ProjectDirectory -Directory $Directory.FullName) -or
        (Test-Path -LiteralPath (Join-Path $Directory.FullName "pyvenv.cfg")) -or
        (Test-Path -LiteralPath (Join-Path $Directory.FullName ".git"))
}

function Test-RedirectedItem {
    param([System.IO.FileSystemInfo]$Item)
    return [bool]($Item.Attributes -band [System.IO.FileAttributes]::ReparsePoint)
}

function Resolve-RepoPath {
    param([string]$RelativePath)

    $candidate = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $RelativePath))
    if (-not $candidate.StartsWith($repoPrefix, $pathComparison)) {
        throw "Refusing path outside repository: $candidate"
    }

    $current = $repoRoot
    foreach ($part in $RelativePath.Split('/')) {
        $current = Join-Path $current $part
        if (-not (Test-Path -LiteralPath $current)) {
            return $null
        }
        $item = Get-Item -LiteralPath $current -Force
        if ((Test-RedirectedItem -Item $item) -or ($item.PSIsContainer -and (Test-PreservedDirectory -Directory $item))) {
            Write-Warning "Skipping protected or redirected path: $RelativePath"
            return $null
        }
    }

    return $candidate
}

function Test-SafeTargetTree {
    param([System.IO.FileSystemInfo]$Item)
    if (Test-RedirectedItem -Item $Item) {
        return $false
    }
    if (-not $Item.PSIsContainer) {
        return $true
    }
    if (Test-PreservedDirectory -Directory $Item) {
        return $false
    }
    foreach ($child in Get-ChildItem -LiteralPath $Item.FullName -Force) {
        if (-not (Test-SafeTargetTree -Item $child)) {
            return $false
        }
    }
    return $true
}

function Test-SkippedTraversalPath {
    param([string]$RelativePath)

    foreach ($skipped in ($preservedRelPaths + $rootTargets)) {
        if ($RelativePath.Equals($skipped, $pathComparison) -or
            $RelativePath.StartsWith("$skipped/", $pathComparison)) {
            return $true
        }
    }

    return $false
}

function Get-PycacheDirs {
    param([string]$Directory)

    foreach ($child in Get-ChildItem -LiteralPath $Directory -Force -Directory -ErrorAction Stop) {
        $relative = $child.FullName.Substring($repoPrefix.Length).Replace($separator, '/')
        if ((Test-SkippedTraversalPath -RelativePath $relative) -or
            (Test-RedirectedItem -Item $child) -or
            (Test-PreservedDirectory -Directory $child)) {
            continue
        }

        if ($child.Name -eq "__pycache__") {
            $relative
            continue
        }

        Get-PycacheDirs -Directory $child.FullName
    }
}

if (Test-ProjectDirectory -Directory $repoRoot) {
    throw "Refusing repository cleanup at an FPVS project root: $repoRoot"
}

$candidates = $rootTargets + @(Get-PycacheDirs -Directory $repoRoot)
$approved = @(foreach ($target in $candidates) {
    $fullPath = Resolve-RepoPath -RelativePath $target
    if ($null -eq $fullPath) {
        continue
    }
    $tracked = @(& git -C $repoRoot ls-files --cached -- "$gitPathspec$target")
    if ($LASTEXITCODE -ne 0) {
        throw "Could not check whether the cleanup target contains tracked data: $target"
    }
    if ($tracked.Count -gt 0 -or -not (Test-SafeTargetTree -Item (Get-Item -LiteralPath $fullPath -Force))) {
        Write-Warning "Skipping target containing tracked, protected, or redirected data: $target"
        continue
    }
    $target
})

foreach ($target in $approved) {
    $fullPath = Resolve-RepoPath -RelativePath $target
    if ($null -eq $fullPath) {
        continue
    }
    if ($DryRun) {
        Write-Output "DRY-RUN $target"
        continue
    }
    Remove-Item -LiteralPath $fullPath -Recurse -Force
    Write-Output "REMOVED $target"
}
