"""客户端入口：本机页面服务 + QWebEngineView + Python 持网 + 托盘 + 本地存储。

运行方式：
    python client/main.py                 # 正常打开窗口
    python client/main.py --tray          # 启动即隐藏到托盘
    python client/main.py --shot out.png  # 截图后退出（自检用）
"""
from __future__ import annotations

import argparse
import os
import sys

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QApplication

# QWebEngine 必须在创建 QApplication 之前设置共享 OpenGL 上下文
QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from client.bridge import SnakeBridge
from client.config import ClientConfig
from client.net_client import NetClient
from client.page_server import PageServer
from client.storage import ClientStorage
from client.tray import ClientTray
from client.window import ClientWindow
from shared.qt_theme import QSS
from shared.version import APP_VERSION


def parse_args(argv: list[str]) -> argparse.Namespace:
    """解析命令行参数。

    Args:
        argv: 命令行参数。

    Returns:
        argparse 命名空间。
    """
    p = argparse.ArgumentParser(description='Play With Snake 客户端')
    p.add_argument('--tray', action='store_true', help='启动后隐藏到系统托盘')
    p.add_argument('--shot', default='', help='加载完成后截图到指定路径并退出')
    p.add_argument('--url', default='', help='直接加载指定地址（调试用）')
    p.add_argument('--autotest', default='', help='加载后执行内置联机自检（参数为服务器地址）')
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
        self.storage = ClientStorage()
        self.page_server = PageServer()
        self.page_url = args.url or self.page_server.start()
        if args.autotest:
            # 自检需要页面暴露内部接口（正常运行时不会加这个参数）
            self.page_url = self.page_url + ('&' if '?' in self.page_url else '?') + 'selftest=1'
        self.net = NetClient()
        self.net.auto_reconnect = bool(self.config.auto_reconnect)
        self.bridge = SnakeBridge(self.net, self.storage, self.config)
        self.window: ClientWindow | None = None
        self.tray: ClientTray | None = None

    def build_ui(self) -> None:
        """创建窗口与托盘。"""
        self.window = ClientWindow(self)
        from PyQt6.QtWidgets import QSystemTrayIcon
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = ClientTray(self.window, self.window.show_and_raise,
                                   self.window.on_check_update, self.window.quit_app)
            self.net.stateChanged.connect(self._on_net_state)
        if self.args.tray or self.config.start_hidden:
            self.window.hide()
        else:
            self.window.show()

    def _on_net_state(self, state: str, host: str) -> None:
        """把连接状态同步到托盘。"""
        if self.tray is None:
            return
        if state == 'connected':
            self.tray.set_state('已连接 ' + host, True)
        elif state == 'connecting':
            self.tray.set_state('正在连接 ' + host, False)
        else:
            self.tray.set_state('未连接服务器', False)


def main() -> int:
    """程序入口。

    Returns:
        进程退出码。
    """
    args = parse_args(sys.argv[1:])
    app = QApplication(sys.argv[:1])
    app.setApplicationName('Play With Snake')
    app.setStyleSheet(QSS)

    ctx = ClientApp(args)
    ctx.build_ui()

    if args.shot:
        def shot():
            try:
                ctx.window.show_and_raise()
                QTimer.singleShot(2200, lambda: (
                    ctx.window.grab().save(args.shot),
                    ctx.window.quit_app(),
                    print('shotsaved=' + args.shot),
                ))
            except Exception as e:
                print('shot failed=' + str(e))
                ctx.window.quit_app()
        QTimer.singleShot(500, shot)

    if args.autotest:
        _run_autotest(ctx, args.autotest)

    app.aboutToQuit.connect(lambda: (
        ctx.page_server.stop(),
        ctx.net.close(),
        ctx.storage.close(),
    ))
    return app.exec()


def _run_autotest(ctx: 'ClientApp', server_host: str) -> None:
    """执行一次内置联机自检（加载页面 → 通过桥接连接服务器 → 打印结果后退出）。

    Args:
        ctx: 客户端上下文。
        server_host: 服务器地址（如 127.0.0.1:18081）。
    """
    import json

    script = """
window.__AUTOTEST = { results: [], done: false };
(async function(){
  function log(k, v){ window.__AUTOTEST.results.push([k, v]); }
  try {
    var B = (window.__T && window.__T.Backend) || window.Backend;
    if (!B){ log('error', 'Backend 未暴露'); window.__AUTOTEST.done = true; return; }
    await B.init();
    log('mode', B.mode);
    B.onState = function(st, host){ log('state', st + ' ' + host); };
    B.onMessage = function(t){
      try {
        var m = JSON.parse(t);
        log('msg', m.t);
        if (m.t === 'hello' && m.httpPort) B.setHttpPort(m.httpPort);
      } catch(e){ log('msg', 'parse-fail'); }
    };
    B.connect('%(host)s', function(r){ log('connectret', r && r.ok); });
    setTimeout(function(){
      B.httpGet('/api/online-board', '%(host)s', function(j){
        log('board', j && j.ok ? (j.rows || []).length : 'fail');
      });
      B.httpGet('/api/maps', '%(host)s', function(j){
        log('maps', j && j.ok ? (j.maps || []).length : 'fail');
      });
      setTimeout(function(){
        B.send({ t: 'create', name: '客户端甲', maxPlayers: 2, map: 'classic', diff: 'normal', isPublic: true });
        setTimeout(function(){ window.__AUTOTEST.done = true; }, 1500);
      }, 1200);
    }, 1500);
  } catch (e){ log('error', String(e)); window.__AUTOTEST.done = true; }
})();
""" % {'host': server_host}

    state = {'tries': 0}

    def poll():
        state['tries'] += 1
        ctx.window.view.page().runJavaScript('JSON.stringify(window.__AUTOTEST || {})', 0, report)
        if state['tries'] > 12:
            ctx.window.quit_app()

    def report(result):
        try:
            data = json.loads(result) if result else {}
        except Exception:
            data = {}
        if data.get('results'):
            print('AUTOTEST ' + json.dumps(data, ensure_ascii=False))
            if data.get('done'):
                ctx.window.quit_app()
                return
        if state['tries'] > 12:
            ctx.window.quit_app()

    def run():
        ctx.window.show_and_raise()
        ctx.window.view.page().runJavaScript(script)

    QTimer.singleShot(2200, run)
    poll_timer = QTimer(ctx.window)
    poll_timer.setInterval(900)
    poll_timer.timeout.connect(poll)
    poll_timer.start()
    ctx._poll_timer = poll_timer      # 保持引用


if __name__ == '__main__':
    sys.exit(main())