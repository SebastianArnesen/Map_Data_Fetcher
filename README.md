# Geonorge Datasets

Desktop app for browsing and downloading map datasets from [Geonorge](https://www.geonorge.no/).

## Run from source

```bash
pip install -r requirements.txt
python -m app.run
```

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

## Data on disk

- Index and enriched metadata: `%APPDATA%\GeonorgeDatasets\dataset_index.sqlite3`
- Logs and crash reports: `%APPDATA%\GeonorgeDatasets\` (see `crash_reports\latest.txt` after a crash)

On first run after the rename, the app migrates the old `%APPDATA%\GeonorgeDesktopDownloader` folder to `GeonorgeDatasets` when possible.
- Optional one-time import from older installs: `cache.json` in the same folder (migrated automatically when the index is empty)
