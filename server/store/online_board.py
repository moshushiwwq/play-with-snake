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

    def submit_auto(self, info: dict, ip: str, score: int, length: int, replay_id: str = '') -> dict:
        """服务端自动入榜（联机对局结束时由服务端直接写入，不经客户端上报）。

        与客户端上报的区别：
        - 展示名称固定为玩家 IP（IP 超过昵称长度上限也不截断）；
        - 不校验客户端签名（数据来自服务端权威引擎）；
        - 同一 IP 且分数完全相同的记录只保留更早的那一条。

        Args:
            info: 对局元信息（mode/diff/mapId/mapName/players/scores/lens/duration/date）。
            ip: 玩家来源 IP。
            score: 该玩家的分数。
            length: 该玩家的蛇长。
            replay_id: 共享回放 id（无回放时为空）。

        Returns:
            {'ok': bool, 'dup': bool, 'msg': str}。
        """
        name = _ip_name(ip)
        try:
            score = max(0, min(1000000, int(score)))
        except Exception:
            score = 0
        try:
            length = max(0, int(length))
        except Exception:
            length = 0

        # 同 IP 同分只保留更早的那条
        for row in self.data['rows']:
            if str(row.get('ip') or '') == str(ip or '') and int(row.get('score') or 0) == score:
                return {'ok': True, 'dup': True, 'msg': '同 IP 同分记录已存在，保留更早的一条'}

        players = info.get('players') if isinstance(info.get('players'), list) else []
        rec = {
            'id': _b36(int(time.time() * 1000)) + ''.join(
                random.choice('0123456789abcdefghijklmnopqrstuvwxyz') for _ in range(5)),
            'name': name,
            'score': score,
            'length': length,
            'mode': str(info.get('mode') or 'duel')[:16],
            'diff': str(info.get('diff') or '')[:16],
            'mapId': str(info.get('mapId') or '')[:24],
            'mapName': str(info.get('mapName') or '')[:24],
            'players': [str(x)[:24] for x in players[:8]],
            'scores': _ints(info.get('scores')),
            'levels': _ints(info.get('levels')),
            'lens': _ints(info.get('lens')),
            'duration': _to_int(info.get('duration')),
            'date': str(info.get('date') or time.strftime('%Y-%m-%d'))[:19],
            'ip': ip or '',
            'level': 0,
            'sig': '',
            'auto': True,
            'replayId': str(replay_id or '')[:40],
            'hasReplay': bool(replay_id),
        }
        self.data['rows'].append(rec)
        self.data['rows'].sort(key=lambda r: (-int(r.get('score') or 0), -int(r.get('length') or 0)))
        del self.data['rows'][MAX_RANK_ROWS:]
        self.save()
        return {'ok': True, 'dup': False, 'msg': '成绩已自动入榜（%s）' % name}

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


def _ip_name(ip: str) -> str:
    """把 IP 转成榜单展示名（不截断、仅过滤控制字符）。

    Args:
        ip: 来源 IP。

    Returns:
        展示名称（无 IP 时为「未知IP」）。
    """
    s = ''.join(ch for ch in str(ip or '') if 0x20 <= ord(ch) != 0x7F)
    return s.strip() or '未知IP'


def _ints(v, cap: int = 8) -> list[int]:
    """把任意列表安全规整为整数列表（最多 cap 个）。"""
    if not isinstance(v, list):
        return []
    out = []
    for x in v[:cap]:
        try:
            out.append(int(x))
        except Exception:
            out.append(0)
    return out


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
