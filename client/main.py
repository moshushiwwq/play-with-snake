"""客户端入口：启动动画 + 系统托盘 + 日志窗口，游戏界面在外部浏览器中打开。

运行方式：
    python client/main.py                 # 播放开场动画后，用默认浏览器打开游戏页面
    python client/main.py --tray          # 启动即隐藏到托盘（不弹日志窗口）
    python client/main.py --url <地址>    # 直接在浏览器打开指定地址（调试用）

架构说明：
    · 不再内嵌 Qt WebEngine，页面由本机回环 PageServer 托管；
    · 浏览器页面以「直连模式」与服务器 WebSocket / HTTP 通信；
    · Python 外壳只负责：开场动画、托盘常驻、运行日志、拉起浏览器。
"""
from __future__ import annotations

import argparse
import os
import sys
import time

from PyQt6.QtCore import QTimer, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import QApplication

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from client.config import ClientConfig
from client.page_server import PageServer
from client.splash import SplashScreen
from client.storage import ClientStorage
from client.tray import ClientTray
from client.window import ClientWindow
from shared.qt_theme import QSS
from shared.version import APP_VERSION

SPLASH_DURATION_MS = 2100


def parse_args(argv: list[str]) -> argparse.Namespace:
    """解析命令行参数。

    Args:
        argv: 命令行参数。

    Returns:
        argparse 命名空间。
    """
    p = argparse.ArgumentParser(description='Play With Snake 客户端')
    p.add_argument('--tray', action='store_true', help='启动后隐藏到系统托盘')
    p.add_argument('--url', default='', help='直接在浏览器打开指定地址（调试用）')
    return p.parse_args(argv)


class ClientApp:
    """客户端上下文。"""

    def __init__(self, args: argparse.Namespace):
        """装配所有组件。

        Args:
            args: 命令行参数。
        """
        self.args = args
        self.config = ClientConfig()
        self._mem_log: list[dict] = []
        try:
            self.storage = ClientStorage()
        except Exception as e:
            self.storage = None
            self._mem_log: list[dict] = []
            self.log('本地存储初始化失败，日志仅保留在内存：%s' % e, 'warn')
        try:
            preferred = int(self.config.get('ui/page_port', 0) or 0)
        except Exception:
            preferred = 0
        self.page_server = PageServer(preferred)
        if args.url:
            self.page_url = args.url
            self.open_url = args.url
        else:
            self.page_url = self.page_server.start()
            # 先经过修复入口：旧版 Service Worker 可能缓存了旧页面，
            # /api/fix 会注销旧 SW 并清理缓存后自动跳回游戏页。
            self.open_url = self.page_server.fix_url
            self.config.set('ui/page_port', int(self.page_server.port))
        self.window: ClientWindow | None = None
        self.tray: ClientTray | None = None
        self.splash: SplashScreen | None = None

    # ---------------------------------------------------------------- 日志
    def log(self, text: str, level: str = 'info') -> None:
        """写一条运行日志到日志窗口与本地存储。

        Args:
            text: 日志文本。
            level: info/ok/warn/error。
        """
        if self.window is not None:
            self.window.append_log(text, level)
        if self.storage is not None:
            try:
                self.storage.save_log(level, text)
            except Exception:
                pass
        else:
            self._mem_log.append({'ts': int(time.time() * 1000), 'level': level, 'text': text})

    # ---------------------------------------------------------------- 界面
    def build_ui(self) -> None:
        """创建日志窗口与托盘。"""
        self.window = ClientWindow(self)
        from PyQt6.QtWidgets import QSystemTrayIcon
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = ClientTray(self.window, self.window.show_and_raise,
                                   self.window.on_check_update, self.window.quit_app)
        if self.args.tray or self.config.start_hidden:
            self.window.hide()
        else:
            self.window.hide()   # 游戏界面在浏览器中，日志窗口默认不抢占前台

    def open_game_page(self) -> None:
        """用系统默认浏览器打开游戏页面。"""
        url = QUrl(self.open_url)
        QDesktopServices.openUrl(url)
        if self.open_url != self.page_url:
            self.log('已打开游戏页面（自动清理旧页面缓存）：%s' % self.page_url, 'ok')
        else:
            self.log('已在浏览器打开游戏页面：%s' % self.page_url, 'ok')

    def show_splash(self) -> None:
        """显示圆角动态启动动画，结束后自动打开游戏页面。"""
        self.splash = SplashScreen(APP_VERSION, SPLASH_DURATION_MS)
        self.splash.finished.connect(self._on_splash_finished)
        self.splash.start()

    def _on_splash_finished(self) -> None:
        """启动动画结束：关闭窗口并拉起浏览器。"""
        if self.splash is not None:
            self.splash.close()
            self.splash = None
        self.open_game_page()


CLIENT_SINGLE_KEY = 'play-with-snake-client'


def _activate_existing() -> bool:
    """若已有客户端实例在运行，则通知它把日志窗口唤到前台。

    只有收到对方回写的 `OK` 才会认为旧实例确实存活：进程异常退出或处于
    僵尸状态时会留下同名本地管道，此时直接退出会表现为「双击后程序毫无反应」。
    握手失败即视为陈旧管道，由调用方清理后正常启动。

    Returns:
        是否成功唤起已有实例（True 表示当前进程应当直接退出）。
    """
    probe = QLocalSocket()
    probe.connectToServer(CLIENT_SINGLE_KEY)
    if not probe.waitForConnected(400):
        return False
    probe.write(b'SHOW')
    probe.flush()
    if not probe.waitForBytesWritten(400):
        probe.abort()
        return False
    if not probe.waitForReadyRead(600):
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
    app.setQuitOnLastWindowClosed(False)   # 无主窗口，关闭日志窗口不应退出

    holder: QLocalServer | None = None
    if not args.url:
        if _activate_existing():
            return 0
        QLocalServer.removeServer(CLIENT_SINGLE_KEY)
        holder = QLocalServer()
        holder.listen(CLIENT_SINGLE_KEY)

    ctx = ClientApp(args)
    ctx.build_ui()
    ctx.log('Play With Snake 客户端 v%s 启动' % APP_VERSION, 'ok')
    ctx.log('数据目录：%s' % ctx.config.path, 'info')

    if holder is not None:
        def _on_new_connection():
            """再次启动时把日志窗口唤到前台。"""
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
        holder.newConnection.connect(_on_new_connection)

    # 开场动画（可在配置中关闭），结束后拉起浏览器
    if ctx.config.splash and not args.url:
        ctx.show_splash()
    else:
        QTimer.singleShot(200, ctx.open_game_page)

    app.aboutToQuit.connect(lambda: (
        ctx.splash.stop() if ctx.splash is not None else None,
        ctx.page_server.stop(),
        ctx.storage.close() if ctx.storage is not None else None,
    ))
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
