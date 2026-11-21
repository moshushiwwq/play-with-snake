# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 规格：服务端（单文件 exe，内嵌游戏页面与管理面板）。

服务端既托管 client/web/index.html，也托管 server/web/panel.html；两份静态
资源都必须进入 datas，否则运行时会返回「页面文件缺失」。
"""
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
        'PyQt6.QtWebSockets', 'PyQt6.QtNetwork',
    ],
    hookspath=[],
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
    name='PlayWithSnake-Server',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=icon if os.path.exists(icon) else None,
)
