# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.hooks import collect_all

REPO_ROOT = Path(SPECPATH).parents[1]
SRC_ROOT = REPO_ROOT / 'src'
MAIN_SCRIPT = SRC_ROOT / 'main.py'
APP_ICON = REPO_ROOT / 'assets' / 'ToolBox_Icon.ico'

datas = []
binaries = []
hiddenimports = ['mne.io.bdf', 'scipy', 'scipy._cyutility', 'pandas', 'numpy', 'statsmodels', 'pyvista', 'statsmodels', 'patsy']
datas += collect_data_files('mne')
tmp_ret = collect_all('mne')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    [str(MAIN_SCRIPT)],
    pathex=[str(SRC_ROOT)],
    binaries=binaries,
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
    [],
    exclude_binaries=True,
    name='FPVS_Toolbox',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[str(APP_ICON)],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='FPVS_Toolbox',
)
