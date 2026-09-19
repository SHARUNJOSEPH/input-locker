# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import sys
from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None

project_root = Path('.').resolve()
assets_dir = project_root / 'assets'

# Ensure src is on sys.path during spec analysis
src_path = str(project_root / 'src')
if src_path not in sys.path:
    sys.path.insert(0, src_path)

datas = [
    (str(assets_dir), 'assets'),
]
binaries = []
hiddenimports = [
    'PIL',
    'PIL.Image',
    'PIL.ImageTk',
    'PIL.ImageDraw',
    'PIL.ImageFont',
    'PyQt6',
    'PyQt6.QtCore',
    'PyQt6.QtGui',
    'PyQt6.QtWidgets',
    'tkinter',
    'tkinter.filedialog',
    'tkinter.messagebox',
]

# Collect all pynput components (submodules, binaries, datas)
pynput_datas, pynput_binaries, pynput_hidden = collect_all('pynput')
datas += pynput_datas
binaries += pynput_binaries
hiddenimports += pynput_hidden

# Collect all pystray components
pystray_datas, pystray_binaries, pystray_hidden = collect_all('pystray')
datas += pystray_datas
binaries += pystray_binaries
hiddenimports += pystray_hidden

# Collect all input_locker modules
hiddenimports += collect_submodules('input_locker')

a = Analysis(
    ['src/input_locker/main.py'],
    pathex=['src'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    name='InputLocker',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(assets_dir / 'icon.ico'),
)
