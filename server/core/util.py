"""通用工具函数。"""
from __future__ import annotations

from shared.constants import MAX_NAME_LEN


def clean_name(value, fallback: str) -> str:
    """清洗昵称：去掉控制字符与 HTML 特殊字符，并按长度截断。

    Args:
        value: 原始昵称。
        fallback: 清洗后为空时使用的默认昵称。

    Returns:
        清洗后的昵称（最多 12 字符）。
    """
    s = '' if value is None else str(value)
    s = ''.join(ch for ch in s if 0x20 <= ord(ch) != 0x7F and ch not in '<>&"\'`')
    s = s.strip()
    return (s or fallback)[:MAX_NAME_LEN]
