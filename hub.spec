# hub.spec — PyInstaller build specification
#
# Usage:
#   pyinstaller hub.spec --clean
#
# Output: dist/OfflineHub.exe  (single file, ~30 MB before content)
#
# Before building:
#   1. Place kiwix-serve.exe  into vendor/
#   2. Place kolibri.exe      into vendor/   (if using Kolibri)
#   3. Run: pip install -r requirements.txt
#   4. Run: pyinstaller hub.spec --clean

import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# ── Hidden imports ────────────────────────────────────────────────────────────
hidden_imports = [
    "customtkinter",
    "flask",
    "werkzeug",
    "werkzeug.serving",
    "requests",
    "sqlite3",
    "json",
    "threading",
    "socket",
    "glob",
    "gzip",
    *collect_submodules("customtkinter"),
    *collect_submodules("flask"),
]

# ── Data files ────────────────────────────────────────────────────────────────
datas = [
    # Portal HTML / static assets
    ("assets/portal",  "assets/portal"),
    # Vendor binaries (kiwix-serve, kolibri, etc.)
    ("vendor",         "vendor"),
    # customtkinter theme files
    *collect_data_files("customtkinter"),
]

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "matplotlib", "numpy", "pandas", "scipy",
        "PIL", "tkinter.test", "unittest",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="OfflineHub",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,                       # compress with UPX if installed
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,                  # no console window (GUI app)
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/icons/hub.ico",    # place a .ico file here before building
    onefile=True,
    version_info=None,
)