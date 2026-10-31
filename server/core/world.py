"""地图解析：经典地图与用户上传的自制地图统一成 Game 可用的结构。"""
from __future__ import annotations

from shared.constants import MAPS


def classic_map_entry(map_id: str) -> dict:
    """取一张经典地图。

    Args:
        map_id: 地图 id。

    Returns:
        含 id/name/cols/rows/obstacles 的地图字典（不存在时回落到 classic）。
    """
    m = MAPS.get(map_id) or MAPS['classic']
    return {
        'id': m['id'],
        'name': m['name'],
        'cols': m['cols'],
        'rows': m['rows'],
        'obstacles': [{'x': o[0], 'y': o[1]} for o in m.get('obstacles', [])],
        'custom': False,
    }


def resolve_map(map_id: str, custom_store=None) -> dict:
    """解析建房时使用的地图 id（优先经典，其次自制）。

    Args:
        map_id: 客户端传入的地图 id。
        custom_store: 自制地图存储对象（需提供 get(map_id)）。

    Returns:
        Game 可直接使用的地图字典；两者都不存在时回落到经典空地。
    """
    if map_id in MAPS:
        return classic_map_entry(map_id)
    if custom_store is not None:
        cm = custom_store.get(map_id)
        if cm:
            return {
                'id': cm['id'],
                'name': cm['name'],
                'cols': int(cm['cols']),
                'rows': int(cm['rows']),
                'obstacles': [{'x': int(w[0]), 'y': int(w[1])} for w in cm.get('walls', [])],
                'custom': True,
            }
    return classic_map_entry('classic')


def map_list(custom_store=None) -> list[dict]:
    """构建下发给客户端的可用地图清单。

    Args:
        custom_store: 自制地图存储对象。

    Returns:
        [{id,name,cols,rows,custom}] 列表，经典在前、自制在后。
    """
    out = [{'id': m['id'], 'name': m['name'], 'cols': m['cols'], 'rows': m['rows'], 'custom': False}
           for m in MAPS.values()]
    if custom_store is not None:
        for cm in custom_store.list_all():
            out.append({
                'id': cm['id'], 'name': cm['name'],
                'cols': int(cm['cols']), 'rows': int(cm['rows']), 'custom': True,
            })
    return out
