"""自制地图存储：上传校验、落盘与查询。

地图结构（与客户端编辑器一致）：
    {id, name, author, mode, cols, rows, walls: [[x,y], ...], wallPass}
"""
from __future__ import annotations

import os
import re

from shared.constants import MAPS
from server.store.jsonstore import load_json, save_json

MAX_MAPS = 200
ID_RE = re.compile(r'^[A-Za-z0-9_-]{1,32}$')


def validate_map(raw: dict) -> tuple[dict | None, str]:
    """校验并规整一张上传的地图。

    Args:
        raw: 客户端提交的地图对象。

    Returns:
        (规整后的地图, 错误信息)；成功时错误信息为空字符串。
    """
    if not isinstance(raw, dict):
        return None, '地图数据格式错误'
    map_id = str(raw.get('id') or '').strip()
    if not ID_RE.match(map_id):
        return None, '地图 id 非法（仅允许字母、数字、下划线、短横线，最多 32 字）'
    if map_id in MAPS:
        return None, '地图 id 与经典地图冲突，请更换名称后重新保存'
    name = str(raw.get('name') or '').strip()[:24]
    if not name:
        return None, '地图名称不能为空'
    try:
        cols = int(raw.get('cols'))
        rows = int(raw.get('rows'))
    except Exception:
        return None, '地图尺寸非法'
    if not (8 <= cols <= 60 and 8 <= rows <= 60):
        return None, '地图尺寸需在 8–60 之间'
    walls = raw.get('walls')
    if not isinstance(walls, list):
        return None, '墙体数据缺失'
    out_walls: list[list[int]] = []
    seen = set()
    for w in walls[:int(cols * rows * 0.45) + 1]:
        try:
            x, y = int(w[0]), int(w[1])
        except Exception:
            return None, '墙体坐标非法'
        if not (0 <= x < cols and 0 <= y < rows):
            return None, '墙体坐标超出地图范围'
        if (x, y) in seen:
            continue
        seen.add((x, y))
        out_walls.append([x, y])
    if len(out_walls) > int(cols * rows * 0.45):
        return None, '墙体数量过多（不得超过格子的 45%）'
    mode = str(raw.get('mode') or 'single')
    if mode not in ('single', 'duel'):
        mode = 'single'
    return {
        'id': map_id,
        'name': name,
        'author': str(raw.get('author') or '')[:24],
        'mode': mode,
        'cols': cols,
        'rows': rows,
        'walls': out_walls,
        'wallPass': bool(raw.get('wallPass')),
    }, ''


class CustomMaps:
    """自制地图库（落盘为 maps.json）。"""

    def __init__(self, data_dir: str):
        """初始化并加载。

        Args:
            data_dir: 数据目录。
        """
        self.path = os.path.join(data_dir, 'maps.json')
        self.items: list[dict] = []
        raw = load_json(self.path, [])
        if isinstance(raw, list):
            self.items = [m for m in raw if isinstance(m, dict) and m.get('id')]

    def save(self) -> bool:
        """落盘。"""
        return save_json(self.path, self.items)

    def get(self, map_id: str) -> dict | None:
        """按 id 取一张地图。"""
        return next((m for m in self.items if m['id'] == map_id), None)

    def list_all(self) -> list[dict]:
        """返回全部自制地图。"""
        return list(self.items)

    def upsert(self, raw: dict) -> tuple[bool, str]:
        """上传一张地图（同 id 覆盖）。

        Args:
            raw: 客户端提交的地图。

        Returns:
            (是否成功, 提示信息)。
        """
        item, err = validate_map(raw)
        if not item:
            return False, err
        existing = self.get(item['id'])
        if existing is None and len(self.items) >= MAX_MAPS:
            return False, '服务器自制地图数量已达上限（%d 张）' % MAX_MAPS
        if existing is not None:
            self.items = [item if m['id'] == item['id'] else m for m in self.items]
        else:
            self.items.append(item)
        if not self.save():
            return False, '地图保存失败（磁盘写入错误）'
        return True, '地图「%s」已上传' % item['name']

    def delete(self, map_id: str) -> bool:
        """删除一张地图。"""
        before = len(self.items)
        self.items = [m for m in self.items if m['id'] != map_id]
        if len(self.items) == before:
            return False
        self.save()
        return True
