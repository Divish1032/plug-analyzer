# Build the unsigned internal Windows x64 standalone app and Inno Setup installer.
[CmdletBinding()]
param(
    [switch]$Clean,
    [switch]$SkipTests,
    [string]$ProtocolVersion = "candidate-v1-unlocked",
    [string]$AlgorithmVersion = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Fail([string]$Message) {
    throw "Windows release build failed: $Message"
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = [IO.Path]::GetFullPath((Join-Path $ScriptDir ".."))
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$EntryPoint = Join-Path $ScriptDir "gui_entrypoint.py"

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    Fail "this script must run on Windows"
}
if (-not [Environment]::Is64BitOperatingSystem -or -not [Environment]::Is64BitProcess) {
    Fail "this target must be built from a 64-bit process on Windows x64"
}
if ($env:PROCESSOR_ARCHITECTURE -ne "AMD64") {
    Fail "this target must be built on native Windows x64, not Arm64 or x86"
}
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    Fail "missing $Python; run: uv sync --frozen --extra dev --extra packaging"
}
if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot "uv.lock") -PathType Leaf)) {
    Fail "uv.lock is required for a reproducible build"
}
if (-not (Test-Path -LiteralPath $EntryPoint -PathType Leaf)) {
    Fail "missing packaging entry point: $EntryPoint"
}
if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot "src\plug_analyzer\app.py") -PathType Leaf)) {
    Fail "GUI entry point is not implemented yet"
}

& $Python -c "import nuitka" 2>$null
if ($LASTEXITCODE -ne 0) {
    Fail "Nuitka is missing; run: uv sync --frozen --extra dev --extra packaging"
}
$PythonBits = & $Python -c "import struct; print(struct.calcsize('P') * 8)"
if ($LASTEXITCODE -ne 0 -or $PythonBits.Trim() -ne "64") {
    Fail "the project .venv Python is not 64-bit"
}
$Version = & $Python -c "import pathlib,sys,tomllib; print(tomllib.loads(pathlib.Path(sys.argv[1]).read_text())['project']['version'])" (Join-Path $ProjectRoot "pyproject.toml")
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($Version)) {
    Fail "could not read the version from pyproject.toml"
}
$Version = $Version.Trim()
if ([string]::IsNullOrWhiteSpace($AlgorithmVersion)) {
    $AlgorithmVersion = $Version
}
if ([string]::IsNullOrWhiteSpace($ProtocolVersion)) {
    Fail "ProtocolVersion cannot be empty"
}

$BuildParent = [IO.Path]::GetFullPath((Join-Path $ProjectRoot "build\release"))
$DistParent = [IO.Path]::GetFullPath((Join-Path $ProjectRoot "dist\release"))
$BuildDir = [IO.Path]::GetFullPath((Join-Path $BuildParent "$Version\windows-x64"))
$ReleaseDir = [IO.Path]::GetFullPath((Join-Path $DistParent "$Version\windows-x64"))
$NuitkaOutput = Join-Path $BuildDir "nuitka"
$IconPng = Join-Path $BuildDir "PlugAnalyzer.png"
$IconIco = Join-Path $BuildDir "PlugAnalyzer.ico"

function Prepare-VersionedDirectory([string]$Target) {
    $FullTarget = [IO.Path]::GetFullPath($Target)
    $BuildPrefix = $BuildParent.TrimEnd('\') + '\'
    $DistPrefix = $DistParent.TrimEnd('\') + '\'
    $Allowed = $FullTarget.StartsWith($BuildPrefix, [StringComparison]::OrdinalIgnoreCase) -or
        $FullTarget.StartsWith($DistPrefix, [StringComparison]::OrdinalIgnoreCase)
    if (-not $Allowed -or $FullTarget -eq $BuildParent -or $FullTarget -eq $DistParent) {
        Fail "refusing to modify a path outside the versioned release roots: $FullTarget"
    }
    if (Test-Path -LiteralPath $FullTarget) {
        if (-not $Clean) {
            Fail "$FullTarget already exists; rerun with -Clean to replace it"
        }
        Remove-Item -LiteralPath $FullTarget -Recurse -Force
    }
    New-Item -ItemType Directory -Path $FullTarget | Out-Null
}

$InnoCandidates = @()
$InnoCommand = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
if ($null -ne $InnoCommand) {
    $InnoCandidates += $InnoCommand.Source
}
if (${env:ProgramFiles(x86)}) {
    $InnoCandidates += Join-Path ${env:ProgramFiles(x86)} "Inno Setup 7\ISCC.exe"
    $InnoCandidates += Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"
}
if ($env:ProgramFiles) {
    $InnoCandidates += Join-Path $env:ProgramFiles "Inno Setup 7\ISCC.exe"
    $InnoCandidates += Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe"
}
$Iscc = $InnoCandidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
if ([string]::IsNullOrWhiteSpace($Iscc)) {
    Fail "Inno Setup 6.3+ compiler (ISCC.exe) was not found"
}

Set-Location $ProjectRoot
Prepare-VersionedDirectory $BuildDir
Prepare-VersionedDirectory $ReleaseDir

if (-not $SkipTests) {
    $PreviousQtPlatform = $env:QT_QPA_PLATFORM
    $env:QT_QPA_PLATFORM = "offscreen"
    & $Python -m pytest
    $TestExitCode = $LASTEXITCODE
    if ($null -eq $PreviousQtPlatform) {
        Remove-Item Env:\QT_QPA_PLATFORM -ErrorAction SilentlyContinue
    } else {
        $env:QT_QPA_PLATFORM = $PreviousQtPlatform
    }
    if ($TestExitCode -ne 0) { Fail "pytest failed" }
}

& $Python (Join-Path $ScriptDir "generate_third_party_notices.py") `
    --output (Join-Path $ReleaseDir "THIRD_PARTY_NOTICES.md")
if ($LASTEXITCODE -ne 0) { Fail "third-party notice generation failed" }
Copy-Item -LiteralPath (Join-Path $ProjectRoot "packaging\CLEAN_MACHINE_SMOKE_CHECKLIST.md") `
    -Destination $ReleaseDir
& $Python (Join-Path $ScriptDir "verify_release.py") `
    --artifacts-dir $ReleaseDir `
    --platform windows-x64 `
    --version $Version `
    --algorithm-version $AlgorithmVersion `
    --protocol-version $ProtocolVersion `
    --write-build-info
if ($LASTEXITCODE -ne 0) { Fail "build-information generation failed" }
& $Python (Join-Path $ScriptDir "render_app_icon.py") --png $IconPng --ico $IconIco
if ($LASTEXITCODE -ne 0) { Fail "app icon generation failed" }

$NuitkaArgs = @(
    "-m", "nuitka",
    "--standalone",
    "--assume-yes-for-downloads",
    "--report=$(Join-Path $BuildDir 'nuitka-compilation-report.xml')",
    "--enable-plugin=pyside6",
    "--enable-plugin=dill-compat",
    "--nofollow-import-to=*.tests",
    "--noinclude-pytest-mode=nofollow",
    "--windows-console-mode=disable",
    "--company-name=Plug Analyzer Team",
    "--product-name=Plug Analyzer",
    "--file-description=Local microscope Z-stack plug analysis",
    "--product-version=$Version",
    "--file-version=$Version",
    "--windows-icon-from-ico=$IconIco",
    "--output-dir=$NuitkaOutput",
    "--output-filename=PlugAnalyzer.exe",
    "--include-package=plug_analyzer",
    "--include-package-data=plug_analyzer",
    "--include-module=PySide6.QtOpenGL",
    "--include-module=PySide6.QtOpenGLWidgets",
    "--include-module=PySide6.QtSvg",
    "--include-package=pyqtgraph",
    "--include-package-data=pyqtgraph",
    "--include-package=tifffile",
    "--include-package=imagecodecs",
    "--include-package=nd2",
    "--include-package-data=nd2",
    "--include-package=zarr",
    "--include-package=dask.array",
    "--include-distribution-metadata=numpy",
    "--include-package=scipy._external.array_api_compat.numpy",
    $EntryPoint
)
$env:NUITKA_CACHE_DIR = Join-Path $BuildDir "nuitka-cache"
& $Python @NuitkaArgs
if ($LASTEXITCODE -ne 0) { Fail "Nuitka standalone build failed" }

$StandaloneDirs = @(Get-ChildItem -LiteralPath $NuitkaOutput -Directory -Filter "*.dist")
if ($StandaloneDirs.Count -ne 1) {
    Fail "expected one .dist folder in $NuitkaOutput; found $($StandaloneDirs.Count)"
}
$StandaloneDir = $StandaloneDirs[0].FullName
$PackagedExe = Join-Path $StandaloneDir "PlugAnalyzer.exe"
if (-not (Test-Path -LiteralPath $PackagedExe -PathType Leaf)) {
    Fail "standalone executable is missing: $PackagedExe"
}
$ExeBytes = [IO.File]::ReadAllBytes($PackagedExe)
if ($ExeBytes.Length -lt 64 -or $ExeBytes[0] -ne 0x4D -or $ExeBytes[1] -ne 0x5A) {
    Fail "standalone executable has an invalid DOS/PE header: $PackagedExe"
}
$PeOffset = [BitConverter]::ToInt32($ExeBytes, 0x3C)
if ($PeOffset -lt 0 -or $PeOffset + 6 -gt $ExeBytes.Length) {
    Fail "standalone executable has an invalid PE offset: $PackagedExe"
}
if ($ExeBytes[$PeOffset] -ne 0x50 -or $ExeBytes[$PeOffset + 1] -ne 0x45 -or
    $ExeBytes[$PeOffset + 2] -ne 0 -or $ExeBytes[$PeOffset + 3] -ne 0) {
    Fail "standalone executable has an invalid PE signature: $PackagedExe"
}
$Machine = [BitConverter]::ToUInt16($ExeBytes, $PeOffset + 4)
if ($Machine -ne 0x8664) {
    Fail ("standalone executable is not Windows x64 (PE machine 0x{0:X4})" -f $Machine)
}

$SmokeArguments = @("--bundle-smoke")
$RegressionTiff = Join-Path (Split-Path -Parent $ProjectRoot) "test.tif"
if (Test-Path -LiteralPath $RegressionTiff -PathType Leaf) {
    $SmokeArguments += $RegressionTiff
}
$PreviousQtPlatform = $env:QT_QPA_PLATFORM
$env:QT_QPA_PLATFORM = "offscreen"
& $PackagedExe @SmokeArguments
$SmokeExitCode = $LASTEXITCODE
if ($null -eq $PreviousQtPlatform) {
    Remove-Item Env:\QT_QPA_PLATFORM -ErrorAction SilentlyContinue
} else {
    $env:QT_QPA_PLATFORM = $PreviousQtPlatform
}
if ($SmokeExitCode -ne 0) { Fail "packaged application dependency smoke failed" }

Copy-Item -LiteralPath (Join-Path $ReleaseDir "THIRD_PARTY_NOTICES.md") -Destination $StandaloneDir
Copy-Item -LiteralPath (Join-Path $ReleaseDir "BUILD_INFO.json") -Destination $StandaloneDir
Copy-Item -LiteralPath (Join-Path $ReleaseDir "CLEAN_MACHINE_SMOKE_CHECKLIST.md") `
    -Destination $StandaloneDir
Copy-Item -LiteralPath (Join-Path $ProjectRoot "packaging\windows\PILOT_INSTALL.md") `
    -Destination (Join-Path $StandaloneDir "READ_ME_FIRST.md")

$IssPath = Join-Path $ProjectRoot "packaging\windows\PlugAnalyzer.iss"
& $Iscc "/DMyAppVersion=$Version" "/DSourceDir=$StandaloneDir" "/DSetupIcon=$IconIco" `
    "/DOutputDir=$ReleaseDir" $IssPath
if ($LASTEXITCODE -ne 0) { Fail "Inno Setup compilation failed" }

$Installer = Join-Path $ReleaseDir "Plug-Analyzer-$Version-windows-x64-Setup.exe"
if (-not (Test-Path -LiteralPath $Installer -PathType Leaf)) {
    Fail "expected installer was not produced: $Installer"
}

& $Python (Join-Path $ScriptDir "verify_release.py") `
    --artifacts-dir $ReleaseDir `
    --platform windows-x64 `
    --version $Version `
    --algorithm-version $AlgorithmVersion `
    --protocol-version $ProtocolVersion `
    --write-manifest `
    --deep
if ($LASTEXITCODE -ne 0) { Fail "release verification failed" }

Write-Host "Unsigned internal Windows release created: $Installer"
Write-Host "Verify SHA-256 values in: $(Join-Path $ReleaseDir 'SHA256SUMS.txt')"
