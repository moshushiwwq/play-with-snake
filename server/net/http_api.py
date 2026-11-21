"""HTTP 接口服务：页面分发、联机 REST 接口与「访问密码 + 排行榜」面板。

用 Python 标准库 ThreadingHTTPServer 实现（绑定 0.0.0.0，局域网可直接访问），
与 Qt 主线程共享 GameService，所有读写都在 service.lock 内完成。
"""
from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from server.paths import resource_path
from server.store.auth import COOKIE_NAME, DEFAULT_USER
from server.sys import autostart


def _read_cookie(header: str | None, name: str) -> str:
    """从 Cookie 头中读取指定字段。

    Args:
        header: 原始 Cookie 头。
        name: 字段名。

    Returns:
        字段值（不存在返回空字符串）。
    """
    if not header:
        return ''
    for part in header.split(';'):
        k, _, v = part.strip().partition('=')
        if k == name:
            return v
    return ''


class HttpApi:
    """HTTP 服务（页面 + REST + 面板）。"""

    def __init__(self, service, config, auth, version: str, logger=None, logbus=None):
        """初始化。

        Args:
            service: GameService。
            config: 配置对象（提供 port）。
            auth: PanelAuth。
            version: 版本号。
            logger: 日志回调 fn(text, level)。
            logbus: LogBus（用于管理面板读取完整日志，可为空）。
        """
        self.service = service
        self.config = config
        self.auth = auth
        self.version = version
        self.logger = logger
        self.logbus = logbus
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    # ---------------------------------------------------------------- 生命周期
    def start(self) -> tuple[bool, str]:
        """启动 HTTP 服务。

        Returns:
            (是否成功, 提示信息)。
        """
        if self._httpd is not None:
            return True, 'HTTP 服务已在运行'
        api = self

        class Handler(BaseHTTPRequestHandler):
            server_version = 'PlayWithSnake/3.1'
            protocol_version = 'HTTP/1.1'

            def log_message(self, fmt, *args):  # noqa: D401  （覆盖默认 stderr 输出）
                return

            # -------------------------------------------------- 基础
            def _cors(self) -> None:
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
                self.send_header('Access-Control-Allow-Headers', 'Content-Type')

            def _json(self, obj, code: int = 200, extra: dict | None = None) -> None:
                body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
                self.send_response(code)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'no-store')
                self._cors()
                for k, v in (extra or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(body)

            def _file(self, path: str, ctype: str) -> None:
                try:
                    with open(path, 'rb') as f:
                        data = f.read()
                except Exception:
                    self._json({'ok': False, 'msg': '页面文件缺失：' + os.path.basename(path)}, 404)
                    return
                self.send_response(200)
                self.send_header('Content-Type', ctype)
                self.send_header('Content-Length', str(len(data)))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(data)

            def _body(self) -> dict:
                try:
                    n = int(self.headers.get('Content-Length') or 0)
                except Exception:
                    n = 0
                raw = self.rfile.read(n) if n else b''
                try:
                    obj = json.loads(raw.decode('utf-8')) if raw else {}
                except Exception:
                    obj = {}
                return obj if isinstance(obj, dict) else {}

            @property
            def ip(self) -> str:
                return self.client_address[0] if self.client_address else ''

            def _token(self) -> str:
                return _read_cookie(self.headers.get('Cookie'), COOKIE_NAME)

            # -------------------------------------------------- OPTIONS
            def do_OPTIONS(self):  # noqa: N802
                self.send_response(204)
                self._cors()
                self.send_header('Content-Length', '0')
                self.end_headers()

            # -------------------------------------------------- GET
            def do_GET(self):  # noqa: N802
                path = urlparse(self.path).path
                qs = parse_qs(urlparse(self.path).query)
                svc = api.service

                if path in ('/', '/index.html'):
                    self._file(resource_path('client', 'web', 'index.html'), 'text/html; charset=utf-8')
                    return
                if path == '/version.js':
                    self._file(resource_path('client', 'web', 'version.js'), 'application/javascript; charset=utf-8')
                    return
                if path == '/panel':
                    self._file(resource_path('server', 'web', 'panel.html'), 'text/html; charset=utf-8')
                    return
                if path == '/health':
                    self._json({'ok': True, 'v': api.version, 'wsPort': api.config.ws_port})
                    return
                if path == '/api/discover':
                    self._json(svc.discover_info(api.version, api.config.port, api.config.ws_port))
                    return
                if path == '/api/online-board':
                    with svc.lock:
                        rows = svc.online_board.top(30)
                    self._json({'ok': True, 'rows': rows})
                    return
                if path == '/api/maps':
                    with svc.lock:
                        maps = svc.map_list()
                    self._json({'ok': True, 'maps': maps})
                    return
                if path == '/api/map':
                    mid = (qs.get('id') or [''])[0]
                    with svc.lock:
                        m = svc.custom_maps.get(mid)
                    self._json({'ok': bool(m), 'map': m} if m else {'ok': False, 'msg': '地图不存在'})
                    return
                if path == '/api/auth/status':
                    self._json({'ok': True, 'enabled': api.auth.enabled(),
                                'authed': api.auth.authed(self._token()),
                                'user': api.auth.username()})
                    return
                if path == '/api/server/settings':
                    if not api.auth.authed(self._token()):
                        self._json({'ok': False, 'msg': '需要登录'}, 401)
                        return
                    self._json({'ok': True, 'settings': api.server_settings()})
                    return
                if path == '/api/leaderboard':
                    if not api.auth.authed(self._token()):
                        self._json({'ok': False, 'msg': '需要登录'}, 401)
                        return
                    with svc.lock:
                        rows = svc.leaderboard.top(30)
                    self._json({'ok': True, 'rows': rows})
                    return
                if path == '/api/logs':
                    if not api.auth.authed(self._token()):
                        self._json({'ok': False, 'msg': '需要登录'}, 401)
                        return
                    bus = api.logbus
                    if bus is None:
                        self._json({'ok': False, 'msg': '日志不可用'}, 200)
                        return
                    try:
                        limit = int((qs.get('limit') or ['500'])[0])
                    except Exception:
                        limit = 500
                    level = (qs.get('level') or ['all'])[0]
                    items = bus.entries(limit, level)
                    source = 'memory'
                    if not items and str(level).lower() in ('', 'all'):
                        items = bus.read_file(limit)
                        source = 'file'
                    self._json({'ok': True, 'entries': items, 'source': source, 'stats': bus.stats()})
                    return
                if path == '/api/logs/download':
                    if not api.auth.authed(self._token()):
                        self._json({'ok': False, 'msg': '需要登录'}, 401)
                        return
                    bus = api.logbus
                    if bus is None or not os.path.exists(bus.path):
                        self._json({'ok': False, 'msg': '还没有日志文件'}, 404)
                        return
                    try:
                        with open(bus.path, 'rb') as f:
                            data = f.read()
                    except Exception as e:
                        self._json({'ok': False, 'msg': '日志读取失败：%s' % e}, 500)
                        return
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/plain; charset=utf-8')
                    self.send_header('Content-Disposition', 'attachment; filename="server.log"')
                    self.send_header('Content-Length', str(len(data)))
                    self.send_header('Cache-Control', 'no-store')
                    self._cors()
                    self.end_headers()
                    self.wfile.write(data)
                    return
                self._json({'ok': False, 'msg': 'Not Found'}, 404)

            # -------------------------------------------------- POST
            def do_POST(self):  # noqa: N802
                path = urlparse(self.path).path
                svc = api.service
                body = self._body()

                if path == '/api/rank':
                    ip = self.ip
                    with svc.lock:
                        r = svc.online_board.submit(body, ip)
                        if r.get('ok'):
                            svc.leaderboard.register_player(body.get('name') or
                                                            ((body.get('players') or [''])[0]), ip)
                    if r.get('ok'):
                        with svc.lock:
                            svc.broadcast_all({'t': 'ob', 'top': svc.online_board.top(30)})
                        (api.logger or svc.log)('联机成绩入榜（HTTP）：%s %s 分' % (
                            body.get('name') or '-', body.get('score') or 0))
                        self._json(r, 200)
                    else:
                        (api.logger or svc.log)('过滤异常数据（签名不符）：%s 来源 %s' % (
                            body.get('name') or '-', ip), 'warn')
                        self._json(r, 400)
                    return

                if path == '/api/solo-score':
                    name = str(body.get('name') or '').strip()
                    try:
                        score = int(body.get('score') or 0)
                    except Exception:
                        score = 0
                    try:
                        length = int(body.get('length') or 0)
                    except Exception:
                        length = 0
                    with svc.lock:
                        svc.leaderboard.solo(name, score, length, self.ip)
                    svc.broadcast_all({'t': 'lb', 'top': svc.leaderboard.top(30)})
                    self._json({'ok': True, 'msg': '单机成绩已记录'})
                    return

                if path == '/api/map':
                    with svc.lock:
                        ok, msg = svc.custom_maps.upsert(body)
                    if ok:
                        (api.logger or svc.log)('自制地图已上传：%s（%s）' % (
                            body.get('name') or '-', body.get('id') or '-'))
                    self._json({'ok': ok, 'msg': msg}, 200 if ok else 400)
                    return

                if path == '/api/auth/login':
                    ip = self.ip
                    left = api.auth.locked_for(ip)
                    if left > 0:
                        self._json({'ok': False, 'msg': '尝试过于频繁，请 %d 秒后再试' % left}, 429)
                        return
                    username = str(body.get('username') or '').strip()
                    password = str(body.get('password') or '')
                    if not api.auth.verify(username, password):
                        api.auth.fail(ip)
                        lk = api.auth.locked_for(ip)
                        (api.logger or svc.log)('控制台登录失败：来自 %s%s' % (
                            ip, '，已锁定 %d 秒' % lk if lk else ''), 'warn')
                        self._json({'ok': False, 'msg': ('账号或密码错误，已锁定 %d 秒' % lk) if lk else '账号或密码错误'}, 401)
                        return
                    api.auth.reset_fail(ip)
                    token = api.auth.issue()
                    self._json({'ok': True, 'msg': '登录成功', 'user': api.auth.username()},
                               extra={'Set-Cookie': api.auth.cookie_header(token)})
                    return

                if path == '/api/auth/set':
                    ip = self.ip
                    if api.auth.enabled() and not api.auth.authed(self._token()):
                        left = api.auth.locked_for(ip)
                        if left > 0:
                            self._json({'ok': False, 'msg': '尝试过于频繁，请 %d 秒后再试' % left}, 429)
                            return
                        if not api.auth.verify(api.auth.username(), body.get('oldPassword') or ''):
                            api.auth.fail(ip)
                            lk = api.auth.locked_for(ip)
                            self._json({'ok': False, 'msg': ('旧密码错误，已锁定 %d 秒' % lk) if lk else '旧密码错误'}, 403)
                            return
                        api.auth.reset_fail(ip)
                    new_user = str(body.get('username') or api.auth.username() or DEFAULT_USER).strip()
                    new_pwd = str(body.get('newPassword') or '')
                    api.auth.set_account(new_user, new_pwd)
                    api.config.data['panelAuth'] = api.auth.params()
                    api.config.save()
                    (api.logger or svc.log)('管理员账号已%s' % (
                        '设置/修改' if new_pwd else '清除'), 'warn')
                    self._json({'ok': True, 'msg': '账号已保存' if new_pwd else '账号保护已清除',
                                'user': api.auth.username()})
                    return

                if path == '/api/server/settings':
                    if not api.auth.authed(self._token()):
                        self._json({'ok': False, 'msg': '需要登录'}, 401)
                        return
                    msg = api.apply_settings(body)
                    self._json({'ok': True, 'msg': msg, 'settings': api.server_settings()})
                    return

                if path == '/api/auth/logout':
                    self._json({'ok': True}, 200, {'Set-Cookie': COOKIE_NAME + '=; Path=/; Max-Age=0; HttpOnly'})
                    return

                if path == '/api/logs/clear':
                    if not api.auth.authed(self._token()):
                        self._json({'ok': False, 'msg': '需要登录'}, 401)
                        return
                    bus = api.logbus
                    if bus is None:
                        self._json({'ok': False, 'msg': '日志不可用'}, 200)
                        return
                    (api.logger or svc.log)('日志文件已由管理面板清空', 'warn')
                    bus.clear_file()
                    self._json({'ok': True, 'msg': '日志文件已清空（本机历史一并删除）',
                                'stats': bus.stats()})
                    return

                self._json({'ok': False, 'msg': 'Not Found'}, 404)

        try:
            self._httpd = ThreadingHTTPServer(('0.0.0.0', self.config.port), Handler)
            self._httpd.daemon_threads = True
            self._httpd.allow_reuse_address = True
        except Exception as e:
            self._httpd = None
            return False, 'HTTP 端口 %d 启动失败：%s' % (self.config.port, e)

        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True,
                                        name='snake-http')
        self._thread.start()
        return True, 'HTTP 服务已启动：%d' % self.config.port

    # ---------------------------------------------------------------- 设置
    def server_settings(self) -> dict:
        """汇总面板需要展示的服务端设置（含当前自启动形态与权限）。"""
        cfg = self.config.data if isinstance(self.config.data, dict) else {}
        try:
            mode = autostart.query()
        except Exception:
            mode = str(cfg.get('autostart') or 'none')
        try:
            admin = autostart.is_admin()
        except Exception:
            admin = False
        return {
            'port': self.config.port,
            'wsPort': self.config.ws_port,
            'autostart': str(cfg.get('autostart') or 'none'),
            'autostartMode': mode,
            'discovery': bool(cfg.get('discovery', True)),
            'splashServer': bool(cfg.get('splashServer', True)),
            'splashClient': bool(cfg.get('splashClient', True)),
            'admin': admin,
            'version': self.version,
        }

    def apply_settings(self, body: dict) -> str:
        """应用面板提交的设置项，返回结果说明文本。

        Args:
            body: 请求体，可含 autostart / discovery / splashServer / splashClient。
        """
        cfg = self.config.data if isinstance(self.config.data, dict) else {}
        msgs: list[str] = []

        if 'discovery' in body:
            cfg['discovery'] = bool(body.get('discovery'))
            msgs.append('内网发现已' + ('开启' if cfg['discovery'] else '关闭'))
        if 'splashServer' in body:
            cfg['splashServer'] = bool(body.get('splashServer'))
            msgs.append('服务端启动动画已' + ('开启' if cfg['splashServer'] else '关闭'))
        if 'splashClient' in body:
            cfg['splashClient'] = bool(body.get('splashClient'))
            msgs.append('客户端启动动画已' + ('开启' if cfg['splashClient'] else '关闭'))

        target_mode = str(body.get('autostart') or '').strip()
        if target_mode in ('none', 'logon', 'boot'):
            old_mode = str(cfg.get('autostart') or 'none')
            cfg['autostart'] = target_mode
            if target_mode != old_mode or autostart.query() != target_mode:
                ok, msg = autostart.apply(target_mode)
                msgs.append(msg)
                if not ok:
                    cfg['autostart'] = old_mode
        self.config.save()
        return '；'.join(msgs) or '设置已保存'

    def stop(self) -> None:
        """停止 HTTP 服务。"""
        if self._httpd is not None:
            try:
                self._httpd.shutdown()
                self._httpd.server_close()
            except Exception:
                pass
            self._httpd = None
            self._thread = None
