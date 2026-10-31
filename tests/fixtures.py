"""测试夹具：临时数据目录、假连接与服务实例。"""
from __future__ import annotations

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from server.core.service import GameService
from server.store.custom_maps import CustomMaps
from server.store.ip_notes import IpNotes
from server.store.leaderboard import Leaderboard
from server.store.online_board import OnlineBoard


class FakeConn:
    """测试用连接：记录所有下发消息。"""

    def __init__(self, cid: int, name: str = '', ip: str = '127.0.0.1'):
        """初始化连接。"""
        self.id = cid
        self.name = name
        self.ip = ip
        self.room = None
        self.role = None
        self.closed = False
        self.last_solo_submit = 0.0
        self.sent: list[dict] = []

    def send(self, obj: dict) -> None:
        """记录消息。"""
        self.sent.append(obj)

    def last(self, t: str) -> dict | None:
        """取最后一条指定类型的消息。"""
        for m in reversed(self.sent):
            if m.get('t') == t:
                return m
        return None

    def count(self, t: str) -> int:
        """统计某类消息数量。"""
        return sum(1 for m in self.sent if m.get('t') == t)


class NullConfig:
    """HTTP 测试用配置桩。"""

    def __init__(self, port: int, ws_port: int = 18081):
        """保存端口。"""
        self.port = port
        self.ws_port = ws_port

        class _Data:
            pass

        self.data = {}

    def save(self) -> bool:
        """桩实现。"""
        return True


def make_service(tmpdir: str | None = None, snapshot_hz: int = 30, logger=None) -> GameService:
    """创建一套完整的服务实例（数据写到临时目录）。

    Args:
        tmpdir: 数据目录（None 时自动创建）。
        snapshot_hz: 快照频率。
        logger: 日志回调。

    Returns:
        GameService。
    """
    d = tmpdir or tempfile.mkdtemp(prefix='snake_test_')
    ip_notes = IpNotes(d)
    leaderboard = Leaderboard(d)
    custom_maps = CustomMaps(d)
    online_board = OnlineBoard(d, ip_notes)
    return GameService(leaderboard, online_board, ip_notes, custom_maps,
                       snapshot_hz=snapshot_hz, logger=logger)
