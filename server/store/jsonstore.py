"""JSON 小文件存储工具（原子写入，损坏时安全回落）。"""
from __future__ import annotations

import json
import os
import tempfile


def load_json(path: str, default):
    """读取 JSON 文件。

    Args:
        path: 文件路径。
        default: 文件不存在或解析失败时的返回值。

    Returns:
        解析后的对象或 default。
    """
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path: str, data) -> bool:
    """原子写入 JSON 文件（先写临时文件再替换，避免写入中断损坏）。

    Args:
        path: 目标路径。
        data: 可 JSON 序列化的对象。

    Returns:
        成功返回 True。
    """
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix='.tmp')
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return True
    except Exception:
        return False
