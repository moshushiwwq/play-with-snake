# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 规格：客户端（单文件 exe，启动后搜索服务器并用浏览器打开其页面）。

客户端不再自己托管页面，因此不需要打包 `client/web`；页面由服务端随自己的 exe 分发。
`console=False` 与默认清单即普通用户权限：不弹 UAC、不请求管理员。
"""
import os

ROOT = os.getcwd()
icon = os.path.join(ROOT, 'build', 'assets', 'app.ico')

a = Analysis(
    [os.path.join(ROOT, 'client', 'main.py')],
    pathex=[ROOT],
    binaries=[],
    datas=[],
    hiddenimports=[
        'PyQt6.QtNetwork',
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
