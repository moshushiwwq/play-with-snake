# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 规格：客户端（onedir，含内置页面）。"""
import os

ROOT = os.getcwd()
icon = os.path.join(ROOT, 'build', 'assets', 'app.ico')

a = Analysis(
    [os.path.join(ROOT, 'client', 'main.py')],
    pathex=[ROOT],
    binaries=[],
    datas=[(os.path.join(ROOT, 'client', 'web'), os.path.join('client', 'web'))],
    hiddenimports=[
        'PyQt6.QtWebEngineWidgets', 'PyQt6.QtWebEngineCore', 'PyQt6.QtWebChannel',
        'PyQt6.QtWebSockets', 'PyQt6.QtSql', 'PyQt6.QtNetwork',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'PySide6', 'PyQt5'],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PlayWithSnake-Client',
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
    name='PlayWithSnake-Client',
)
