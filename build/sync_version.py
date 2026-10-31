"""把 shared/version.py 的版本信息写成 client/web/version.js。

页面启动时先加载 version.js，再加载主脚本，从而保证「关于」面板的版本号
与服务端 /health、更新清单完全一致。
"""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from shared.version import APP_VERSION, VERSION_LOG


def main() -> int:
    """生成 version.js。

    Returns:
        进程退出码。
    """
    out = os.path.join(ROOT, 'client', 'web', 'version.js')
    payload = (
        '/* 由 build/sync_version.py 自动生成，请勿手工修改 */\n'
        'window.APP_VERSION = %s;\n'
        'window.VERSION_LOG = %s;\n'
    ) % (json.dumps(APP_VERSION, ensure_ascii=False),
         json.dumps(VERSION_LOG, ensure_ascii=False, indent=2))
    with open(out, 'w', encoding='utf-8', newline='\n') as f:
        f.write(payload)
    print('已生成 %s（版本 %s，%d 条更新日志）' % (out, APP_VERSION, len(VERSION_LOG)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
