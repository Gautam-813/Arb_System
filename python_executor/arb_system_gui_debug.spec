# -*- mode: python ; coding: utf-8 -*-


from pathlib import Path

PYTHON_ROOT = Path(r"C:\Users\Administrator\AppData\Local\Programs\Python\Python311")
WORKING_TK = Path("vendor_tk_from_working_exe")

a = Analysis(
    ['gui.py'],
    pathex=[],
    binaries=[
        (str(WORKING_TK / "_tkinter.pyd"), "."),
        (str(WORKING_TK / "tcl86t.dll"), "."),
        (str(WORKING_TK / "tk86t.dll"), "."),
    ],
    datas=[
        (str(WORKING_TK / "_tcl_data"), "_tcl_data"),
        (str(WORKING_TK / "_tk_data"), "_tk_data"),
    ],
    hiddenimports=['numpy', 'tkinter', '_tkinter', 'mt5_price_worker'],
    hookspath=['hooks'],
    hooksconfig={},
    runtime_hooks=['tk_runtime_hook.py'],
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
    name='arb_system_gui_debug',
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

