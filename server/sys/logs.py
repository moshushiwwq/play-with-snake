"""日志总线：线程安全收集、界面增量拉取与文件落盘。"""
from __future__ import annotations

import os
import queue
import threading
import time


class LogBus:
    """日志总线。

    网络线程与 GUI 线程都会写日志，这里统一入队；GUI 用定时器调用 `drain()`
    取走增量并显示，同时写入 server_data/server.log（超过 2 MB 时轮转一份 .1）。
    """

    def __init__(self, data_dir: str, max_memory: int = 3000):
        """初始化。

        Args:
            data_dir: 数据目录。
            max_memory: 内存中保留的最近日志条数。
        """
        self.path = os.path.join(data_dir, 'server.log')
        self._q: queue.Queue = queue.Queue()
        self._recent: list[dict] = []
        self._lock = threading.Lock()
        self._max = max_memory

    def push(self, text: str, level: str = 'info') -> None:
        """写入一条日志（任意线程可调用）。

        Args:
            text: 文本。
            level: info/ok/warn/error。
        """
        item = {'ts': time.strftime('%H:%M:%S'), 'level': level, 'text': str(text)}
        with self._lock:
            self._recent.append(item)
            if len(self._recent) > self._max:
                del self._recent[:len(self._recent) - self._max]
        self._q.put(item)
        self._append_file(item)

    def _append_file(self, item: dict) -> None:
        """追加到日志文件（超限时轮转）。

        Args:
            item: 日志项。
        """
        try:
            if os.path.exists(self.path) and os.path.getsize(self.path) > 2 * 1024 * 1024:
                bak = self.path + '.1'
                try:
                    if os.path.exists(bak):
                        os.remove(bak)
                    os.replace(self.path, bak)
                except Exception:
                    pass
            with open(self.path, 'a', encoding='utf-8') as f:
                f.write('[%s] %s\n' % (item['ts'], item['text']))
        except Exception:
            pass

    def drain(self, limit: int = 300) -> list[dict]:
        """取走增量日志（仅供 GUI 线程调用）。

        Args:
            limit: 单次最多取走的条数。

        Returns:
            日志项列表。
        """
        out = []
        for _ in range(limit):
            try:
                out.append(self._q.get_nowait())
            except queue.Empty:
                break
        return out

    def recent(self, limit: int = 200) -> list[dict]:
        """读取最近日志（用于界面初始化）。

        Args:
            limit: 条数。

        Returns:
            日志项列表。
        """
        with self._lock:
            return self._recent[-limit:]

    def entries(self, limit: int = 300, level: str = 'all') -> list[dict]:
        """读取日志（可按级别过滤），供管理面板拉取完整列表。

        Args:
            limit: 最多返回的条数（不超过内存上限）。
            level: all / info（含成功）/ warn（警告与错误）/ error。

        Returns:
            日志项列表（时间从旧到新）。
        """
        with self._lock:
            items = list(self._recent)
        want = {
            'warn': ('warn', 'error'),
            'error': ('error',),
            'info': ('info', 'ok'),
        }.get(str(level or 'all').lower())
        if want:
            items = [it for it in items if it.get('level') in want]
        cap = max(1, min(int(limit or 300), self._max))
        return items[-cap:]

    def stats(self) -> dict:
        """返回日志存储状态（内存条数、文件大小、路径）。

        Returns:
            状态字典。
        """
        with self._lock:
            memory = len(self._recent)
        size = self._size(self.path)
        backup = self._size(self.path + '.1')
        return {
            'memory': memory, 'maxMemory': self._max,
            'fileSize': size, 'backupSize': backup,
            'name': os.path.basename(self.path),
        }

    @staticmethod
    def _size(path: str) -> int:
        """安全读取文件大小（不存在返回 0）。

        Args:
            path: 文件路径。

        Returns:
            字节数。
        """
        try:
            return os.path.getsize(path) if os.path.exists(path) else 0
        except Exception:
            return 0

    def read_file(self, limit: int = 800) -> list[dict]:
        """读取日志文件尾部（进程重启后内存为空时用于回显历史）。

        Args:
            limit: 最多返回的行数。

        Returns:
            日志项列表（时间从旧到新，级别未知记为 info）。
        """
        try:
            with open(self.path, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()
        except Exception:
            return []
        out = []
        for line in lines[-max(1, limit):]:
            text = line.rstrip('\n')
            if not text:
                continue
            ts, body = '', text
            if text.startswith('[') and ']' in text:
                ts, _, body = text[1:].partition(']')
                body = body.strip()
            out.append({'ts': ts, 'level': 'info', 'text': body})
        return out

    def clear_file(self) -> None:
        """清空日志文件（保留内存记录）。"""
        try:
            open(self.path, 'w', encoding='utf-8').close()
        except Exception:
            pass
