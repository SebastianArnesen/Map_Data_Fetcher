# Build a console-mode executable so progress and logs are visible in a terminal.
# Run from repository root:
#   powershell -ExecutionPolicy Bypass -File .\build_debug_exe.ps1

$ErrorActionPreference = "Stop"

if (Test-Path ".\build") {
  Remove-Item -Recurse -Force ".\build"
}

python -m PyInstaller `
  --noconfirm `
  --clean `
  "GeonorgeDatasetsDebug.spec"

Write-Host ""
Write-Host "Built: dist\GeonorgeDatasetsDebug.exe"

