"""IP 备注存储：管理员为来源 IP 添加自定义备注。"""
from __future__ import annotations

import os

from server.store.jsonstore import load_json, save_json


class IpNotes:
    """IP -> 备注 的映射（落盘为 ip_notes.json）。"""

    def __init__(self, data_dir: str):
        """初始化并加载。

        Args:
            data_dir: 数据目录。
        """
        self.path = os.path.join(data_dir, 'ip_notes.json')
        self.data: dict[str, str] = {}
        raw = load_json(self.path, {})
        if isinstance(raw, dict):
            self.data = {str(k): str(v) for k, v in raw.items() if k}

    def get(self, ip: str) -> str:
        """取某 IP 的备注。

        Args:
            ip: 客户端 IP。

        Returns:
            备注文本；没有时为空字符串。
        """
        return (ip and self.data.get(ip, '')) or ''

    def set(self, ip: str, note: str) -> bool:
        """设置或删除某 IP 的备注。

        Args:
            ip: 客户端 IP。
            note: 备注（空字符串表示删除）。

        Returns:
            保存成功返回 True。
        """
        if not ip:
            return False
        value = str('' if note is None else note)[:200]
        if value:
            self.data[ip] = value
        else:
            self.data.pop(ip, None)
        return save_json(self.path, self.data)
