"""客户端更新检查：读取服务器/仓库上的 version.json 并与本地版本比较。"""
from __future__ import annotations

import json
import urllib.request

from shared.version import APP_VERSION


DEFAULT_MANIFEST_URL = (
    'https://raw.githubusercontent.com/play-with-snake/play-with-snake/main/release/version.json'
)


def check_update(url: str = DEFAULT_MANIFEST_URL, current: str = APP_VERSION) -> dict:
    """检查是否有新版本。

    Args:
        url: version.json 地址。
        current: 当前版本。

    Returns:
        {'ok': bool, 'latest': str, 'url': str, 'notes': str, 'hasUpdate': bool}。
    """
    try:
        req = urllib.request.Request(url, headers={'Cache-Control': 'no-cache'})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode('utf-8', 'replace'))
        latest = str(data.get('version') or '')
        return {
            'ok': True,
            'latest': latest,
            'url': str(data.get('download') or ''),
            'notes': str(data.get('notes') or ''),
            'hasUpdate': _is_newer(latest, current),
        }
    except Exception as e:
        return {'ok': False, 'msg': '检查更新失败：%s' % e, 'hasUpdate': False}


def _is_newer(latest: str, current: str) -> bool:
    """简单的语义化版本比较（x.y.z）。

    Args:
        latest: 远端版本。
        current: 本地版本。

    Returns:
        远端更新返回 True。
    """
    def parse(v):
        parts = []
        for x in str(v).strip().lstrip('v').split('.'):
            try:
                parts.append(int(x))
            except Exception:
                parts.append(0)
        while len(parts) < 3:
            parts.append(0)
        return parts[:3]

    return parse(latest) > parse(current)
