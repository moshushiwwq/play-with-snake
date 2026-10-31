"""房间模型：成员管理、房间设置、开局/再来一局与房间快照。

移植自原 Node 版 Room 类，字段与消息结构保持一致。
"""
from __future__ import annotations

import hashlib
import time

from shared.constants import COLORS
from server.core.game import Game


def hash_pass(password: str) -> str:
    """房间密码哈希（sha256('snake|'+密码) 取前 16 位十六进制，与旧版一致）。

    Args:
        password: 明文密码。

    Returns:
        16 位十六进制字符串。
    """
    return hashlib.sha256(('snake|' + str(password)).encode('utf-8')).hexdigest()[:16]


class Room:
    """一个联机房间。

    Attributes:
        code: 4 位房间码（大写，去易混字符）。
        players: 玩家列表 [{id, conn, name, color, ready}]。
        spectators: 观战者列表 [{id, conn, name}]。
        game: 当前对局（Game 或 None）。
        state: waiting / playing / over。
    """

    def __init__(self, service, host_conn, settings: dict):
        """创建房间。

        Args:
            service: GameService。
            host_conn: 房主连接。
            settings: {maxPlayers, map, diff, password, isPublic}。
        """
        self.service = service
        self.code = service.new_code()
        self.host_id = host_conn.id
        self.settings = {
            'maxPlayers': int(settings.get('maxPlayers', 4)),
            'map': settings.get('map', 'classic'),
            'diff': settings.get('diff', 'normal'),
            'password': str(settings.get('password', '') or ''),
            'isPublic': bool(settings.get('isPublic', True)),
        }
        self.players: list[dict] = []
        self.spectators: list[dict] = []
        self.game: Game | None = None
        self.round = 0
        self.last_result: list[dict] | None = None
        self.created_at = time.time()
        self.state = 'waiting'
        self.rematch_votes: set[int] = set()
        self.tick_acc = 0.0
        self.auto_start_at = 0.0
        self.pass_hash = hash_pass(self.settings['password']) if self.settings['password'] else None

    @property
    def is_full(self) -> bool:
        """房间是否已满。"""
        return len(self.players) >= self.settings['maxPlayers']

    def map_def(self) -> dict:
        """解析当前设置对应的地图（含自制图）。"""
        return self.service.resolve_map(self.settings['map'])

    def add_player(self, conn, name: str) -> dict:
        """把连接加入为玩家，自动分配未使用的颜色。

        Args:
            conn: 连接对象。
            name: 玩家昵称。

        Returns:
            新玩家记录。
        """
        used = [p['color'] for p in self.players]
        color = next((c for c in COLORS if c not in used), COLORS[0])
        p = {'id': conn.id, 'conn': conn, 'name': name, 'color': color, 'ready': False}
        self.players.append(p)
        conn.room = self
        conn.role = 'player'
        return p

    def remove_by_conn(self, conn) -> str | None:
        """从房间移除某个连接。

        Args:
            conn: 连接对象。

        Returns:
            'player' / 'spectator' / None。
        """
        for i, p in enumerate(self.players):
            if p['conn'] is conn:
                self.players.pop(i)
                return 'player'
        for i, s in enumerate(self.spectators):
            if s['conn'] is conn:
                self.spectators.pop(i)
                return 'spectator'
        return None

    def public_info(self) -> dict:
        """房间公示信息（大厅列表、房间页共用）。"""
        m = self.map_def()
        diff = self.service.diffs.get(self.settings['diff'], self.service.diffs['normal'])
        host = next((p for p in self.players if p['id'] == self.host_id), None)
        return {
            'code': self.code,
            'host': host['name'] if host else '-',
            'count': len(self.players),
            'max': self.settings['maxPlayers'],
            'map': self.settings['map'],
            'mapName': m['name'],
            'diff': self.settings['diff'],
            'diffName': diff['name'],
            'hasPass': bool(self.pass_hash),
            'isPublic': bool(self.settings['isPublic']),
            'state': self.state,
            'round': self.round,
            'isFull': self.is_full,
            'players': [{'name': p['name'], 'color': p['color'], 'ready': p['ready'],
                         'host': p['id'] == self.host_id} for p in self.players],
        }

    def broadcast(self, obj: dict) -> None:
        """向房间内所有玩家与观战者广播一条消息。

        Args:
            obj: 消息字典。
        """
        for p in self.players:
            p['conn'].send(obj)
        for s in self.spectators:
            s['conn'].send(obj)

    def send_room(self, target=None) -> None:
        """下发房间快照：target 收个性化版本，其余人收 roomUpdate。

        Args:
            target: 指定连接（可为 None 表示全部广播）。
        """
        if target is not None and not target.closed:
            me = next((p for p in self.players if p['conn'] is target), None)
            spec = next((s for s in self.spectators if s['conn'] is target), None)
            target.send({
                't': 'room', 'room': self.public_info(),
                'self': ({'name': me['name'], 'host': me['id'] == self.host_id,
                          'spectate': False, 'color': me['color']} if me else
                         ({'name': spec['name'], 'host': False, 'spectate': True} if spec else None)),
                'players': [{'name': p['name'], 'color': p['color'], 'ready': p['ready'],
                             'host': p['id'] == self.host_id, 'idx': i} for i, p in enumerate(self.players)],
                'spectators': len(self.spectators),
                'readyCount': sum(1 for p in self.players if p['ready']),
            })
        for p in self.players:
            if p['conn'] is not target:
                p['conn'].send({'t': 'roomUpdate', 'room': self.public_info()})
        for s in self.spectators:
            if s['conn'] is not target:
                s['conn'].send({'t': 'roomUpdate', 'room': self.public_info()})

    def start_game(self, by_name: str = '') -> dict:
        """开始新一局。

        Args:
            by_name: 触发者昵称（展示用）。

        Returns:
            {'ok': bool, 'msg': str}。
        """
        if len(self.players) < 2:
            return {'ok': False, 'msg': '至少需要 2 名玩家'}
        if self.game is not None and self.game.phase != 'over':
            return {'ok': False, 'msg': '当前对局还没结束'}
        self.round += 1
        self.state = 'playing'
        self.rematch_votes.clear()
        self.game = Game(self, self.map_def())
        for p in self.players:
            p['ready'] = False
        self.broadcast({
            't': 'start', 'round': self.round, 'by': by_name,
            'map': self.settings['map'], 'diff': self.settings['diff'],
            'cols': self.game.cols, 'rows': self.game.rows,
            'players': [{'name': p['name'], 'color': p['color'], 'id': p['id']} for p in self.players],
        })
        self.send_room()
        self.service.log('房间 %s 第 %d 局开始，玩家 %s' % (
            self.code, self.round, '/'.join(p['name'] for p in self.players)))
        return {'ok': True}

    def end_game(self, to_lobby: bool = False) -> None:
        """结束当前对局并回到等待状态。

        Args:
            to_lobby: 是否通知客户端回到房间等待页。
        """
        self.state = 'waiting'
        self.game = None
        if to_lobby:
            self.broadcast({'t': 'toLobby'})
        self.send_room()

    def try_auto_start(self) -> None:
        """全员准备后延迟 0.9 秒自动开局（由 GameService.tick 检查时间点）。"""
        if len(self.players) < 2:
            self.auto_start_at = 0.0
            return
        if not all(p['ready'] for p in self.players):
            self.auto_start_at = 0.0
            return
        if not self.auto_start_at:
            self.auto_start_at = time.time() + 0.9
