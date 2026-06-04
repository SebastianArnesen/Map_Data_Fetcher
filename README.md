# Geonorge Datasets

Desktop app for browsing and downloading map datasets from [Geonorge](https://www.geonorge.no/).

Current version: **1.2.0** (see `app/__init__.py`).

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

## Release checklist (Windows)

### GitHub Actions (recommended)

1. Bump version in `app/__init__.py` (`__version__ = "x.y.z"`) and update the version line in this README if you keep it in sync.
2. Commit and push to `main`.
3. Tag must match the version with a `v` prefix, then push the tag:

```bash
git tag v1.2.0
git push origin v1.2.0
```

The [Release workflow](.github/workflows/release.yml) runs on `windows-latest`, calls the same `build_exe.ps1` and `build_installer.ps1` scripts as local builds, and publishes `GeonorgeDatasets.exe` plus `GeonorgeDatasetsSetup.exe` to [GitHub Releases](https://github.com/SebastianArnesen/Map_Data_Fetcher/releases). The tag name must equal `v` + `__version__` (e.g. app `1.2.0` → tag `v1.2.0`).

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