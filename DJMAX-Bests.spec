# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec: one self-contained DJMAX-Bests.exe (no Python visible anywhere).

Onefile on purpose: everything (interpreter, packages, renderer assets, jackets) lives inside
the executable, and the only thing it writes beside itself is ./data. Startup pays a one-time
extraction of the bundle to %TEMP%; in exchange the distribution is a single file.
"""
import os

from PyInstaller.utils.hooks import collect_data_files

ROOT = SPECPATH

# ---------------------------------------------------------------- bundled assets
datas = []

generators = os.path.join(ROOT, "djmax_bests", "generators")
for dirpath, dirnames, filenames in os.walk(generators):
    dirnames[:] = [d for d in dirnames if d != "__pycache__"]
    for filename in filenames:
        if filename.lower().endswith((".png", ".ttf", ".csv", ".jpg", ".jpeg")):
            datas.append((os.path.join(dirpath, filename),
                          os.path.relpath(dirpath, ROOT)))

# Only the placeholder jacket ships inside the exe; the first refresh downloads the real ones
# (api_handler.prefetch_covers), which keeps ~13 MB of jackets out of the executable.
dummy_cover = os.path.join(ROOT, "djmax_bests", "covers", "dummy.jpg")
if os.path.exists(dummy_cover):
    datas.append((dummy_cover, "djmax_bests/covers"))

datas.append((os.path.join(ROOT, "djmax_bests", "analyzer", "djmax_songs_tags.csv"),
              "djmax_bests/analyzer"))

# zoneinfo needs the tzdata package on Windows (no system tz database)
datas += collect_data_files("tzdata")

# ---------------------------------------------------------------- analysis
a = Analysis(
    [os.path.join(ROOT, "app.py")],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "pyarrow",
        "pyarrow.lib",
        "pyarrow.parquet",
        "pyarrow._parquet",
        "matplotlib.backends.backend_agg",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "IPython",
        "pytest",
        "PyQt5",
        "PySide6",
        "notebook",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="DJMAX-Bests",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
