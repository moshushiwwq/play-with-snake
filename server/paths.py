"""路径解析：源码运行与 PyInstaller 打包运行（onedir）都可用。"""
from __future__ import annotations

import os
import sys

IS_FROZEN = bool(getattr(sys, 'frozen', False))
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resource_path(*parts: str) -> str:
    """返回随程序分发的资源文件路径（client/web、server/web 等）。

    Args:
        *parts: 相对路径片段。

    Returns:
        绝对路径。
    """
    base = getattr(sys, '_MEIPASS', PROJECT_ROOT) if IS_FROZEN else PROJECT_ROOT
    return os.path.join(base, *parts)


def app_dir() -> str:
    """程序所在目录（打包后为 exe 所在目录，源码运行时为项目根）。

    Returns:
        绝对路径。
    """
    return os.path.dirname(sys.executable) if IS_FROZEN else PROJECT_ROOT


def data_dir() -> str:
    """服务端数据目录（配置、排行榜、地图、日志等）。

    Returns:
        绝对路径（不存在时自动创建）。
    """
    d = os.path.join(app_dir(), 'server_data')
    os.makedirs(d, exist_ok=True)
    return d
