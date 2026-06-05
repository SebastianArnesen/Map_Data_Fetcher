#!/usr/bin/env bash
# Build a release artifact for macOS (.app + .dmg) or Linux (onedir tarball).
# Run from repository root:
#   ./build_exe.sh
#
# macOS cross-arch (on Apple Silicon hosts):
#   MACOS_TARGET_ARCH=x86_64 ./build_exe.sh

set -euo pipefail

cd "$(dirname "$0")"

if [[ "$(uname -s)" != "Darwin" && "$(uname -s)" != "Linux" ]]; then
  echo "build_exe.sh supports macOS and Linux only. On Windows use build_exe.ps1." >&2
  exit 1
fi

run_python() {
  if [[ "$(uname -s)" == "Darwin" && "$(uname -m)" == "arm64" && "${MACOS_TARGET_ARCH:-}" == "x86_64" ]]; then
    arch -x86_64 python "$@"
  else
    python "$@"
  fi
}

if [[ "$(uname -s)" == "Darwin" ]]; then
  MACOS_TARGET_ARCH="${MACOS_TARGET_ARCH:-$(uname -m)}"
  if [[ "$MACOS_TARGET_ARCH" == "aarch64" ]]; then
    MACOS_TARGET_ARCH="arm64"
  fi
  export MACOS_TARGET_ARCH
  echo "macOS build architecture: $MACOS_TARGET_ARCH"
fi

if [[ -d build ]]; then
  rm -rf build
fi

run_python -m pip install --quiet pillow

if [[ "$(uname -s)" == "Darwin" ]]; then
  run_python scripts/prepare_icons.py --macos
else
  run_python scripts/prepare_icons.py
fi

run_python -m PyInstaller --noconfirm --clean GeonorgeDatasets.spec

if [[ "$(uname -s)" == "Darwin" ]]; then
  if [[ ! -d dist/GeonorgeDatasets.app ]]; then
    echo "Expected dist/GeonorgeDatasets.app after PyInstaller build." >&2
    exit 1
  fi
  version="$(run_python -c 'from app import __version__; print(__version__)')"
  dmg="dist/GeonorgeDatasets-${version}-macos-${MACOS_TARGET_ARCH}.dmg"
  DMG_OUTPUT="$dmg" bash build_dmg.sh
  echo ""
  echo "Built: dist/GeonorgeDatasets.app"
  echo "Built: $dmg"
else
  if [[ ! -d dist/GeonorgeDatasets ]]; then
    echo "Expected dist/GeonorgeDatasets after PyInstaller build." >&2
    exit 1
  fi
  version="$(run_python -c 'from app import __version__; print(__version__)')"
  arch="$(uname -m)"
  tarball="dist/GeonorgeDatasets-${version}-linux-${arch}.tar.gz"
  rm -f "$tarball"
  tar -czf "$tarball" -C dist GeonorgeDatasets
  echo ""
  echo "Built: dist/GeonorgeDatasets/"
  echo "Built: $tarball"
fi
