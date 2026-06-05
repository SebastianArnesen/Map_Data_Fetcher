#!/usr/bin/env bash
# Build a release artifact for macOS (.app + .dmg) or Linux (onedir tarball).
# Run from repository root:
#   ./build_exe.sh

set -euo pipefail

cd "$(dirname "$0")"

if [[ "$(uname -s)" != "Darwin" && "$(uname -s)" != "Linux" ]]; then
  echo "build_exe.sh supports macOS and Linux only. On Windows use build_exe.ps1." >&2
  exit 1
fi

if [[ -d build ]]; then
  rm -rf build
fi

python -m pip install --quiet pillow

if [[ "$(uname -s)" == "Darwin" ]]; then
  python scripts/prepare_icons.py --macos
else
  python scripts/prepare_icons.py
fi

python -m PyInstaller --noconfirm --clean GeonorgeDatasets.spec

if [[ "$(uname -s)" == "Darwin" ]]; then
  if [[ ! -d dist/GeonorgeDatasets.app ]]; then
    echo "Expected dist/GeonorgeDatasets.app after PyInstaller build." >&2
    exit 1
  fi
  bash build_dmg.sh
  echo ""
  echo "Built: dist/GeonorgeDatasets.app"
  echo "Built: dist/GeonorgeDatasets.dmg"
else
  if [[ ! -d dist/GeonorgeDatasets ]]; then
    echo "Expected dist/GeonorgeDatasets after PyInstaller build." >&2
    exit 1
  fi
  version="$(python -c 'from app import __version__; print(__version__)')"
  arch="$(uname -m)"
  tarball="dist/GeonorgeDatasets-${version}-linux-${arch}.tar.gz"
  rm -f "$tarball"
  tar -czf "$tarball" -C dist GeonorgeDatasets
  echo ""
  echo "Built: dist/GeonorgeDatasets/"
  echo "Built: $tarball"
fi
