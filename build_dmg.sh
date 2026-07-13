#!/usr/bin/env bash
# Wrap dist/MapDataFetcher.app in a drag-to-Applications .dmg (macOS only).

set -euo pipefail

cd "$(dirname "$0")"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "build_dmg.sh is macOS-only." >&2
  exit 1
fi

app="dist/MapDataFetcher.app"
dmg="${DMG_OUTPUT:-dist/MapDataFetcher.dmg}"
staging="dist/dmg-staging"

if [[ ! -d "$app" ]]; then
  echo "Missing $app — run build_exe.sh first." >&2
  exit 1
fi

rm -f "$dmg"
rm -rf "$staging"
mkdir -p "$staging"
cp -R "$app" "$staging/"
ln -s /Applications "$staging/Applications"

hdiutil create \
  -volname "Map Data Fetcher" \
  -srcfolder "$staging" \
  -ov \
  -format UDZO \
  "$dmg"

rm -rf "$staging"
echo "Built: $dmg"
