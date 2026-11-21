"""一键构建并打包双端单文件 exe 到 release/，同时生成 version.json 与构建日志。

用法：
    python build/release.py            # 构建客户端与服务端
    python build/release.py --client   # 只构建客户端
    python build/release.py --server   # 只构建服务端

产物：
    release/PlayWithSnake-Client.exe
    release/PlayWithSnake-Server.exe
    build/logs/build-YYYYmmdd-HHMMSS.log   # 完整构建日志

说明：
    · 两个 exe 均为单文件模式，运行时自带 Python 解释器与 PyQt6，无需额外环境；
    · 静态页面通过 PyInstaller datas 打入 exe，由 server/paths.py 的
      resource_path() 在 sys._MEIPASS 中解析；
    · 构建日志会保留在 build/logs/，失败时可直接查看最后一段输出定位问题。
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

EXE_MIN_BYTES = 5 * 1024 * 1024   # 单文件产物至少 5MB，用于识别被截断的异常产物


class BuildLogger:
    """构建日志器：同时输出到控制台与 build/logs 下的日志文件。"""

    def __init__(self, path: str):
        """打开日志文件。

        Args:
            path: 日志文件绝对路径。
        """
        self.path = path
        self._fp = open(path, 'w', encoding='utf-8', buffering=1)

    def line(self, text: str = '') -> None:
        """写一行日志（控制台 + 文件）。

        Args:
            text: 日志文本。
        """
        print(text)
        self._fp.write(text + '\n')

    def step(self, text: str) -> None:
        """写一条带时间戳的阶段日志。

        Args:
            text: 阶段描述。
        """
        self.line('[%s] %s' % (time.strftime('%H:%M:%S'), text))

    def close(self) -> None:
        """关闭日志文件。"""
        try:
            self._fp.close()
        except Exception:
            pass


def build_env() -> dict:
    """构造子进程环境变量，保证中英文日志按 UTF-8 传输。

    Returns:
        环境变量字典。
    """
    env = os.environ.copy()
    env['PYTHONUTF8'] = '1'
    env['PYTHONIOENCODING'] = 'utf-8'
    return env


def run(cmd: list[str], logger: BuildLogger, env: dict,
        capture: list[str] | None = None) -> int:
    """执行命令并把输出实时写入构建日志。

    Args:
        cmd: 命令列表。
        logger: 构建日志器。
        env: 子进程环境变量。
        capture: 可选列表，用于同时收集输出行以便判断失败原因。

    Returns:
        进程退出码。
    """
    logger.line('')
    logger.line('>>> ' + subprocess.list2cmdline(cmd))
    try:
        p = subprocess.Popen(
            cmd, cwd=ROOT, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding='utf-8', errors='replace', bufsize=1,
        )
    except Exception as e:
        logger.line('[异常] 无法启动命令：%s' % e)
        return 1
    assert p.stdout is not None
    for line in p.stdout:
        text = line.rstrip('\r\n')
        logger.line(text)
        if capture is not None:
            capture.append(text)
    code = p.wait()
    logger.line('[退出码] %d' % code)
    return code


def finalize_exe(path: str, logger: BuildLogger, timeout: float = 120.0) -> bool:
    """在安全软件短暂锁定 exe 后补写 PE 校验和。

    PyInstaller 写完 exe 后会立即回写 PE 校验和；若此时文件被杀毒软件
    扫描锁定，构建会以 PermissionError 失败。文件内容其实已经完整，
    这里等待解锁后调用 PyInstaller 自带工具补写校验和即可。

    Args:
        path: exe 路径。
        logger: 构建日志器。
        timeout: 最长等待秒数。

    Returns:
        成功返回 True。
    """
    try:
        from PyInstaller.utils.win32.winutils import update_exe_pe_checksum
    except Exception as e:
        logger.line('[恢复失败] 无法导入校验和工具：%s' % e)
        return False
    deadline = time.time() + max(5.0, timeout)
    last = ''
    while time.time() < deadline:
        try:
            with open(path, 'rb+'):
                pass
            update_exe_pe_checksum(path)
            return True
        except Exception as e:
            last = str(e)
            time.sleep(1.0)
    logger.line('[恢复失败] 等待 exe 解锁超时：%s' % last)
    return False


def sha256_file(path: str) -> str:
    """计算文件 sha256。

    Args:
        path: 文件路径。

    Returns:
        十六进制摘要；文件不存在时返回空字符串。
    """
    if not os.path.isfile(path):
        return ''
    h = hashlib.sha256()
    with open(path, 'rb') as fp:
        for chunk in iter(lambda: fp.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def build(spec: str, exe_name: str, out_dir: str, logger: BuildLogger, env: dict) -> bool:
    """构建单个端并把 exe 复制到输出目录。

    Args:
        spec: spec 文件名（位于 build/ 下）。
        exe_name: 产物名（不含 .exe）。
        out_dir: 输出目录。
        logger: 构建日志器。
        env: 子进程环境变量。

    Returns:
        成功返回 True。
    """
    dist_dir = os.path.join(ROOT, 'build', 'dist')
    work_dir = os.path.join(ROOT, 'build', 'work')
    logger.step('开始构建 %s' % exe_name)
    lines: list[str] = []
    code = run([
        sys.executable, '-m', 'PyInstaller', os.path.join('build', spec),
        '--noconfirm', '--clean',
        '--distpath', dist_dir,
        '--workpath', work_dir,
    ], logger, env, capture=lines)
    src = os.path.join(dist_dir, exe_name + '.exe')
    if code != 0:
        locked = any('update_exe_pe_checksum' in x or 'Permission denied' in x for x in lines)
        if locked and os.path.isfile(src):
            logger.line('[恢复] 检测到 exe 被安全软件短暂占用，等待解锁后补写 PE 校验和…')
            if finalize_exe(src, logger):
                logger.line('[恢复] PE 校验和已补写，继续输出产物')
                code = 0
    if code != 0:
        logger.line('[失败] PyInstaller 退出码 %d（%s）' % (code, exe_name))
        return False

    if not os.path.isfile(src):
        logger.line('[失败] 未找到产物 %s' % src)
        return False
    size = os.path.getsize(src)
    if size < EXE_MIN_BYTES:
        logger.line('[失败] 产物体积异常（%d 字节），可能缺少依赖或资源' % size)
        return False

    os.makedirs(out_dir, exist_ok=True)
    dst = os.path.join(out_dir, exe_name + '.exe')
    shutil.copy2(src, dst)
    logger.line('[完成] %s（%.1f MB）' % (dst, size / 1024 / 1024))
    return True


def main() -> int:
    """入口。

    Returns:
        退出码（0 成功）。
    """
    p = argparse.ArgumentParser()
    p.add_argument('--client', action='store_true', help='只构建客户端')
    p.add_argument('--server', action='store_true', help='只构建服务端')
    p.add_argument('--out', default='release', help='exe 输出目录（默认 release）')
    args = p.parse_args()
    do_client = args.client or not (args.client or args.server)
    do_server = args.server or not (args.client or args.server)

    log_dir = os.path.join(ROOT, 'build', 'logs')
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, 'build-%s.log' % time.strftime('%Y%m%d-%H%M%S'))
    logger = BuildLogger(log_path)
    env = build_env()
    try:
        logger.step('Play With Snake %s 打包开始' % APP_VERSION)
        logger.line('Python：%s' % sys.version.replace('\n', ' '))
        logger.line('平台：%s' % sys.platform)
        logger.line('输出目录：%s' % os.path.abspath(os.path.join(ROOT, args.out)))
        logger.line('构建日志：%s' % log_path)

        if run([sys.executable, os.path.join('build', 'sync_version.py')], logger, env) != 0:
            logger.line('[失败] 版本资源同步失败')
            return 1
        if run([sys.executable, os.path.join('build', 'make_icon.py')], logger, env) != 0:
            logger.line('[失败] 图标生成失败')
            return 1

        out_dir = os.path.join(ROOT, args.out)
        os.makedirs(out_dir, exist_ok=True)
        ok = True
        if do_client:
            ok = build('client.spec', 'PlayWithSnake-Client', out_dir, logger, env) and ok
        if do_server:
            ok = build('server.spec', 'PlayWithSnake-Server', out_dir, logger, env) and ok
        if not ok:
            logger.line('[失败] 打包未全部成功，请查看上方日志')
            return 1

        client_exe = os.path.join(out_dir, 'PlayWithSnake-Client.exe')
        server_exe = os.path.join(out_dir, 'PlayWithSnake-Server.exe')
        manifest = {
            'version': APP_VERSION,
            'builtAt': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'notes': 'Play With Snake %s' % APP_VERSION,
            'download': '',
            'sha256': sha256_file(client_exe),
            'serverSha256': sha256_file(server_exe),
        }
        with open(os.path.join(out_dir, 'version.json'), 'w', encoding='utf-8') as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        logger.line('已生成 %s' % os.path.join(out_dir, 'version.json'))
        logger.step('打包完成')
        return 0
    finally:
        logger.line('')
        logger.line('构建日志已保存：%s' % log_path)
        logger.close()


if __name__ == '__main__':
    sys.exit(main())
