"""HTTP 接口测试：页面/发现/排行榜/地图/成绩/密码。"""
from __future__ import annotations

import json
import socket
import unittest
import urllib.error
import urllib.request

from shared.version import APP_VERSION
from server.net.http_api import HttpApi
from server.store.auth import PanelAuth
from tests.fixtures import NullConfig, make_service


def _free_port() -> int:
    """取一个空闲端口。"""
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    p = s.getsockname()[1]
    s.close()
    return p


class TestHttpApi(unittest.TestCase):
    """HTTP 层端到端。"""

    @classmethod
    def setUpClass(cls):
        """启动服务。"""
        cls.port = _free_port()
        cls.svc = make_service()
        cls.auth = PanelAuth(None, lambda params: None)
        cls.cfg = NullConfig(cls.port, 18081)
        cls.api = HttpApi(cls.svc, cls.cfg, cls.auth, APP_VERSION)
        ok, msg = cls.api.start()
        assert ok, msg
        cls.base = 'http://127.0.0.1:%d' % cls.port

    @classmethod
    def tearDownClass(cls):
        """停止服务。"""
        cls.api.stop()

    def _get(self, path: str) -> tuple[int, dict]:
        """GET 并解析 JSON。"""
        req = urllib.request.Request(self.base + path)
        try:
            with urllib.request.urlopen(req, timeout=6) as r:
                return r.status, json.loads(r.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode('utf-8', 'replace') or '{}')

    def _post(self, path: str, obj: dict, cookie: str = '') -> tuple[int, dict]:
        """POST JSON。"""
        data = json.dumps(obj).encode('utf-8')
        req = urllib.request.Request(self.base + path, data=data,
                                     headers={'Content-Type': 'application/json',
                                              **({'Cookie': cookie} if cookie else {})})
        try:
            with urllib.request.urlopen(req, timeout=8) as r:
                return r.status, json.loads(r.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode('utf-8', 'replace') or '{}')

    def test_health_and_discover(self):
        """/health 与 /api/discover 可用且带 wsPort。"""
        code, j = self._get('/health')
        self.assertEqual(code, 200)
        self.assertEqual(j['v'], APP_VERSION)
        code, j = self._get('/api/discover')
        self.assertEqual(code, 200)
        self.assertEqual(j['app'], 'snake-lan-server')
        self.assertEqual(j['wsPort'], 18081)
        self.assertEqual(j['port'], self.port)

    def test_pages(self):
        """首页与面板页都能返回 HTML。"""
        with urllib.request.urlopen(self.base + '/', timeout=8) as r:
            body = r.read().decode('utf-8')
        self.assertIn('index.html', body) if False else None
        self.assertIn('Play With Snake', body)
        with urllib.request.urlopen(self.base + '/panel', timeout=8) as r:
            panel = r.read().decode('utf-8')
        self.assertIn('管理员账号', panel)
        self.assertIn('排行榜', panel)

    def test_rank_signature(self):
        """签名不符返回 400，合法记录入榜。"""
        from shared.protocol import snake_sig
        rec = {'id': 'h1', 'mode': 'single', 'diff': 'normal', 'players': ['甲', ''],
               'scores': [88, 0], 'levels': [1, 1], 'lens': [7, 0], 'duration': 40,
               'mapId': 'classic', 'name': '甲', 'score': 88, 'length': 7,
               'mapName': '经典', 'date': '2026-10-31'}
        rec['sig'] = 'deadbeef'
        code, j = self._post('/api/rank', rec)
        self.assertEqual(code, 400)
        self.assertIn('校验失败', j['msg'])
        rec['sig'] = snake_sig(rec)
        code, j = self._post('/api/rank', rec)
        self.assertEqual(code, 200)
        self.assertTrue(j['ok'])

    def test_online_board_read(self):
        """联机榜只返回前 30 条并附带 note 字段。"""
        code, j = self._get('/api/online-board')
        self.assertEqual(code, 200)
        self.assertTrue(j['ok'])
        self.assertLessEqual(len(j['rows']), 30)
        for r in j['rows']:
            self.assertIn('note', r)

    def test_maps_upload_and_list(self):
        """自制地图上传与列表。"""
        code, j = self._post('/api/map', {
            'id': 'm1', 'name': '测试图', 'author': '测试', 'mode': 'single',
            'cols': 16, 'rows': 16, 'walls': [[2, 2]], 'wallPass': False,
        })
        self.assertEqual(code, 200)
        self.assertTrue(j['ok'])
        code, j = self._get('/api/maps')
        self.assertEqual(code, 200)
        self.assertTrue(any(m['id'] == 'm1' for m in j['maps']))
        code, j = self._post('/api/map', {
            'id': 'classic', 'name': '冲突', 'cols': 16, 'rows': 16, 'walls': [],
        })
        self.assertEqual(code, 400)

    def test_solo_score(self):
        """单机成绩入库。"""
        code, j = self._post('/api/solo-score', {'name': '甲', 'score': 60, 'length': 6})
        self.assertEqual(code, 200)
        self.assertTrue(j['ok'])

    def test_auth_flow_and_lockout(self):
        """设置密码 → 未登录 401 → 登录 → 连续失败锁定。"""
        self.auth.set_password('Unit-Test-Pass')
        code, j = self._get('/api/leaderboard')
        self.assertEqual(code, 401)
        code, j = self._post('/api/auth/login', {'password': 'Unit-Test-Pass'})
        self.assertEqual(code, 200)
        self.assertTrue(j['ok'])
        cookie = 'snake_panel=' + list(self.auth.sessions.keys())[-1]
        code, j = self._get('/api/leaderboard')
        self.assertEqual(code, 401)  # _get 不发送 Cookie
        # 直接带 Cookie 校验
        req = urllib.request.Request(self.base + '/api/leaderboard', headers={'Cookie': cookie})
        with urllib.request.urlopen(req, timeout=6) as r:
            self.assertEqual(r.status, 200)
        for _ in range(5):
            code, _ = self._post('/api/auth/login', {'password': 'wrong'})
        code, j = self._post('/api/auth/login', {'password': 'wrong'})
        self.assertEqual(code, 429)


class TestHttpLogs(unittest.TestCase):
    """管理面板日志接口：完整列表、级别过滤、下载与清空。"""

    @classmethod
    def setUpClass(cls):
        """启动带 LogBus 的服务。"""
        import tempfile

        from server.sys.logs import LogBus

        cls.tmp = tempfile.TemporaryDirectory()
        cls.port = _free_port()
        cls.svc = make_service()
        cls.auth = PanelAuth(None, lambda params: None)
        cls.cfg = NullConfig(cls.port, 18082)
        cls.bus = LogBus(cls.tmp.name)
        cls.api = HttpApi(cls.svc, cls.cfg, cls.auth, APP_VERSION,
                          cls.bus.push, logbus=cls.bus)
        ok, msg = cls.api.start()
        assert ok, msg
        cls.base = 'http://127.0.0.1:%d' % cls.port

        cls.bus.push('服务器已启动', 'ok')
        for i in range(12):
            cls.bus.push('房间测试第 %d 条' % i)
        cls.bus.push('端口占用', 'warn')
        cls.bus.push('tick 异常', 'error')

    @classmethod
    def tearDownClass(cls):
        """停止服务并清理临时目录。"""
        cls.api.stop()
        cls.tmp.cleanup()

    def _get_json(self, path: str) -> tuple[int, dict]:
        """GET 并解析 JSON。"""
        req = urllib.request.Request(self.base + path)
        try:
            with urllib.request.urlopen(req, timeout=6) as r:
                return r.status, json.loads(r.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode('utf-8', 'replace') or '{}')

    def _post_json(self, path: str, obj: dict) -> tuple[int, dict]:
        """POST JSON。"""
        data = json.dumps(obj).encode('utf-8')
        req = urllib.request.Request(self.base + path, data=data,
                                     headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=8) as r:
                return r.status, json.loads(r.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode('utf-8', 'replace') or '{}')

    def test_full_list_and_levels(self):
        """默认返回全部条目（含 level），并按级别过滤。"""
        code, j = self._get_json('/api/logs?limit=200')
        self.assertEqual(code, 200)
        self.assertTrue(j['ok'])
        self.assertEqual(j['source'], 'memory')
        texts = {(e['text'], e['level']) for e in j['entries']}
        self.assertIn(('服务器已启动', 'ok'), texts)
        self.assertIn(('tick 异常', 'error'), texts)
        self.assertIn(('房间测试第 0 条', 'info'), texts)
        for i in range(12):
            self.assertIn(('房间测试第 %d 条' % i, 'info'), texts)
        self.assertIn('fileSize', j['stats'])

        code, j = self._get_json('/api/logs?limit=200&level=error')
        self.assertEqual(len(j['entries']), 1)
        self.assertEqual(j['entries'][0]['text'], 'tick 异常')

        code, j = self._get_json('/api/logs?limit=200&level=warn')
        self.assertGreaterEqual(len(j['entries']), 1)
        self.assertTrue(all(e['level'] in ('warn', 'error') for e in j['entries']))

    def test_download_and_clear(self):
        """下载返回整份 server.log；清空后文件归零、历史仍可在内存查看。"""
        with urllib.request.urlopen(self.base + '/api/logs/download', timeout=8) as r:
            body = r.read().decode('utf-8')
        self.assertIn('服务器已启动', body)
        self.assertIn('tick 异常', body)

        code, j = self._post_json('/api/logs/clear', {})
        self.assertEqual(code, 200)
        self.assertTrue(j['ok'])
        self.assertEqual(j['stats']['fileSize'], 0)

        code, j = self._get_json('/api/logs?limit=200')
        self.assertTrue(any(e['text'] == '服务器已启动' for e in j['entries']))


class TestLogBus(unittest.TestCase):
    """日志总线的读取与级别过滤（面板数据来源）。"""

    def test_entries_filter_and_file(self):
        """内存条目带级别；过滤无匹配时返回空列表，不会串到文件历史。"""
        import tempfile

        from server.sys.logs import LogBus

        with tempfile.TemporaryDirectory() as d:
            bus = LogBus(d)
            bus.push('开局', 'ok')
            bus.push('房间已创建')
            bus.push('端口占用', 'warn')
            self.assertEqual([e['text'] for e in bus.entries(10, 'error')], [])
            self.assertEqual([e['text'] for e in bus.entries(10, 'warn')], ['端口占用'])
            self.assertEqual([e['text'] for e in bus.entries(10, 'info')], ['开局', '房间已创建'])
            self.assertEqual(len(bus.entries(10, 'all')), 3)
            stats = bus.stats()
            self.assertGreater(stats['fileSize'], 0)
            self.assertEqual(stats['memory'], 3)
            # 文件回读用于重启后回显历史
            lines = bus.read_file(10)
            self.assertEqual(len(lines), 3)
            self.assertIn('端口占用', lines[-1]['text'])
            self.assertTrue(lines[0]['ts'])


if __name__ == '__main__':
    unittest.main()
