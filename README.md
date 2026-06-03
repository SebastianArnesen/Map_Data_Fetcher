# Geonorge Datasets

Desktop app for browsing and downloading map datasets from [Geonorge](https://www.geonorge.no/).

Current version: **1.1.0** (see `app/__init__.py`).

## License

MIT (see `LICENSE`).

## Run from source

Requires **Python 3.11+**. On macOS and most Linux systems the command is **`python3`**, not `python` (unless you use a venv — then `python` works after activation).

```bash
# macOS / Linux — use python3 for the venv
python3 -m venv .venv
source .venv/bin/activate   # Windows: .\.venv\Scripts\activate
pip install -r requirements.txt
python -m app.run
```

### macOS (first time on a new machine)

Apple does not include `python` in Terminal. Install Python and PROJ, then use a venv:

```bash
# If you don't have Homebrew: https://brew.sh
brew install python@3.12 proj

cd /path/to/Map_Data_Fetcher
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
python -m app.run
```

If `python3` is too old (< 3.11), use the Homebrew binary explicitly, e.g. `$(brew --prefix python@3.12)/bin/python3 -m venv .venv`.

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

- Bump version: edit `app/__init__.py` (`__version__ = "x.y.z"`)
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

| OS | Folder |
|----|--------|
| Windows | `%APPDATA%\GeonorgeDatasets\` |
| macOS | `~/Library/Application Support/GeonorgeDatasets/` |
| Linux | `$XDG_DATA_HOME/GeonorgeDatasets/` or `~/.local/share/GeonorgeDatasets/` |

Files in that folder:

- `dataset_index.sqlite3` — index and enriched metadata
- `app.log` — application log
- `crash_reports\latest.txt` (or `crash_reports/latest.txt`) after a crash
- `tile_cache\` — cached map basemap tiles

On first run, the app migrates legacy data when possible:

- Windows: `%APPDATA%\GeonorgeDesktopDownloader` → `GeonorgeDatasets`
- macOS/Linux: old flat `~/GeonorgeDatasets` (or `~/GeonorgeDesktopDownloader`) → the OS-specific path above

Optional one-time import from older installs: `cache.json` in the same folder (migrated automatically when the index is empty).
