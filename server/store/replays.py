"""联机对局回放存储：每局落盘一个 JSON，按数量上限滚动清理。

联机对局由服务端权威引擎推进，回放帧也由服务端录制（客户端只负责播放），
因此即使玩家中途关掉页面，这一局的回放依然可以在联机排行榜里查看。
"""
from __future__ import annotations

import os
import time

from server.store.jsonstore import load_json, save_json


class ReplayStore:
    """回放文件仓库（data_dir/replays/<id>.json）。"""

    def __init__(self, data_dir: str, keep: int = 40):
        """初始化。

        Args:
            data_dir: 数据目录。
            keep: 最多保留的回放数量（超出后按时间删最旧的）。
        """
        self.dir = os.path.join(data_dir, 'replays')
        self.keep = max(5, int(keep))
        try:
            os.makedirs(self.dir, exist_ok=True)
        except Exception:
            pass

    def save(self, rid: str, payload: dict) -> bool:
        """写入一条回放。

        Args:
            rid: 回放 id（同时作为文件名）。
            payload: {rec: 记录信息, frames: 帧数组}。

        Returns:
            是否写入成功。
        """
        rid = ''.join(ch for ch in str(rid or '') if ch.isalnum() or ch in '-_')[:40]
        if not rid:
            return False
        path = os.path.join(self.dir, rid + '.json')
        ok = save_json(path, payload)
        if ok:
            self._prune()
        return bool(ok)

    def load(self, rid: str) -> dict | None:
        """读取一条回放。

        Args:
            rid: 回放 id。

        Returns:
            {'rec':..., 'frames':...} 或 None（不存在/损坏）。
        """
        rid = ''.join(ch for ch in str(rid or '') if ch.isalnum() or ch in '-_')[:40]
        if not rid:
            return None
        data = load_json(os.path.join(self.dir, rid + '.json'), None)
        if not isinstance(data, dict) or not isinstance(data.get('frames'), list):
            return None
        return data

    def count(self) -> int:
        """当前回放文件数量。"""
        try:
            return len([n for n in os.listdir(self.dir) if n.endswith('.json')])
        except Exception:
            return 0

    def _prune(self) -> None:
        """超出保留数量时删除最旧的回放文件。"""
        try:
            items = []
            for name in os.listdir(self.dir):
                if not name.endswith('.json'):
                    continue
                p = os.path.join(self.dir, name)
                try:
                    items.append((os.path.getmtime(p), p))
                except Exception:
                    continue
            if len(items) <= self.keep:
                return
            items.sort()
            for _, p in items[:len(items) - self.keep]:
                try:
                    os.remove(p)
                except Exception:
                    pass
        except Exception:
            pass


def new_replay_id() -> str:
    """生成一个回放 id（时间戳 36 进制 + 3 位随机后缀）。"""
    import random

    n = int(time.time() * 1000)
    chars = '0123456789abcdefghijklmnopqrstuvwxyz'
    out = []
    while n:
        n, r = divmod(n, 36)
        out.append(chars[r])
    return 'o' + ''.join(reversed(out)) + ''.join(random.choice(chars) for _ in range(3))
