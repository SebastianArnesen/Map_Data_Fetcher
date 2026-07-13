# -*- mode: python ; coding: utf-8 -*-
import os
import re
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files

ROOT = Path(SPECPATH)
_version_match = re.search(
    r'^__version__\s*=\s*"([^"]+)"',
    (ROOT / "app" / "__init__.py").read_text(encoding="utf-8"),
    re.MULTILINE,
)
APP_VERSION = _version_match.group(1) if _version_match else "0.0.0"
IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform == "linux"

_mac_target = os.environ.get("MACOS_TARGET_ARCH", "").strip()
TARGET_ARCH = _mac_target if IS_MAC and _mac_target in ("arm64", "x86_64", "universal2") else None
_RUNTIME_HOOK = str(ROOT / "rthooks" / "pyi_rth_geonorge_frozen.py")

datas: list[tuple[str, str]] = []
for name in ("appIcon.ico", "appIcon.png", "appIcon.icns"):
    path = ROOT / "assets" / name
    if path.is_file():
        datas.append((str(path), "assets"))

datas += collect_data_files("certifi")
_pyproj_datas, _pyproj_binaries, _pyproj_hiddenimports = collect_all("pyproj")
datas += _pyproj_datas

if IS_MAC or IS_LINUX:
    try:
        import PySide6

        _qt_plugins = Path(PySide6.__file__).resolve().parent / "Qt" / "plugins"
        if _qt_plugins.is_dir():
            datas.append((str(_qt_plugins), "PySide6/Qt/plugins"))
    except Exception:
        pass

icon_path: str | None = None
if IS_WIN and (ROOT / "assets" / "appIcon.ico").is_file():
    icon_path = str(ROOT / "assets" / "appIcon.ico")
elif IS_MAC and (ROOT / "assets" / "appIcon.icns").is_file():
    icon_path = str(ROOT / "assets" / "appIcon.icns")

a = Analysis(
    [str(ROOT / "app" / "run.py")],
    pathex=[str(ROOT)],
    binaries=_pyproj_binaries,
    datas=datas,
    hiddenimports=_pyproj_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[_RUNTIME_HOOK],
    excludes=[],
    noarchive=False,
    optimize=1,
    target_arch=TARGET_ARCH,
)
pyz = PYZ(a.pure)

if IS_LINUX:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="MapDataFetcher",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=TARGET_ARCH,
        codesign_identity=None,
        entitlements_file=None,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name="MapDataFetcher",
    )
elif IS_MAC:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="MapDataFetcher",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=True,
        target_arch=TARGET_ARCH,
        codesign_identity=None,
        entitlements_file=None,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name="MapDataFetcher",
    )
    app = BUNDLE(
        coll,
        name="MapDataFetcher.app",
        icon=icon_path,
        bundle_identifier="com.github.sebastianarnesen.map-data-fetcher",
        info_plist={
            "NSHighResolutionCapable": "True",
            "CFBundleName": "Map Data Fetcher",
            "CFBundleDisplayName": "Map Data Fetcher",
            "CFBundleShortVersionString": APP_VERSION,
            "LSMinimumSystemVersion": "12.0",
        },
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name="MapDataFetcher",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=TARGET_ARCH,
        codesign_identity=None,
        entitlements_file=None,
        icon=icon_path,
    )
