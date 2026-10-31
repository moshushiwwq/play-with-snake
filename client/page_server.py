"""本机回环 HTTP 服务：托管内置页面，规避 file:// 的联网与存储限制。

页面从 http://127.0.0.1:<固定端口> 加载，因此：
    · 拥有稳定的 origin，localStorage / IndexedDB 可以跨启动长期持久化；
    · 不受浏览器对本地文件访问网络的限制。

端口优先使用上次成功占用的端口（由 ClientConfig 持久化），
被占用时顺序向后寻找，保证多次启动尽量落在同一个 origin。
"""
from __future__ import annotations

import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from server.paths import resource_path

DEFAULT_PAGE_PORT = 17001
PORT_RANGE = 40


class PageServer:
    """静态页面服务（仅监听 127.0.0.1）。"""

    def __init__(self, preferred_port: int = 0):
        """初始化（不启动）。

        Args:
            preferred_port: 优先绑定的端口（0 表示随机）。
        """
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.port = 0
        self.preferred_port = int(preferred_port or 0)

    @property
    def url(self) -> str:
        """页面访问地址。"""
        return 'http://127.0.0.1:%d/' % self.port

    def start(self) -> str:
        """启动服务。

        Returns:
            页面地址；失败时抛 RuntimeError。
        """
        web_root = resource_path('client', 'web')

        class Handler(BaseHTTPRequestHandler):
            server_version = 'PlayWithSnakeClient/3.1'
            protocol_version = 'HTTP/1.1'

            def log_message(self, fmt, *args):
                return

            def do_GET(self):  # noqa: N802
                path = self.path.split('?')[0].split('#')[0]
                if path in ('/', '/index.html'):
                    rel = 'index.html'
                elif path == '/version.js':
                    rel = 'version.js'
                elif path == '/health':
                    body = b'ok'
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/plain')
                    self.send_header('Content-Length', str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                else:
                    rel = path.lstrip('/')
                full = os.path.join(web_root, rel)
                if not os.path.isfile(full):
                    body = b'Not Found'
                    self.send_response(404)
                    self.send_header('Content-Type', 'text/plain')
                    self.send_header('Content-Length', str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                with open(full, 'rb') as f:
                    data = f.read()
                ctype = 'text/html; charset=utf-8' if rel.endswith('.html') else (
                    'application/javascript; charset=utf-8' if rel.endswith('.js') else 'application/octet-stream')
                self.send_response(200)
                self.send_header('Content-Type', ctype)
                self.send_header('Content-Length', str(len(data)))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(data)

        candidates: list[int] = []
        base = self.preferred_port or DEFAULT_PAGE_PORT
        for i in range(PORT_RANGE):
            candidates.append(base + i)
        candidates.append(0)
        last_error: Exception | None = None
        for port in candidates:
            try:
                self._httpd = ThreadingHTTPServer(('127.0.0.1', port), Handler)
                break
            except OSError as e:
                last_error = e
                self._httpd = None
        if self._httpd is None:
            raise RuntimeError('本机页面服务启动失败：%s' % last_error)
        self._httpd.daemon_threads = True
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True, name='client-page')
        self._thread.start()
        return self.url

    def stop(self) -> None:
        """停止服务。"""
        if self._httpd is not None:
            try:
                self._httpd.shutdown()
                self._httpd.server_close()
            except Exception:
                pass
            self._httpd = None
            self._thread = None
