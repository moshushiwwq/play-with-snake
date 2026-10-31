# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 规格：服务端（onedir，含内置页面与面板）。"""
import os

ROOT = os.getcwd()
icon = os.path.join(ROOT, 'build', 'assets', 'app.ico')

a = Analysis(
    [os.path.join(ROOT, 'server', 'main.py')],
    pathex=[ROOT],
    binaries=[],
    datas=[
        (os.path.join(ROOT, 'client', 'web'), os.path.join('client', 'web')),
        (os.path.join(ROOT, 'server', 'web'), os.path.join('server', 'web')),
    ],
    hiddenimports=[
        'PyQt6.QtWebEngineWidgets', 'PyQt6.QtWebEngineCore', 'PyQt6.QtWebChannel',
        'PyQt6.QtWebSockets', 'PyQt6.QtNetwork', 'PyQt6.QtSql',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[os.path.join(ROOT, 'build', 'runtime_stdio.py')],
    excludes=['tkinter', 'PySide6', 'PyQt5'],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PlayWithSnake-Server',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=icon if os.path.exists(icon) else None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='PlayWithSnake-Server',
)
