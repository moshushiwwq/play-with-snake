"""客户端路径与配置（QSettings ini + 本地数据目录）。"""
from __future__ import annotations

import os

from PyQt6.QtCore import QSettings


def app_data_dir() -> str:
    """客户端数据目录（%LOCALAPPDATA%/PlayWithSnake）。

    Returns:
        绝对路径（不存在时自动创建）。
    """
    base = os.environ.get('LOCALAPPDATA') or os.path.join(os.path.expanduser('~'), '.playwithsnake')
    d = os.path.join(base, 'PlayWithSnake')
    os.makedirs(d, exist_ok=True)
    return d


class ClientConfig:
    """客户端配置（Qt 内置 QSettings 持久化）。"""

    def __init__(self):
        """打开 ini 配置文件。"""
        self.path = os.path.join(app_data_dir(), 'client.ini')
        self.s = QSettings(self.path, QSettings.Format.IniFormat)

    def get(self, key: str, default=None):
        """读取配置项。"""
        v = self.s.value(key)
        if v is None:
            return default
        if isinstance(default, bool):
            return str(v).lower() in ('1', 'true', 'yes', 'on')
        return v

    def set(self, key: str, value) -> None:
        """写入配置项并立即落盘。"""
        self.s.setValue(key, value)
        self.s.sync()

    @property
    def start_hidden(self) -> bool:
        """是否启动即隐藏到托盘。"""
        return bool(self.get('ui/start_hidden', False))

    @property
    def minimize_to_tray(self) -> bool:
        """关闭窗口时是否最小化到托盘。"""
        return bool(self.get('ui/minimize_to_tray', True))

    @property
    def auto_reconnect(self) -> bool:
        """断线是否自动重连。"""
        return bool(self.get('net/auto_reconnect', True))

    @property
    def last_server(self) -> str:
        """上次连接的服务器地址。"""
        return str(self.get('net/last_server', '') or '')

    def set_last_server(self, host: str) -> None:
        """记录最近一次成功连接的服务器。"""
        self.set('net/last_server', host)

    @property
    def geometry(self):
        """上次窗口几何（QByteArray 或 None）。"""
        return self.get('ui/geometry', None)

    def set_geometry(self, data) -> None:
        """保存窗口几何。"""
        self.set('ui/geometry', data)
