## Roadmap

### Packaging for other people (Windows)

- Build exe with PyInstaller (`build_exe.ps1` / `GeonorgeDatasets.spec`)
- Build installer with Inno Setup (`build_installer.ps1` / `installer/GeonorgeDatasets.iss`)
- Later: code-signing (optional but recommended for Windows SmartScreen)

### macOS / Linux

The app is PySide6-based and can be cross-platform, but packaging differs:

- **macOS**: build an `.app` bundle and distribute via `.dmg` (or `.pkg`).
- **Linux**: AppImage or `.deb`/`.rpm` depending on target distro.

Recommended approach:
- First ensure the code runs cleanly on macOS/Linux (paths, SSL bundle, single-instance lock).
- Then create per-OS build scripts and CI jobs that produce artifacts.

