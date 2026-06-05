# -*- mode: python ; coding: utf-8 -*-
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

datas: list[tuple[str, str]] = []
for name in ("appIcon.ico", "appIcon.png", "appIcon.icns"):
    path = ROOT / "assets" / name
    if path.is_file():
        datas.append((str(path), "assets"))

datas += collect_data_files("certifi")
_pyproj_datas, _pyproj_binaries, _pyproj_hiddenimports = collect_all("pyproj")
datas += _pyproj_datas

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
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

if IS_LINUX:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="GeonorgeDatasets",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
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
        name="GeonorgeDatasets",
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name="GeonorgeDatasets",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=IS_MAC,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=icon_path,
    )
    if IS_MAC:
        app = BUNDLE(
            exe,
            name="GeonorgeDatasets.app",
            icon=icon_path,
            bundle_identifier="com.github.sebastianarnesen.geonorge-datasets",
            info_plist={
                "NSHighResolutionCapable": "True",
                "CFBundleShortVersionString": APP_VERSION,
            },
        )
