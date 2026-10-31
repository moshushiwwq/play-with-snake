"""玩家统计存储：昵称、来源 IP、单机成绩与联机战绩。"""
from __future__ import annotations

import os
import time

from server.store.jsonstore import load_json, save_json


class Leaderboard:
    """玩家统计（落盘为 leaderboard.json）。"""

    def __init__(self, data_dir: str):
        """初始化并加载。

        Args:
            data_dir: 数据目录。
        """
        self.path = os.path.join(data_dir, 'leaderboard.json')
        self.data: dict[str, dict] = {'players': {}, 'updatedAt': 0}
        raw = load_json(self.path, {})
        if isinstance(raw, dict) and isinstance(raw.get('players'), dict):
            self.data = raw

    def save(self) -> None:
        """落盘（附带更新时间）。"""
        self.data['updatedAt'] = int(time.time() * 1000)
        save_json(self.path, self.data)

    def entry(self, name: str) -> dict:
        """取（或创建）某玩家的统计记录。

        Args:
            name: 昵称。

        Returns:
            统计记录字典。
        """
        e = self.data['players'].get(name)
        if not e:
            e = {
                'name': name, 'soloBest': 0, 'soloGames': 0, 'mpGames': 0,
                'wins': 0, 'score': 0, 'best': 0, 'kills': 0, 'lastPlayed': 0,
            }
            self.data['players'][name] = e
        return e

    def get(self, name: str) -> dict | None:
        """取某玩家统计（不存在返回 None）。"""
        return self.data['players'].get(name) if name else None

    def solo(self, name: str, score: int, length: int, ip: str = '') -> None:
        """记录一次单机成绩。

        Args:
            name: 昵称。
            score: 分数。
            length: 蛇身长度。
            ip: 来源 IP。
        """
        if not name or not (score > 0):
            return
        e = self.entry(name)
        if ip:
            e['ip'] = ip
        e['soloGames'] += 1
        e['score'] += score
        e['best'] = max(e['best'], score, length or 0)
        e['soloBest'] = max(e['soloBest'], score)
        e['lastPlayed'] = int(time.time() * 1000)
        self.save()

    def match(self, rows: list[dict]) -> None:
        """记录一局联机结果。

        Args:
            rows: [{name, score, kills, win}]。
        """
        seen = set()
        for r in rows:
            name = r.get('name')
            if not name:
                continue
            e = self.entry(name)
            seen.add(name)
            e['mpGames'] += 1
            e['score'] += max(0, int(r.get('score') or 0))
            e['best'] = max(e['best'], int(r.get('score') or 0))
            if r.get('kills'):
                e['kills'] += int(r.get('kills') or 0)
            if r.get('win'):
                e['wins'] += 1
            e['lastPlayed'] = int(time.time() * 1000)
        if seen:
            self.save()

    def top(self, limit: int = 30) -> list[dict]:
        """按总分/胜场/场次排序取前若干名。

        Args:
            limit: 数量。

        Returns:
            统计记录列表。
        """
        lst = list(self.data['players'].values())
        lst.sort(key=lambda a: (-(a.get('score') or 0), -(a.get('wins') or 0), -(a.get('mpGames') or 0)))
        return lst[:limit]

    def register_player(self, name: str, ip: str = '') -> None:
        """登记一名提交过成绩的玩家（供后台「联机用户与 IP」展示）。

        Args:
            name: 昵称。
            ip: 来源 IP。
        """
        if not name:
            return
        e = self.entry(name)
        if ip:
            e['ip'] = ip
        e['lastPlayed'] = int(time.time() * 1000)
        self.save()
