# Verify and locally install an already-built Windows x64 installer.
[CmdletBinding(DefaultParameterSetName = "Deploy")]
param(
    [Parameter(ParameterSetName = "Deploy")]
    [switch]$Silent,
    [Parameter(ParameterSetName = "Verify")]
    [switch]$VerifyOnly,
    [Parameter(ParameterSetName = "Print")]
    [switch]$PrintArtifact
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Fail([string]$Message) {
    throw "Windows deployment failed: $Message"
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = [IO.Path]::GetFullPath((Join-Path $ScriptDir ".."))
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    Fail "this script must run on Windows"
}
if (-not [Environment]::Is64BitOperatingSystem -or $env:PROCESSOR_ARCHITECTURE -ne "AMD64") {
    Fail "this deployment target requires native Windows x64"
}
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    Fail "missing $Python; run: make setup"
}

$Pyproject = Join-Path $ProjectRoot "pyproject.toml"
$Version = & $Python -c "import pathlib,sys,tomllib; print(tomllib.loads(pathlib.Path(sys.argv[1]).read_text())['project']['version'])" $Pyproject
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($Version)) {
    Fail "could not read the application version"
}
$Version = $Version.Trim()
$ReleaseDir = Join-Path $ProjectRoot "dist\release\$Version\windows-x64"
$Installer = Join-Path $ReleaseDir "Plug-Analyzer-$Version-windows-x64-Setup.exe"
if (-not (Test-Path -LiteralPath $Installer -PathType Leaf)) {
    Fail "missing $Installer; run: make build-windows"
}

if ($PrintArtifact) {
    Write-Output $Installer
    exit 0
}

& $Python (Join-Path $ScriptDir "verify_release.py") `
    --artifacts-dir $ReleaseDir `
    --platform windows-x64 `
    --version $Version `
    --deep
if ($LASTEXITCODE -ne 0) { Fail "release verification failed" }
if ($VerifyOnly) {
    Write-Host "Verified Windows release: $Installer"
    exit 0
}

$Running = Get-Process -Name "PlugAnalyzer" -ErrorAction SilentlyContinue
if ($null -ne $Running) {
    Fail "Plug Analyzer is running; close it before deployment"
}

$InstallerArguments = @("/NORUN")
if ($Silent) {
    $InstallerArguments += @("/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS")
}
$Process = Start-Process -FilePath $Installer -ArgumentList $InstallerArguments -PassThru -Wait
if ($Process.ExitCode -ne 0) {
    Fail "installer exited with code $($Process.ExitCode)"
}

$InstalledExe = Join-Path $env:LOCALAPPDATA "Programs\Plug Analyzer\PlugAnalyzer.exe"
if (-not (Test-Path -LiteralPath $InstalledExe -PathType Leaf)) {
    Fail "installed executable was not found: $InstalledExe"
}
$SmokeArguments = @("--bundle-smoke")
$RegressionTiff = Join-Path (Split-Path -Parent $ProjectRoot) "test.tif"
if (Test-Path -LiteralPath $RegressionTiff -PathType Leaf) {
    $SmokeArguments += $RegressionTiff
}
$PreviousQtPlatform = $env:QT_QPA_PLATFORM
$env:QT_QPA_PLATFORM = "offscreen"
try {
    & $InstalledExe @SmokeArguments
    if ($LASTEXITCODE -ne 0) { Fail "installed application dependency smoke failed" }
} finally {
    if ($null -eq $PreviousQtPlatform) {
        Remove-Item Env:\QT_QPA_PLATFORM -ErrorAction SilentlyContinue
    } else {
        $env:QT_QPA_PLATFORM = $PreviousQtPlatform
    }
}

Write-Host "Installed and verified Plug Analyzer $Version at: $InstalledExe"
