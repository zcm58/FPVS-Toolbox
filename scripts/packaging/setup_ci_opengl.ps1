param([switch]$Execute)

$ErrorActionPreference = 'Stop'
# This changes the disposable runner's graphics driver registration. Never run
# it as part of a developer build or ship these CI-only drivers in the installer.
if (-not $Execute -or $env:GITHUB_ACTIONS -cne 'true' -or $env:CI -cne 'true' -or
    $env:RUNNER_ENVIRONMENT -cne 'github-hosted' -or $env:OS -ne 'Windows_NT') {
    throw 'OpenGL driver setup requires -Execute on a disposable GitHub-hosted Windows runner.'
}
if (-not $env:RUNNER_TEMP -or -not [IO.Path]::IsPathRooted($env:RUNNER_TEMP) -or
    -not (Test-Path -LiteralPath $env:RUNNER_TEMP -PathType Container)) {
    throw 'RUNNER_TEMP must be an existing absolute directory.'
}

$version = '26.2.4'
$digest = '351fc8c8b695878ffb3eaa044b3ead08672a48b1a045e3c3e3975811df0f6695'
$url = "https://github.com/pal1000/mesa-dist-win/releases/download/$version/mesa3d-$version-release-msvc.7z"
$root = Join-Path $env:RUNNER_TEMP ('fpvs-ci-opengl-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $root | Out-Null
$archive = Join-Path $root 'mesa.7z'
$expanded = Join-Path $root 'driver'
Invoke-WebRequest -Uri $url -OutFile $archive
if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -cne $digest) {
    throw 'Pinned Mesa3D archive checksum mismatch.'
}
& 7z x $archive "-o$expanded" -y | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Could not extract the verified Mesa3D archive.' }
$deployment = Join-Path $expanded 'systemwidedeploy.cmd'
if (-not (Test-Path -LiteralPath $deployment -PathType Leaf)) { throw 'Mesa3D deployment utility is missing.' }
# Option 1 installs the desktop OpenGL driver. Keep native onscreen Qt/VTK;
# do not select OSMesa or change QT_QPA_PLATFORM/PYVISTA_OFF_SCREEN.
& $deployment '1'
if ($LASTEXITCODE -ne 0) { throw 'Mesa3D desktop OpenGL deployment failed.' }
$installed = Join-Path $env:WINDIR 'System32/mesadrv.dll'
if (-not (Test-Path -LiteralPath $installed -PathType Leaf)) { throw 'Mesa3D desktop driver was not installed.' }
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$evidence = Join-Path $repo 'build/release-acceptance'
New-Item -ItemType Directory -Force -Path $evidence | Out-Null
@{
    version = $version
    source = $url
    archive_sha256 = $digest
    installed_driver_sha256 = (Get-FileHash -LiteralPath $installed -Algorithm SHA256).Hash.ToLowerInvariant()
    purpose = 'Native onscreen software OpenGL on disposable CI; excluded from release artifacts'
} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $evidence 'graphics-driver.json')
