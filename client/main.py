"""客户端入口：搜索局域网服务器，然后用系统浏览器直接打开服务器页面。

运行方式：
    python client/main.py                  # 自动搜索并打开唯一/上次的服务器
    python client/main.py --url <地址>     # 不启动窗口，直接把指定地址交给浏览器（调试用）
    python client/main.py --no-auto        # 只搜索不自动打开，由用户手动选择

全程普通用户权限：不申请管理员、不改注册表与防火墙、不写系统目录；
界面上也不使用表情符号或装饰性字符。
"""
from __future__ import annotations

import argparse
import os
import sys

from PyQt6.QtCore import QTimer, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import QApplication

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from client.config import ClientConfig
from client.picker import ServerPicker
from shared.qt_theme import QSS
from shared.version import APP_VERSION

CLIENT_SINGLE_KEY = 'play-with-snake-client'


def parse_args(argv: list[str]) -> argparse.Namespace:
    """解析命令行参数。

    Args:
        argv: 命令行参数列表。

    Returns:
        argparse 命名空间。
    """
    p = argparse.ArgumentParser(description='Play With Snake 客户端')
    p.add_argument('--url', default='', help='直接把指定地址交给浏览器打开（调试用）')
    p.add_argument('--no-auto', action='store_true', help='只搜索，不自动打开浏览器')
    return p.parse_args(argv)


class ClientApp:
    """客户端上下文（窗口、配置与浏览器拉起）。"""

    def __init__(self, args: argparse.Namespace):
        """装配上下文。

        Args:
            args: 命令行参数。
        """
        self.args = args
        self.config = ClientConfig()
        self.window: ServerPicker | None = None
        self.auto_open = not args.no_auto and bool(self.config.get('ui/auto_open', True))

    def build_ui(self) -> None:
        """创建主窗口。"""
        self.window = ServerPicker(self)
        self.window.show()

    def open_url(self, url: str) -> bool:
        """用系统默认浏览器打开地址。

        Args:
            url: 完整地址。

        Returns:
            是否成功提交给系统。
        """
        try:
            return bool(QDesktopServices.openUrl(QUrl(url)))
        except Exception:
            return False

    def scan(self) -> None:
        """触发一次搜索（窗口创建后调用）。"""
        if self.window is None:
            return
        self.window.scan(auto=self.auto_open)

    def quit(self) -> None:
        """退出客户端。"""
        QApplication.quit()


def _activate_existing() -> bool:
    """唤起已在运行的客户端窗口。

    只有收到对方回写的 OK 才认为旧实例存活：异常退出会留下同名本地管道，
    此时握手失败应按「陈旧管道」处理，清理后正常启动，避免双击毫无反应。

    Returns:
        True 表示已有实例被唤起，本进程应直接退出。
    """
    probe = QLocalSocket()
    probe.connectToServer(CLIENT_SINGLE_KEY)
    if not probe.waitForConnected(400):
        return False
    # 只以 write() 的返回值为准：waitForBytesWritten 在小报文上可能返回 False，
    # 但数据其实已经发出，据此判断会把存活的实例误当成陈旧管道。
    if probe.write(b'SHOW') < 0:
        probe.abort()
        return False
    probe.flush()
    if not probe.waitForReadyRead(800):
        probe.disconnectFromServer()
        return False
    ack = bytes(probe.readAll())
    probe.disconnectFromServer()
    return b'OK' in ack


def main() -> int:
    """程序入口。

    Returns:
        进程退出码。
    """
    args = parse_args(sys.argv[1:])
    app = QApplication(sys.argv[:1])
    app.setApplicationName('Play With Snake')
    app.setStyleSheet(QSS)
    app.setQuitOnLastWindowClosed(True)

    if args.url:
        # 调试直开：不占单实例锁，也不显示窗口
        ctx = ClientApp(args)
        ctx.open_url(args.url)
        return 0

    if _activate_existing():
        return 0
    QLocalServer.removeServer(CLIENT_SINGLE_KEY)
    holder = QLocalServer()
    holder.listen(CLIENT_SINGLE_KEY)

    ctx = ClientApp(args)
    ctx.build_ui()

    def _on_new_connection() -> None:
        """再次启动时把窗口带到前台并重新搜索。"""
        while holder.hasPendingConnections():
            conn = holder.nextPendingConnection()
            if conn is not None:
                conn.readAll()
                conn.write(b'OK')
                conn.flush()
                conn.waitForBytesWritten(200)
                conn.disconnectFromServer()
                conn.deleteLater()
        if ctx.window is not None:
            ctx.window.show_and_raise()
            ctx.scan()
    holder.newConnection.connect(_on_new_connection)

    # 窗口先画出来，再开始搜索，避免首帧被扫描阻塞
    QTimer.singleShot(120, ctx.scan)
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
