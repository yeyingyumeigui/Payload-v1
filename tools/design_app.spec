# -*- mode: python ; coding: utf-8 -*-
"""通信卫星有效载荷方案设计器 —— PyInstaller 打包配置。

pyinstaller design_app.spec
产物: dist/载荷方案设计器.exe（单文件，双击运行，离线，Edge WebView2 渲染）
"""
import os

BASE = os.path.abspath(os.path.dirname(SPEC))
KG = os.path.join(BASE, "..", "output", "通信有效载荷知识图谱_2026-09-20.json")

block_cipher = None

a = Analysis(
    ['design_app.py'],
    pathex=[BASE],
    binaries=[],
    datas=[(KG, 'output')],
    hiddenimports=[
        'webview.platforms.edgechromium',
        'webview.platforms.winforms',
        'clr',
        'pythonnet',
        'design_data', 'design_engine', 'infoflow_data', 'infoflow_engine',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'pandas', 'PyQt5', 'PySide2'],
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
    name='载荷方案设计器',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
    version=None,
)
