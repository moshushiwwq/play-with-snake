"""PyInstaller 运行时钩子：为 windowed 产物提供可用的标准流与崩溃日志。

windowed（console=False）打包时进程没有控制台，标准输出的文件描述符 0/1/2
不存在：PyInstaller 会把 sys.stdout / sys.stderr 置为 None，而 Qt / QtWebEngine
（Chromium）仍在 C 层向 stderr 写入，写入失败会直接影响浏览器初始化，表现为
窗口空白、页面不加载。本钩子在 Python 启动最早期同时修复 C 层 fd 与 sys 层对象，
并把未捕获异常写入程序目录下的 app.log。
"""
from __future__ import annotations

import os
import sys
import traceback


def _log_path() -> str:
    """返回日志文件路径（程序目录优先，不可写时退回临时目录）。

    Returns:
        绝对路径。
    """
    base = os.path.dirname(os.path.abspath(sys.executable)) if getattr(sys, 'frozen', False) else os.getcwd()
    candidate = os.path.join(base, 'app.log')
    try:
        with open(candidate, 'a', encoding='utf-8'):
            pass
        return candidate
    except Exception:
        import tempfile
        return os.path.join(tempfile.gettempdir(), 'play-with-snake-app.log')


_LOG = _log_path()
try:
    _fp = open(_LOG, 'a', encoding='utf-8', buffering=1)
    for _fd in (1, 2):
        try:
            os.dup2(_fp.fileno(), _fd)
        except Exception:
            pass
    if sys.stdout is None:
        sys.stdout = _fp
    if sys.stderr is None:
        sys.stderr = _fp
    _fp.write('\n[boot] exe=%s argv=%s\n' % (sys.executable, sys.argv))
    _fp.flush()
except Exception:
    _fp = None


def _excepthook(exc_type, exc, tb) -> None:
    """把未捕获异常写入日志文件。

    Args:
        exc_type: 异常类型。
        exc: 异常实例。
        tb: 调用栈。
    """
    try:
        with open(_LOG, 'a', encoding='utf-8') as f:
            f.write('\n[traceback]\n')
            f.write(''.join(traceback.format_exception(exc_type, exc, tb)))
            f.flush()
    except Exception:
        pass


sys.excepthook = _excepthook
