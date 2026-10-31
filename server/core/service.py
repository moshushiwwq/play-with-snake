"""游戏服务门面：持有房间/连接/存储，驱动 tick 与消息分发。

网络层（HTTP / WebSocket）只负责搬运数据，所有规则都在这里与 core 中完成。
"""
from __future__ import annotations

import itertools
import random
import threading
import time

from shared.constants import DIFFS, MAX_ROOMS, ROOM_CODE_CHARS
from server.core import world
from server.core.protocol import handle_message
from server.core.util import clean_name  # noqa: F401  （对外复用的工具函数）


class GameService:
    """联机服务核心。

    Attributes:
        rooms: 房间码 -> Room。
        conns: 当前连接集合。
        snapshot_hz: 快照下发频率（Hz）。
    """

    def __init__(self, leaderboard, online_board, ip_notes, custom_maps,
                 snapshot_hz: int = 30, logger=None):
        """初始化服务。

        Args:
            leaderboard: 玩家统计存储。
            online_board: 联机排行榜存储。
            ip_notes: IP 备注存储。
            custom_maps: 自制地图存储。
            snapshot_hz: 快照频率。
            logger: 日志回调 fn(text, level='info')。
        """
        self.leaderboard = leaderboard
        self.online_board = online_board
        self.ip_notes = ip_notes
        self.custom_maps = custom_maps
        self.snapshot_hz = max(5, min(60, int(snapshot_hz or 30)))
        self.rooms: dict[str, object] = {}
        self.conns: set = set()
        self.diffs = DIFFS
        self._ids = itertools.count(1)
        self._snap_acc = 0.0
        self._logger = logger
        self.on_change = None      # GUI 可挂回调，用于刷新表格
        # HTTP 线程与 Qt 主线程都会读写房间/排行数据，统一用可重入锁保护
        self.lock = threading.RLock()

    # ---------------------------------------------------------------- 工具
    def next_conn_id(self) -> int:
        """分配一个新的连接 id。"""
        return next(self._ids)

    def log(self, text: str, level: str = 'info') -> None:
        """写入一条日志。

        Args:
            text: 文本。
            level: info/ok/warn/error。
        """
        if self._logger:
            try:
                self._logger(text, level)
            except Exception:
                pass

    def _changed(self) -> None:
        """通知外层状态发生变化（房间/排行榜等）。"""
        if self.on_change:
            try:
                self.on_change()
            except Exception:
                pass

    def resolve_map(self, map_id: str) -> dict:
        """解析地图 id（经典或自制）。"""
        return world.resolve_map(map_id, self.custom_maps)

    def map_list(self) -> list[dict]:
        """可用地图清单（经典 + 自制）。"""
        return world.map_list(self.custom_maps)

    def new_code(self) -> str | None:
        """生成一个未占用的 4 位房间码。

        Returns:
            房间码或 None（多次尝试仍冲突时）。
        """
        for _ in range(300):
            code = ''.join(random.choice(ROOM_CODE_CHARS) for _ in range(4))
            if code not in self.rooms:
                return code
        return None

    # ---------------------------------------------------------------- 连接
    def add_conn(self, conn) -> None:
        """登记一个连接。

        Args:
            conn: 连接对象（需含 id/name/ip/room/role/closed/send）。
        """
        self.conns.add(conn)

    def remove_conn(self, conn) -> None:
        """连接断开时清理其房间关系并广播大厅。

        Args:
            conn: 连接对象。
        """
        room = getattr(conn, 'room', None)
        if room is not None:
            kind = room.remove_by_conn(conn)
            conn.room = None
            conn.role = None
            if kind == 'player':
                room.broadcast({'t': 'sys', 'msg': (conn.name or '玩家') + ' 离开了房间'})
                if room.host_id == conn.id and room.players:
                    room.host_id = room.players[0]['id']
                    room.broadcast({'t': 'sys', 'msg': room.players[0]['name'] + ' 成为新房主'})
            if not room.players and not room.spectators:
                self.rooms.pop(room.code, None)
                self.log('房间 %s 已解散（无人）' % room.code)
            else:
                room.send_room()
                room.try_auto_start()
        self.conns.discard(conn)
        self.broadcast_lobby()
        self._changed()

    def handle(self, conn, text: str) -> None:
        """处理一条客户端文本消息。

        Args:
            conn: 来源连接。
            text: JSON 文本。
        """
        with self.lock:
            handle_message(self, conn, text)
            self._changed()

    # ---------------------------------------------------------------- 大厅
    def public_rooms(self) -> list[dict]:
        """公开房间列表（等待中的排前面，人多优先）。"""
        out = [r.public_info() for r in self.rooms.values() if r.settings['isPublic']]
        out.sort(key=lambda a: (0 if a['state'] == 'waiting' else 1, -a['count']))
        return out

    def player_count(self) -> int:
        """房间内玩家总数。"""
        return sum(len(r.players) for r in self.rooms.values())

    def match_count(self) -> int:
        """正在进行的对局数。"""
        return sum(1 for r in self.rooms.values() if r.game is not None and r.game.phase == 'playing')

    def broadcast_all(self, obj: dict) -> None:
        """向所有连接广播。"""
        for c in list(self.conns):
            if not getattr(c, 'closed', False):
                c.send(obj)

    def broadcast_lobby(self) -> None:
        """向不在房间内的连接广播大厅概览。"""
        msg = {
            't': 'lobby', 'rooms': self.public_rooms(), 'online': len(self.conns),
            'playing': self.player_count(), 'matches': self.match_count(),
        }
        for c in list(self.conns):
            if not getattr(c, 'closed', False) and getattr(c, 'room', None) is None:
                c.send(msg)

    # ---------------------------------------------------------------- 驱动
    def tick(self, dt_ms: float) -> None:
        """推进所有房间并把快照按设定频率下发。

        Args:
            dt_ms: 距上一 tick 的毫秒数。
        """
        with self.lock:
            self._tick_locked(dt_ms)

    def _tick_locked(self, dt_ms: float) -> None:
        """tick 的实际实现（调用方需持有 self.lock）。"""
        now = time.time()
        for room in list(self.rooms.values()):
            if room.game is not None:
                step_ms = 1000.0 / max(1, room.game.diff['speed'])
                room.tick_acc += dt_ms
                guard = 0
                while room.tick_acc >= step_ms and guard < 10:
                    room.tick_acc -= step_ms
                    room.game.step()
                    guard += 1
                    if room.game.phase == 'over':
                        room.state = 'over'
                        break
            # 全员准备自动开局
            if room.auto_start_at and now >= room.auto_start_at:
                room.auto_start_at = 0.0
                if room.state == 'waiting' and len(room.players) >= 2 and \
                        all(p['ready'] for p in room.players):
                    room.start_game('全员准备')

        # 快照
        self._snap_acc += dt_ms
        snap_ms = 1000.0 / self.snapshot_hz
        if self._snap_acc >= snap_ms:
            self._snap_acc = 0.0
            for room in self.rooms.values():
                g = room.game
                if g is None:
                    continue
                events = g.events[:40]
                if events:
                    del g.events[:40]
                room.broadcast({'t': 'state', 's': g.snapshot(), 'events': events})

    # ---------------------------------------------------------------- 查询
    def discover_info(self, version: str, port: int, ws_port: int) -> dict:
        """构造内网发现响应（客户端搜索功能识别用）。

        Args:
            version: 服务端版本。
            port: HTTP 端口。
            ws_port: WebSocket 端口。

        Returns:
            发现信息字典。
        """
        import socket
        try:
            host = socket.gethostname()
        except Exception:
            host = ''
        return {
            'ok': True, 'app': 'snake-lan-server', 'name': '贪吃蛇大冒险', 'version': version,
            'port': port, 'wsPort': ws_port,
            'rooms': len(self.rooms), 'players': self.player_count(),
            'online': len(self.conns), 'host': host,
        }

    def max_rooms(self) -> int:
        """房间上限常量。"""
        return MAX_ROOMS
