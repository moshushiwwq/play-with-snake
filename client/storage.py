"""客户端本地存储（QtSql SQLite）：操作日志、自制地图与键值缓存。

使用 Qt 框架内置的 QSqlDatabase(SQLITE) 驱动，无需额外依赖。
"""
from __future__ import annotations

import json
import os
import time

from PyQt6.QtSql import QSqlDatabase, QSqlQuery

from client.config import app_data_dir


class ClientStorage:
    """客户端数据库。"""

    def __init__(self):
        """打开数据库并建表。"""
        self.path = os.path.join(app_data_dir(), 'client.db')
        self.db = QSqlDatabase.addDatabase('QSQLITE', 'client')
        self.db.setDatabaseName(self.path)
        if not self.db.open():
            raise RuntimeError('无法打开客户端数据库：' + self.db.lastError().text())
        self._migrate()

    def _migrate(self) -> None:
        """建表（幂等）。"""
        q = QSqlQuery(self.db)
        q.exec("""
            CREATE TABLE IF NOT EXISTS op_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts INTEGER NOT NULL,
                kind TEXT NOT NULL,
                detail TEXT
            )
        """)
        q.exec("""
            CREATE TABLE IF NOT EXISTS custom_maps (
                id TEXT PRIMARY KEY,
                name TEXT,
                payload TEXT,
                updated_at INTEGER
            )
        """)
        q.exec("""
            CREATE TABLE IF NOT EXISTS kv (
                k TEXT PRIMARY KEY,
                v TEXT
            )
        """)

    # ---------------------------------------------------------------- 日志
    def save_log(self, kind: str, detail: str, ts: int | None = None) -> bool:
        """写入一条用户操作日志。

        Args:
            kind: 操作类型。
            detail: 细节。
            ts: 时间戳（毫秒，缺省取当前）。

        Returns:
            成功返回 True。
        """
        q = QSqlQuery(self.db)
        q.prepare('INSERT INTO op_logs (ts, kind, detail) VALUES (?, ?, ?)')
        q.addBindValue(int(ts or time.time() * 1000))
        q.addBindValue(str(kind))
        q.addBindValue(str(detail))
        return q.exec()

    def list_logs(self, limit: int = 200) -> list[dict]:
        """读取最近的日志。

        Args:
            limit: 条数。

        Returns:
            [{ts,kind,detail}]。
        """
        q = QSqlQuery(self.db)
        q.prepare('SELECT ts, kind, detail FROM op_logs ORDER BY id DESC LIMIT ?')
        q.addBindValue(int(limit))
        out = []
        if q.exec():
            while q.next():
                out.append({'ts': q.value(0), 'kind': q.value(1), 'detail': q.value(2)})
        return out

    def export_logs(self, path: str) -> bool:
        """导出全部日志为 JSON 文件。

        Args:
            path: 目标文件路径。

        Returns:
            成功返回 True。
        """
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(self.list_logs(100000), f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False

    # ---------------------------------------------------------------- 地图
    def save_maps(self, maps: list[dict]) -> bool:
        """整体替换自制地图库。

        Args:
            maps: 地图对象列表。

        Returns:
            成功返回 True。
        """
        q = QSqlQuery(self.db)
        if not q.exec('DELETE FROM custom_maps'):
            return False
        now = int(time.time() * 1000)
        for m in maps or []:
            if not isinstance(m, dict) or not m.get('id'):
                continue
            q2 = QSqlQuery(self.db)
            q2.prepare('INSERT OR REPLACE INTO custom_maps (id, name, payload, updated_at) VALUES (?, ?, ?, ?)')
            q2.addBindValue(str(m.get('id')))
            q2.addBindValue(str(m.get('name') or ''))
            q2.addBindValue(json.dumps(m, ensure_ascii=False))
            q2.addBindValue(now)
            q2.exec()
        return True

    def list_maps(self) -> list[dict]:
        """读取全部自制地图。"""
        q = QSqlQuery(self.db)
        out = []
        if q.exec('SELECT payload FROM custom_maps ORDER BY updated_at DESC'):
            while q.next():
                try:
                    out.append(json.loads(q.value(0)))
                except Exception:
                    pass
        return out

    # ---------------------------------------------------------------- KV
    def set_kv(self, key: str, value: str) -> None:
        """写入键值。"""
        q = QSqlQuery(self.db)
        q.prepare('INSERT OR REPLACE INTO kv (k, v) VALUES (?, ?)')
        q.addBindValue(str(key))
        q.addBindValue(str(value))
        q.exec()

    def get_kv(self, key: str, default: str = '') -> str:
        """读取键值。"""
        q = QSqlQuery(self.db)
        q.prepare('SELECT v FROM kv WHERE k = ?')
        q.addBindValue(str(key))
        if q.exec() and q.next():
            return str(q.value(0))
        return default

    def close(self) -> None:
        """关闭数据库连接。"""
        try:
            self.db.close()
        except Exception:
            pass
