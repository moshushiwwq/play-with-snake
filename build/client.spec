# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 规格：客户端（单文件 exe，内嵌本机回环托管的 HTML 页面）。

单文件模式下 datas 会在启动时解压到 sys._MEIPASS，server/paths.py 的
resource_path() 已按该目录解析，因此页面资源不会出现「找不到文件」。
"""
import os

ROOT = os.getcwd()
icon = os.path.join(ROOT, 'build', 'assets', 'app.ico')

a = Analysis(
    [os.path.join(ROOT, 'client', 'main.py')],
    pathex=[ROOT],
    binaries=[],
    datas=[(os.path.join(ROOT, 'client', 'web'), os.path.join('client', 'web'))],
    hiddenimports=[
        'PyQt6.QtSql', 'PyQt6.QtNetwork',
    ],
    hookspath=[os.path.join(ROOT, 'build', 'hooks')],
    hooksconfig={},
    runtime_hooks=[os.path.join(ROOT, 'build', 'runtime_stdio.py')],
    excludes=['tkinter', 'PySide6', 'PyQt5',
              'PyQt6.QtWebEngineCore', 'PyQt6.QtWebEngineWidgets',
              'PyQt6.QtWebChannel'],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='PlayWithSnake-Client',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=icon if os.path.exists(icon) else None,
)
