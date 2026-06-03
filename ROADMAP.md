## Roadmap

### Cross-platform (macOS / Linux)

#### Phase 1 — Run from source

- [x] Cross-platform `app_data_dir()` (Windows AppData, macOS Application Support, Linux XDG)
- [x] Migrate legacy flat `~/GeonorgeDatasets` on macOS/Linux when applicable
- [x] Route `geonorge/cache.py` through `app_data_dir()` only
- [x] Add `certifi` to `requirements.txt` (HTTPS in dev matches frozen builds)
- [x] Document macOS/Linux setup and data paths in `README.md`
- [ ] Manual smoke test on macOS and at least one Linux distro

#### Phase 2 — Platform polish

- [ ] Crash restart: detect frozen app on macOS/Linux (not only `.exe`)
- [ ] App icon: `.icns` / `.png` on macOS/Linux; keep `.ico` on Windows
- [ ] Window startup: review `showMaximized()` on macOS
- [ ] Map fetch: use `ca_bundle_path()` in `map_picker.fetch_text`

#### Phase 3 — Packaging

- [ ] Portable PyInstaller spec paths (no Windows-only backslashes)
- [ ] `build_exe.sh` (or shared build script) for macOS and Linux
- [ ] macOS: `.app` bundle, code sign, notarize, `.dmg`
- [ ] Linux: onedir or AppImage (`.deb` optional)
- [ ] Keep Inno Setup Windows-only

#### Phase 4 — CI and releases

- [ ] GitHub Actions matrix: `windows-latest`, `macos-latest`, `ubuntu-latest`
- [ ] Tests + ruff + compileall on all three
- [ ] Optional: PyInstaller artifacts on release tags

---

### Packaging for other people (Windows)

- Build exe with PyInstaller (`build_exe.ps1` / `GeonorgeDatasets.spec`)
- Build installer with Inno Setup (`build_installer.ps1` / `installer/GeonorgeDatasets.iss`)
- Later: code-signing (optional but recommended for Windows SmartScreen)

### macOS / Linux (summary)

The app is PySide6-based and can be cross-platform; packaging differs:

- **macOS**: `.app` bundle + `.dmg` (or `.pkg`)
- **Linux**: AppImage or `.deb`/`.rpm` depending on target distro

See the phased checklist above for concrete tasks.
