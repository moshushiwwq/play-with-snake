"""本机回环 HTTP 服务：托管内置页面，并代理局域网服务器发现。

页面从 http://127.0.0.1:<固定端口> 加载，因此：
    · 拥有稳定的 origin，localStorage / IndexedDB 可以跨启动长期持久化；
    · 不受浏览器对本地文件访问网络的限制；
    · 浏览器自身无法发送 UDP 广播，/discover 端点由本地 Python 完成
      局域网扫描后把结果回传给页面。

端口优先使用上次成功占用的端口（由 ClientConfig 持久化），
被占用时顺序向后寻找，保证多次启动尽量落在同一个 origin。
"""
from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from client.discovery import ServerFinder
from server.paths import resource_path

DEFAULT_PAGE_PORT = 17001
PORT_RANGE = 40

# 旧版本曾在 127.0.0.1:17001 注册过 /sw.jsa（缓存名 pws-shell-v4）。
# 该 Service Worker 使用 ignoreSearch 缓存整个页面，导致新客户端一直加载旧页面。
# 这里在同一地址返回自愈脚本：接管后删除旧缓存、注销自身并刷新所有窗口，
# 只清理 CacheStorage，不会触碰 localStorage / IndexedDB 中的游戏数据。
SELF_HEAL_SW = """/* Play With Snake 旧 Service Worker 自愈脚本 */
self.addEventListener('install', function(e){
  e.waitUntil(self.skipWaiting());
});
self.addEventListener('activate', function(e){
  e.waitUntil((async function(){
    try {
      var keys = await caches.keys();
      await Promise.all(keys.map(function(k){
        return k.indexOf('pws-shell-') === 0 ? caches.delete(k) : Promise.resolve(false);
      }));
    } catch (err) {}
    try { await self.clients.claim(); } catch (err) {}
    try { await self.registration.unregister(); } catch (err) {}
    try {
      var list = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
      for (var i = 0; i < list.length; i++){
        try { list[i].navigate(list[i].url); } catch (err) {}
      }
    } catch (err) {}
  })());
});
self.addEventListener('fetch', function(){});
"""

# 旧版 Service Worker 的 fetch 处理器会放过 /api/ 请求，因此用 /api/fix
# 作为入口可以绕过旧缓存加载本页：注销全部 Service Worker、清理 CacheStorage
# 后跳回游戏页。localStorage / IndexedDB 中的设置、战绩与回放不受影响。
FIX_PAGE = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Play With Snake</title>
<style>
html,body{height:100%;margin:0;background:#071a17;color:#8fb3ad;
font-family:"Microsoft YaHei UI","Microsoft YaHei",sans-serif;
display:flex;align-items:center;justify-content:center}
.box{text-align:center}
.dot{width:34px;height:34px;margin:0 auto 16px;border-radius:50%;
border:3px solid rgba(65,227,154,.2);border-top-color:#41e39a;
animation:spin .8s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
</style></head>
<body><div class="box"><div class="dot"></div>正在准备游戏界面…</div>
<script>
(function(){
  var target = '/?client=1';
  var go = function(){ location.replace(target); };
  setTimeout(go, 1800);
  (async function(){
    try {
      if ('serviceWorker' in navigator){
        var regs = await navigator.serviceWorker.getRegistrations();
        await Promise.all(regs.map(function(r){ return r.unregister(); }));
      }
    } catch (e) {}
    try {
      if (window.caches && caches.keys){
        var keys = await caches.keys();
        await Promise.all(keys.map(function(k){ return caches.delete(k); }));
      }
    } catch (e) {}
    go();
  })();
})();
</script></body></html>
"""


class _QuietHttpServer(ThreadingHTTPServer):
    """忽略浏览器主动断开连接产生的 ConnectionReset/BrokenPipe 噪音。"""

    def handle_error(self, request, client_address) -> None:
        """仅在非连接类异常时调用父类默认输出。"""
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)


class PageServer:
    """静态页面服务 + 发现代理（仅监听 127.0.0.1）。"""

    def __init__(self, preferred_port: int = 0):
        """初始化（不启动）。

        Args:
            preferred_port: 优先绑定的端口（0 表示随机）。
        """
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.port = 0
        self.preferred_port = int(preferred_port or 0)
        self._finder = ServerFinder()
        self._lock = threading.Lock()

    @property
    def url(self) -> str:
        """页面访问地址（client=1 用于页面识别本地托管来源）。"""
        return 'http://127.0.0.1:%d/?client=1' % self.port

    @property
    def fix_url(self) -> str:
        """修复入口地址：绕过旧 Service Worker，清理后自动跳回游戏页。"""
        return 'http://127.0.0.1:%d/api/fix?client=1' % self.port

    def discover(self, timeout: float = 1.5, hint: str = '') -> list[dict]:
        """执行一次局域网扫描（线程内调用）。

        Args:
            timeout: 扫描时长（秒）。
            hint: 上次连接的服务器地址（"IP" 或 "IP:端口"），用于 HTTP 兜底探测。

        Returns:
            规整后的服务器列表。
        """
        with self._lock:
            try:
                return self._finder.scan(timeout, hint)
            except Exception:
                return []

    def start(self) -> str:
        """启动服务。

        Returns:
            页面地址；失败时抛 RuntimeError。
        """
        web_root = resource_path('client', 'web')
        api = self

        class Handler(BaseHTTPRequestHandler):
            server_version = 'PlayWithSnakeClient/3.1'
            protocol_version = 'HTTP/1.1'

            def log_message(self, fmt, *args):
                return

            def _send_json(self, obj, code: int = 200) -> None:
                body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
                self.send_response(code)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):  # noqa: N802
                parsed = urlparse(self.path)
                path = parsed.path
                qs = parse_qs(parsed.query)

                if path == '/health':
                    self._send_json({'ok': True})
                    return
                if path == '/discover':
                    hint = (qs.get('host') or [''])[0]
                    self._send_json({'ok': True, 'servers': api.discover(hint=hint)})
                    return
                if path in ('/sw.jsa', '/sw.js'):
                    body = SELF_HEAL_SW.encode('utf-8')
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/javascript; charset=utf-8')
                    self.send_header('Content-Length', str(len(body)))
                    self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate')
                    self.send_header('Service-Worker-Allowed', '/')
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if path == '/api/fix':
                    body = FIX_PAGE.encode('utf-8')
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/html; charset=utf-8')
                    self.send_header('Content-Length', str(len(body)))
                    self.send_header('Cache-Control', 'no-store')
                    self.end_headers()
                    self.wfile.write(body)
                    return

                if path in ('/', '/index.html'):
                    rel = 'index.html'
                elif path == '/version.js':
                    rel = 'version.js'
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
                # 127.0.0.1 端口固定，清理旧版本可能留下的 HTTP 缓存
                self.send_header('Clear-Site-Data', '"cache"')
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
                self._httpd = _QuietHttpServer(('127.0.0.1', port), Handler)
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
