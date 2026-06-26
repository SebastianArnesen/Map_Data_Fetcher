# Geonorge Datasets

Desktop app for browsing and downloading map datasets from [Geonorge](https://www.geonorge.no/).

Current version: **1.4.0** (see `app/__init__.py`).

## License

MIT (see `LICENSE`).

## Run from source

Requires **Python 3.11+**. On macOS and most Linux systems the command is `**python3`**, not `python` (unless you use a venv — then `python` works after activation).

```bash
# macOS / Linux — use python3 for the venv
python3 -m venv .venv
source .venv/bin/activate   # Windows: .\.venv\Scripts\activate
pip install -r requirements.txt
python -m app.run
```

### macOS (first time on a new machine)

Apple does not include `python` in Terminal, and the default `python3` is often **3.9**, which cannot install recent PySide6 wheels. Use **Homebrew Python 3.12** for the venv:

```bash
# If you don't have Homebrew: https://brew.sh
brew install python@3.12 proj

cd /path/to/Map_Data_Fetcher
# Important: use Homebrew's python3, not /usr/bin/python3
"$(brew --prefix python@3.12)/bin/python3" -m venv .venv
source .venv/bin/activate
python --version    # should show 3.12.x
pip install --upgrade pip
pip install -r requirements.txt
python -m app.run
```

**If `pip install` fails on `PySide6>=6.11`:** either your clone is outdated (`git pull`) or you are on **macOS 12 (Monterey)** — Qt does not publish PySide6 6.10+ wheels for that OS, so pip installs **6.9.3** (fine for this app). Ensure `requirements.txt` says `PySide6>=6.8.0`, not `>=6.11.0`.

Check before creating the venv: `python --version` in the venv must be **3.11+** (3.12 recommended).

### Linux (Debian/Ubuntu example)

```bash
sudo apt install python3.11-venv libproj-dev
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m app.run
```

`pyproj` needs PROJ on Linux when pip does not provide a compatible wheel.

### Debugging flags

- `python -m app.run --no-tooltips`
- `python -m app.run --profile-ui`

## Build Windows executable

```powershell
pip install -r requirements-dev.txt
powershell -ExecutionPolicy Bypass -File .\build_exe.ps1
```

Output: `dist\GeonorgeDatasets.exe`

Place the app icon at `assets\appIcon.ico` before building (used for the `.exe`, title bar, and taskbar).

## Build debug executable (console)

```powershell
pip install -r requirements-dev.txt
powershell -ExecutionPolicy Bypass -File .\build_debug_exe.ps1
```

Output: `dist\GeonorgeDatasetsDebug.exe`

## Install

Download the build for your OS from [GitHub Releases](https://github.com/SebastianArnesen/Map_Data_Fetcher/releases).

### Windows

- **Installer:** `GeonorgeDatasetsSetup.exe`
- **Portable:** `GeonorgeDatasets.exe` (no install step)

**Windows SmartScreen:** The installer is not code-signed (no paid certificate), so Windows may show *“Windows protected your PC”* with **Unknown publisher**. That is normal for unsigned open-source software. Click **Run anyway** to continue — the file comes from this repository’s GitHub Actions build.

### macOS

Download the DMG that matches your Mac:

| Mac type | File |
| --- | --- |
| Apple Silicon (M1/M2/M3/M4) | `GeonorgeDatasets-<version>-macos-arm64.dmg` |
| Intel | `GeonorgeDatasets-<version>-macos-x86_64.dmg` |

Not sure? **Apple menu → About This Mac** — “Chip” means Apple Silicon; “Processor” with Intel in the name means x86_64.

Open the DMG and drag **Geonorge Datasets** to **Applications**. If you see *“not supported on this Mac”*, you downloaded the wrong architecture DMG.

**Requires macOS 12 Monterey or later.** Release builds use Qt 6.9 (PySide6 below 6.10) so they run on Monterey; if you see *“Qt requires macOS 13.0.0 or later”*, you have an older release built with a too-new Qt — install the latest DMG from [Releases](https://github.com/SebastianArnesen/Map_Data_Fetcher/releases).

The app is not Apple-notarized (no paid developer certificate). That is normal for unsigned open-source builds:

1. **Double-click** may show a warning with only **OK** — use step 2 instead.
2. **Right-click** the app → **Open** → **Open** in the dialog (one-time bypass).
3. If macOS still refuses after download, clear quarantine in Terminal:

```bash
xattr -dr com.apple.quarantine /Applications/GeonorgeDatasets.app
```

**App bounces in the Dock and exits?** Check `~/Library/Application Support/GeonorgeDatasets/app.log` and `crash_reports/latest.txt`. That usually means a bad download/architecture mismatch or an older broken build — grab the latest `*-macos-x86_64.dmg` (Intel) or `*-macos-arm64.dmg` (Apple Silicon) from [Releases](https://github.com/SebastianArnesen/Map_Data_Fetcher/releases).

**“Open map” missing for Cell areas (Windows/macOS)?** The app only shows it when the dataset supports map-based cell selection. If you upgraded from an older build, click **Reset cache** once (toolbar) so capabilities are re-fetched, or install a release built after enrichment version 4.

### Linux

- **Portable:** `GeonorgeDatasets-<version>-linux-<arch>.tar.gz`
- Extract and run the binary inside the `GeonorgeDatasets/` folder:

```bash
tar -xzf GeonorgeDatasets-1.2.3-linux-x86_64.tar.gz
./GeonorgeDatasets/GeonorgeDatasets
```

Built on Ubuntu (GitHub `ubuntu-latest`); glibc must be new enough for that runner (typical on current Debian/Ubuntu/Fedora). Install Qt/X11 libs if the binary complains about missing `libxcb` or similar.

## Build macOS / Linux executable

Requires **Python 3.11+** and PyInstaller (see `requirements-dev.txt`).

```bash
pip install -r requirements-dev.txt
# macOS release builds: use Qt 6.9 so the .app runs on macOS 12+
pip install -r requirements-macos-build.txt
chmod +x build_exe.sh
./build_exe.sh
```

Output:

- **macOS:** `dist/GeonorgeDatasets.app` and `dist/GeonorgeDatasets-<version>-macos-<arch>.dmg` (`<arch>` is `arm64` or `x86_64`)
- **Linux:** `dist/GeonorgeDatasets/` and `dist/GeonorgeDatasets-<version>-linux-<arch>.tar.gz`

Place the app icon at `assets/appIcon.ico` before building (used for window icons; macOS bundle icons are generated as `.icns` during the build).

## Release checklist

### GitHub Actions (recommended)

1. Bump version in `app/__init__.py` (`__version__ = "x.y.z"`) and update the version line in this README if you keep it in sync.
2. Commit and push to `main`.
3. Tag must match the version with a `v` prefix, then push the tag:

```bash
git tag v1.2.3
git push origin v1.2.3
```

The [Release workflow](.github/workflows/release.yml) runs when you **push a version tag** (`v*`). It builds on **Windows, macOS, and Linux** in parallel, then publishes all artifacts to [GitHub Releases](https://github.com/SebastianArnesen/Map_Data_Fetcher/releases):

| OS | Files |
| --- | --- |
| Windows | `GeonorgeDatasets.exe`, `GeonorgeDatasetsSetup.exe` |
| macOS | `GeonorgeDatasets-<version>-macos-arm64.dmg`, `GeonorgeDatasets-<version>-macos-x86_64.dmg` |
| Linux | `GeonorgeDatasets-<version>-linux-<arch>.tar.gz` |

The tag name **must** equal `v` + `__version__` (e.g. app `1.2.3` → tag `v1.2.3`).

Pushing a tag does **not** re-run CI (only branch pushes to `main` do). Typical flow: push `main` (CI runs) → when green, `git tag v1.2.3 && git push origin v1.2.3` (Release runs once). If a release failed, fix `main`, then delete and re-push the tag (`git push origin :refs/tags/v1.2.3` then tag again) or run **Actions → Release → Run workflow** with ref `v1.2.3`.

### Local build (optional)

- Build release exe: `powershell -ExecutionPolicy Bypass -File .\build_exe.ps1`
- (Optional) Build debug exe: `powershell -ExecutionPolicy Bypass -File .\build_debug_exe.ps1`
- Build installer: `powershell -ExecutionPolicy Bypass -File .\build_installer.ps1`
- Smoke test:
  - Open app, wait for datasets to load
  - Try: Format=TIFF + Area type=Cell (no dataset) → ensure UI stays responsive
  - Select a dataset + format + projection + area and start a small download
- Verify disk paths:
  - `%APPDATA%\GeonorgeDatasets\app.log`
  - `%APPDATA%\GeonorgeDatasets\dataset_index.sqlite3`
  - `%APPDATA%\GeonorgeDatasets\crash_reports\latest.txt` after a forced crash test (optional)

## Data on disk


| OS      | Folder                                                                   |
| ------- | ------------------------------------------------------------------------ |
| Windows | `%APPDATA%\GeonorgeDatasets\`                                            |
| macOS   | `~/Library/Application Support/GeonorgeDatasets/`                        |
| Linux   | `$XDG_DATA_HOME/GeonorgeDatasets/` or `~/.local/share/GeonorgeDatasets/` |


Files in that folder:

- `dataset_index.sqlite3` — index and enriched metadata
- `app.log` — application log
- `crash_reports\latest.txt` (or `crash_reports/latest.txt`) after a crash
- `tile_cache\` — cached map basemap tiles

On first run, the app migrates legacy data when possible:

- Windows: `%APPDATA%\GeonorgeDesktopDownloader` → `GeonorgeDatasets`
- macOS/Linux: old flat `~/GeonorgeDatasets` (or `~/GeonorgeDesktopDownloader`) → the OS-specific path above

Optional one-time import from older installs: `cache.json` in the same folder (migrated automatically when the index is empty).