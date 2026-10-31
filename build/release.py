"""一键构建并打包双端产物到 release/，同时生成 version.json。

用法：
    python build/release.py            # 构建客户端与服务端
    python build/release.py --client   # 只构建客户端
    python build/release.py --server   # 只构建服务端
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from shared.version import APP_VERSION


def run(cmd: list[str]) -> int:
    """执行命令并回显。

    Args:
        cmd: 命令列表。

    Returns:
        退出码。
    """
    print('>>> ' + ' '.join(cmd))
    p = subprocess.run(cmd, cwd=ROOT)
    return p.returncode


def sha256_dir(path: str) -> str:
    """计算目录内主程序文件的 sha256（用于更新清单）。

    Args:
        path: 目录。

    Returns:
        十六进制摘要。
    """
    h = hashlib.sha256()
    for name in ('PlayWithSnake-Client.exe', 'PlayWithSnake-Server.exe'):
        f = os.path.join(path, name)
        if os.path.isfile(f):
            with open(f, 'rb') as fp:
                for chunk in iter(lambda: fp.read(1024 * 1024), b''):
                    h.update(chunk)
            break
    return h.hexdigest()


def build(spec: str, name: str, release_dir: str) -> bool:
    """构建单个端并复制到 release 目录。

    Args:
        spec: spec 文件名。
        name: 产物目录名。
        release_dir: 输出根目录。

    Returns:
        成功返回 True。
    """
    code = run([sys.executable, '-m', 'PyInstaller', os.path.join('build', spec),
                '--noconfirm', '--clean', '--distpath', os.path.join('build', 'dist'),
                '--workpath', os.path.join('build', 'work')])
    if code != 0:
        print('[失败] PyInstaller 退出码 %d' % code)
        return False
    src = os.path.join(ROOT, 'build', 'dist', name)
    dst = os.path.join(release_dir, name)
    if not os.path.isdir(src):
        print('[失败] 未找到产物目录 ' + src)
        return False
    if os.path.isdir(dst):
        shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(src, dst)
    print('已输出：' + dst)
    return True


def main() -> int:
    """入口。

    Returns:
        退出码。
    """
    p = argparse.ArgumentParser()
    p.add_argument('--client', action='store_true')
    p.add_argument('--server', action='store_true')
    args = p.parse_args()
    do_client = args.client or not (args.client or args.server)
    do_server = args.server or not (args.client or args.server)

    if run([sys.executable, os.path.join('build', 'sync_version.py')]) != 0:
        return 1
    if run([sys.executable, os.path.join('build', 'make_icon.py')]) != 0:
        return 1

    release_dir = os.path.join(ROOT, 'release')
    os.makedirs(release_dir, exist_ok=True)
    ok = True
    if do_client:
        ok = build('client.spec', 'PlayWithSnake-Client', release_dir) and ok
    if do_server:
        ok = build('server.spec', 'PlayWithSnake-Server', release_dir) and ok
    if not ok:
        return 1

    client_dir = os.path.join(release_dir, 'PlayWithSnake-Client')
    manifest = {
        'version': APP_VERSION,
        'builtAt': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'notes': 'Play With Snake %s' % APP_VERSION,
        'download': '',
        'sha256': sha256_dir(client_dir) if os.path.isdir(client_dir) else '',
    }
    with open(os.path.join(release_dir, 'version.json'), 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print('已生成 %s' % os.path.join(release_dir, 'version.json'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
