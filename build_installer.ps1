# Build a Windows installer (Inno Setup).
# Prereqs:
# - Build exe first: powershell -ExecutionPolicy Bypass -File .\build_exe.ps1
# - Install Inno Setup and add ISCC.exe to PATH
#
# Output: dist\GeonorgeDatasetsSetup.exe

$ErrorActionPreference = "Stop"

function Read-AppVersion {
  $p = ".\\app\\__init__.py"
  if (-not (Test-Path $p)) { return $null }
  $line = (Select-String -Path $p -Pattern '^__version__\s*=\s*"(.*)"' -AllMatches | Select-Object -First 1)
  if (-not $line) { return $null }
  return $line.Matches[0].Groups[1].Value
}

function Resolve-IsccPath {
  $cmd = Get-Command ISCC.exe -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }

  $candidates = @(
    "C:\Program Files (x86)\Inno Setup 7\ISCC.exe",
    "C:\Program Files\Inno Setup 7\ISCC.exe",
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe",
    "C:\Program Files (x86)\Inno Setup 5\ISCC.exe",
    "C:\Program Files\Inno Setup 5\ISCC.exe",
    "$env:ProgramData\chocolatey\lib\InnoSetup\tools\ISCC.exe",
    "$env:ProgramData\chocolatey\lib\innosetup\tools\ISCC.exe"
  )

  foreach ($path in $candidates) {
    if (Test-Path $path) { return $path }
  }

  # Try registry (works even if installed to a custom path).
  $regKeys = @(
    "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\ISCC.exe",
    "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\ISCC.exe"
  )
  foreach ($key in $regKeys) {
    try {
      $p = (Get-ItemProperty -Path $key -ErrorAction Stop)."(default)"
      if ($p -and (Test-Path $p)) { return $p }
    } catch { }
  }

  return $null
}

$version = Read-AppVersion
if (-not $version) {
  Write-Error "Could not read __version__ from app\\__init__.py"
}

$iscc = Resolve-IsccPath
if (-not $iscc) {
  Write-Error @"
ISCC.exe not found.

Install Inno Setup, or add ISCC.exe to your PATH.
Common install locations:
  - C:\Program Files (x86)\Inno Setup 7\ISCC.exe
  - C:\Program Files\Inno Setup 7\ISCC.exe
  - C:\Program Files (x86)\Inno Setup 6\ISCC.exe
  - C:\Program Files\Inno Setup 6\ISCC.exe
"@
}

if (-not (Test-Path ".\\dist\\GeonorgeDatasets.exe")) {
  Write-Error "dist\\GeonorgeDatasets.exe not found. Build the exe first."
}

& $iscc "/DAppVersion=$version" ".\\installer\\GeonorgeDatasets.iss"
if (-not (Test-Path ".\\dist\\GeonorgeDatasetsSetup.exe")) {
  Write-Error "Inno Setup did not produce dist\\GeonorgeDatasetsSetup.exe"
}
Write-Host ""
Write-Host "Built installer: dist\\GeonorgeDatasetsSetup.exe"

