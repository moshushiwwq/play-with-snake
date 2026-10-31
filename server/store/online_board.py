"""联机排行榜存储：签名校验、降序排序、仅保留前 30 名、过滤异常数据。"""
from __future__ import annotations

import os
import random
import time

from shared.constants import MAX_RANK_ROWS
from shared.protocol import verify_record
from server.core.util import clean_name
from server.store.jsonstore import load_json, save_json


class OnlineBoard:
    """联机排行榜（落盘为 online_board.json）。"""

    def __init__(self, data_dir: str, ip_notes):
        """初始化并加载。

        Args:
            data_dir: 数据目录。
            ip_notes: IpNotes 实例（用于给每条记录附加管理员备注）。
        """
        self.path = os.path.join(data_dir, 'online_board.json')
        self.ip_notes = ip_notes
        self.data: dict = {'rows': [], 'updatedAt': 0}
        raw = load_json(self.path, {})
        if isinstance(raw, dict) and isinstance(raw.get('rows'), list):
            self.data = raw

    def save(self) -> None:
        """落盘（附带更新时间）。"""
        self.data['updatedAt'] = int(time.time() * 1000)
        save_json(self.path, self.data)

    def submit(self, raw: dict, ip: str = '') -> dict:
        """提交一条成绩：重算签名，不符即判为异常数据（不入榜）。

        Args:
            raw: 客户端上报的成绩记录（需含 sig）。
            ip: 来源 IP。

        Returns:
            {'ok': bool, 'msg': str}。
        """
        if not isinstance(raw, dict) or not verify_record(raw):
            return {'ok': False, 'msg': '数据校验失败，异常数据已被过滤'}
        rec = self._build(raw, ip)
        self.data['rows'].append(rec)
        self.data['rows'].sort(key=lambda r: (-int(r.get('score') or 0), -int(r.get('length') or 0)))
        del self.data['rows'][MAX_RANK_ROWS:]
        self.save()
        try:
            rank = self.data['rows'].index(rec) + 1
        except ValueError:
            rank = 0
        return {'ok': True, 'msg': ('成绩已记录，当前第 %d 名' % rank) if rank else '成绩已记录（未进前 30）'}

    def top(self, n: int = MAX_RANK_ROWS) -> list[dict]:
        """取前 N 名，并为每条附加 note、level 字段。

        Args:
            n: 数量。

        Returns:
            记录列表（含 ip/note）。
        """
        out = []
        for r in self.data['rows'][:n]:
            item = dict(r)
            item['note'] = self.ip_notes.get(r.get('ip', ''))
            out.append(item)
        return out

    def clear(self) -> None:
        """清空排行榜。"""
        self.data['rows'] = []
        self.save()

    def _build(self, raw: dict, ip: str) -> dict:
        """把上报记录规整成入库结构（参与签名的字段保持原样）。

        Args:
            raw: 上报记录。
            ip: 来源 IP。

        Returns:
            可入库的记录字典。
        """
        players = raw.get('players') if isinstance(raw.get('players'), list) else []
        rid = str(raw.get('id') or '')[:32] or (
            _b36(int(time.time() * 1000)) + ''.join(random.choice('0123456789abcdefghijklmnopqrstuvwxyz') for _ in range(5)))

        def _ints(v, cap=8):
            if not isinstance(v, list):
                return []
            out = []
            for x in v[:cap]:
                try:
                    out.append(int(x))
                except Exception:
                    out.append(0)
            return out

        return {
            'id': rid,
            'name': clean_name(raw.get('name') or (players[0] if players else ''), '玩家'),
            'score': max(0, min(1000000, _to_int(raw.get('score')))),
            'length': max(0, _to_int(raw.get('length'))),
            'mode': '' if raw.get('mode') is None else str(raw.get('mode'))[:16],
            'diff': '' if raw.get('diff') is None else str(raw.get('diff'))[:16],
            'mapId': '' if raw.get('mapId') is None else str(raw.get('mapId'))[:24],
            'mapName': str(raw.get('mapName') or '')[:24],
            'players': [str(x)[:24] for x in players[:8]],
            'scores': _ints(raw.get('scores')),
            'levels': _ints(raw.get('levels')),
            'lens': _ints(raw.get('lens')),
            'duration': None if raw.get('duration') is None else _to_int(raw.get('duration')),
            'date': str(raw.get('date') or time.strftime('%Y-%m-%d'))[:19],
            'ip': ip or '',
            'level': _to_int(raw.get('level')),
            'sig': str(raw.get('sig') or ''),
        }


def _to_int(v) -> int:
    """安全转整数（失败返回 0）。"""
    try:
        return int(v)
    except Exception:
        return 0


def _b36(n: int) -> str:
    """把整数转成 36 进制字符串（生成记录 id 用）。"""
    chars = '0123456789abcdefghijklmnopqrstuvwxyz'
    if n == 0:
        return '0'
    out = []
    while n:
        n, r = divmod(n, 36)
        out.append(chars[r])
    return ''.join(reversed(out))
