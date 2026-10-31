"""协议常量：签名算法、经典地图、难度、房间与连接限制。

本文件由客户端（经 JS 等价实现）与服务端共用同一套数值；
任何一项改动都必须同步客户端 `client/web/index.html` 中的同名常量。
"""
from __future__ import annotations

# 篡改校验密钥（客户端与服务端必须一字不差）
SIGN_SECRET = 'snake-magic-2026-v3'

# 房间/连接限制（与原 Node 版保持一致）
MAX_NAME_LEN = 12
MAX_ROOMS = 200
MAX_CONNS = 300
MAX_RANK_ROWS = 30
ROOM_CODE_CHARS = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'

# 玩家配色（按顺序分配，最多 4 人）
COLORS = ['#34e39b', '#38bdf8', '#fbbf24', '#f472b6']

# 四方向
DIRS = [(1, 0), (-1, 0), (0, 1), (0, -1)]

# 服务端权威判定的 tick 间隔（毫秒）
TICK_MS = 10

# 难度：speed = 每秒推进格数；grow = 每吃一个食物增长节数；food = 场上食物数；power = 道具生成基数
DIFFS = {
    'easy': {'name': '休闲', 'speed': 7, 'grow': 3, 'food': 6, 'power': 180},
    'normal': {'name': '普通', 'speed': 9, 'grow': 3, 'food': 5, 'power': 140},
    'hard': {'name': '困难', 'speed': 12, 'grow': 4, 'food': 4, 'power': 110},
    'insane': {'name': '疯狂', 'speed': 15, 'grow': 5, 'food': 4, 'power': 90},
}


def _build_obstacles(map_id: str, cols: int, rows: int) -> list[list[int]]:
    """按地图 id 生成墙体坐标（与原 Node 版 buildObstacles 完全一致）。

    Args:
        map_id: 地图标识（cross/pillars/tunnel/arena，其它返回空）。
        cols: 列数。
        rows: 行数。

    Returns:
        [[x, y], ...] 墙体坐标列表。
    """
    walls: set[tuple[int, int]] = set()

    def add(x: int, y: int) -> None:
        if 0 <= x < cols and 0 <= y < rows:
            walls.add((x, y))

    cx, cy = cols // 2, rows // 2
    if map_id == 'cross':
        for i in range(-6, 7):
            add(cx + i, cy)
            add(cx, cy + i)
        for i in range(-2, 3):
            walls.discard((cx + i, cy))
            walls.discard((cx, cy + i))
    elif map_id == 'pillars':
        for x in range(5, cols - 4, 7):
            for y in range(4, rows - 3, 6):
                if abs(x - cx) < 4 and abs(y - cy) < 4:
                    continue
                add(x, y)
                add(x + 1, y)
    elif map_id == 'tunnel':
        for x in range(4, cols - 4):
            add(x, 4)
            add(x, rows - 5)
        for y in range(4, rows - 4):
            add(4, y)
            add(cols - 5, y)
        for i in range(-3, 4):
            walls.discard((cx + i, 4))
            walls.discard((cx + i, rows - 5))
            walls.discard((4, cy + i))
            walls.discard((cols - 5, cy + i))
    elif map_id == 'arena':
        for i in range(-5, 6):
            add(cx + i, cy - 6)
            add(cx + i, cy + 6)
            add(cx - 6, cy + i)
            add(cx + 6, cy + i)
        for i in range(-3, 4):
            walls.discard((cx + i, cy - 6))
            walls.discard((cx, cy + i))
            walls.discard((cx + i, cy + 6))
    return [[x, y] for (x, y) in sorted(walls)]


# 经典地图（obstacles 在导入时填充）
MAPS: dict[str, dict] = {
    'classic': {'name': '经典空地', 'desc': '无障碍，纯走位', 'cols': 48, 'rows': 36},
    'cross': {'name': '十字迷宫', 'desc': '中央十字墙', 'cols': 48, 'rows': 36},
    'pillars': {'name': '石柱阵', 'desc': '均匀石柱，考验绕行', 'cols': 48, 'rows': 36},
    'tunnel': {'name': '回字走廊', 'desc': '外圈留墙，中间开阔', 'cols': 48, 'rows': 36},
    'arena': {'name': '竞技场', 'desc': '四周与中央小墙', 'cols': 52, 'rows': 38},
}

for _id, _m in MAPS.items():
    _m['id'] = _id
    _m.setdefault('obstacles', [])
    if not _m['obstacles']:
        _m['obstacles'] = _build_obstacles(_id, _m['cols'], _m['rows'])
