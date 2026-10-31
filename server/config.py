"""服务端配置：端口、快照频率、内网发现、托盘启动、自启动方式与面板密码参数。"""
from __future__ import annotations

import os

from server.paths import data_dir
from server.store.jsonstore import load_json, save_json

DEFAULTS = {
    'port': 8080,
    'wsPort': 8081,
    'snapshotHz': 30,
    'discovery': True,
    'trayStart': False,
    'autostart': 'none',      # none | logon | boot
    'bind': '0.0.0.0',
    'panelAuth': None,
}


class Config:
    """服务端配置对象（JSON 持久化到 server_data/config.json）。"""

    def __init__(self):
        """加载配置并与默认值合并。"""
        self.path = os.path.join(data_dir(), 'config.json')
        raw = load_json(self.path, {})
        self.data = dict(DEFAULTS)
        if isinstance(raw, dict):
            self.data.update({k: v for k, v in raw.items() if k in DEFAULTS})
        self._normalize()

    def _normalize(self) -> None:
        """修正非法端口与频率。"""
        self.data['port'] = _port(self.data.get('port'), 8080)
        self.data['wsPort'] = _port(self.data.get('wsPort'), 8081)
        if self.data['wsPort'] == self.data['port']:
            self.data['wsPort'] = 8081 if self.data['port'] != 8081 else 8082
        try:
            hz = int(self.data.get('snapshotHz') or 30)
        except Exception:
            hz = 30
        self.data['snapshotHz'] = max(5, min(60, hz))
        self.data['discovery'] = bool(self.data.get('discovery', True))
        self.data['trayStart'] = bool(self.data.get('trayStart', False))
        if self.data.get('autostart') not in ('none', 'logon', 'boot'):
            self.data['autostart'] = 'none'

    # 便捷访问
    @property
    def port(self) -> int:
        """HTTP 端口。"""
        return int(self.data['port'])

    @property
    def ws_port(self) -> int:
        """WebSocket 端口。"""
        return int(self.data['wsPort'])

    @property
    def snapshot_hz(self) -> int:
        """快照频率。"""
        return int(self.data['snapshotHz'])

    def save(self) -> bool:
        """保存配置。

        Returns:
            成功返回 True。
        """
        return save_json(self.path, self.data)


def _port(value, fallback: int) -> int:
    """端口合法性校验。"""
    try:
        n = int(value)
    except Exception:
        return fallback
    return n if 1 <= n <= 65535 else fallback
