"""协议工具：篡改校验签名与消息字段说明。

签名算法必须与客户端 `snake_v3.html` / `client/web/index.html` 中的 `snakeSig()` 一字不差：
FNV-1a 变体，按 JS `Math.imul` 的 32 位语义计算，输出 8 位小写十六进制。

参与签名的字段（顺序与分隔符不可改）：
    mode # diff # players(|) # scores(,) # levels(,) # lens(,) # duration # mapId
"""
from __future__ import annotations

from typing import Any

from shared.constants import SIGN_SECRET


def _js_string(value: Any, *, is_list: bool, sep: str) -> str:
    """把字段值转成 JS 侧同等文本。

    Args:
        value: 原始值（可能是 None、数字、字符串或列表）。
        is_list: 是否按列表拼接。
        sep: 列表分隔符。

    Returns:
        与 JS 模板拼接结果一致的字符串。
    """
    if is_list:
        if not value:
            return ''
        if isinstance(value, (list, tuple)):
            return sep.join(str(v) for v in value)
        return str(value)
    if value is None:
        return ''
    return str(value)


def _js_char_codes(text: str) -> list[int]:
    """返回 JS `charCodeAt` 等价的 UTF-16 码元序列。

    中文等 BMP 字符与码点一致；非 BMP（如扩展区汉字/表情）在 JS 中会被拆成
    两个代理项码元，这里用 utf-16-le 编码逐 2 字节读取以完全对齐。

    Args:
        text: 待转换字符串。

    Returns:
        UTF-16 码元整数列表。
    """
    data = text.encode('utf-16-le')
    return [int.from_bytes(data[i:i + 2], 'little') for i in range(0, len(data), 2)]


def snake_sig(record: dict) -> str:
    """计算一条成绩记录的校验码。

    Args:
        record: 含 mode/diff/players/scores/levels/lens/duration/mapId 字段的字典。

    Returns:
        8 位小写十六进制校验码。
    """
    parts = [
        _js_string(record.get('mode'), is_list=False, sep=''),
        _js_string(record.get('diff'), is_list=False, sep=''),
        _js_string(record.get('players'), is_list=True, sep='|'),
        _js_string(record.get('scores'), is_list=True, sep=','),
        _js_string(record.get('levels'), is_list=True, sep=','),
        _js_string(record.get('lens'), is_list=True, sep=','),
        _js_string(record.get('duration'), is_list=False, sep=''),
        _js_string(record.get('mapId'), is_list=False, sep=''),
    ]
    text = '#'.join(parts) + '#' + SIGN_SECRET
    h = 2166136261
    for code in _js_char_codes(text):
        h ^= code
        h = (h * 16777619) & 0xFFFFFFFF
    return '%08x' % h


def verify_record(record: dict) -> bool:
    """校验上报记录自带的 sig 是否与重算结果一致。

    Args:
        record: 客户端上报的记录（需含 sig）。

    Returns:
        校验通过返回 True。
    """
    try:
        return snake_sig(record) == str(record.get('sig') or '')
    except Exception:
        return False
