# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller recipe for the standalone Windows console executable."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules, copy_metadata


PROJECT_ROOT = Path(SPECPATH).parents[1]
EXAMPLES = PROJECT_ROOT / "docker" / "examples"

datas = copy_metadata("cineflow")
datas += [(str(PROJECT_ROOT / "VERSION"), ".")]
datas += [
    (str(EXAMPLES / filename), "examples")
    for filename in ("config.yaml", "from_lib.yaml", "to_lib.yaml")
]

hiddenimports = collect_submodules("cineflow.integrations")
hiddenimports += collect_submodules("cineflow.internal")

a = Analysis(
    [str(PROJECT_ROOT / "cineflow" / "main.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="CineFlow",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
