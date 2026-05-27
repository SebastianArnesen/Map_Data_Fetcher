# Build a single-file Windows executable.
# Run from repository root:
#   powershell -ExecutionPolicy Bypass -File .\build_exe.ps1

$ErrorActionPreference = "Stop"

# PyInstaller output; safe to delete — it is recreated every build.
if (Test-Path ".\build") {
  Remove-Item -Recurse -Force ".\build"
}

python -m PyInstaller `
  --noconfirm `
  --clean `
  "GeonorgeDatasets.spec"

Write-Host ""
Write-Host "Built: dist\GeonorgeDatasets.exe"

