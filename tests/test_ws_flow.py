"""消息流程测试：hello 之外的完整 WS 协议（使用协议层直调，无需真实网络）。"""
from __future__ import annotations

import unittest

from tests.fixtures import FakeConn, make_service


class TestMessageFlow(unittest.TestCase):
    """覆盖联机主流程与异常分支。"""

    def setUp(self):
        """建立服务与两名玩家。"""
        self.svc = make_service()
        self.a = FakeConn(1, '房主甲')
        self.b = FakeConn(2, '玩家乙')
        for c in (self.a, self.b):
            self.svc.add_conn(c)

    def _send(self, conn, obj):
        """以 JSON 文本发送一条消息。"""
        import json
        self.svc.handle(conn, json.dumps(obj, ensure_ascii=False))

    def test_name_and_lobby(self):
        """自报昵称与请求大厅。"""
        self._send(self.a, {'t': 'name', 'name': '房主甲'})
        self.assertEqual(self.a.last('me')['name'], '房主甲')
        self._send(self.a, {'t': 'lobby'})
        self.assertIn('rooms', self.a.last('lobby'))

    def test_create_and_join(self):
        """开房、加入、房间公示与成员信息。"""
        self._send(self.a, {'t': 'name', 'name': '房主甲'})
        self._send(self.a, {'t': 'create', 'name': '房主甲', 'maxPlayers': 2,
                            'map': 'classic', 'diff': 'normal', 'isPublic': True})
        room_msg = self.a.last('room')
        self.assertIsNotNone(room_msg)
        code = room_msg['room']['code']
        self.assertEqual(room_msg['room']['mapName'], '经典空地')
        self.assertTrue(room_msg['room']['isPublic'])
        self._send(self.b, {'t': 'join', 'code': code, 'name': '玩家乙'})
        self.assertIsNotNone(self.b.last('room'))
        self.assertEqual(self.b.last('room')['room']['count'], 2)

    def test_join_wrong_code(self):
        """房间码错误返回 err。"""
        self._send(self.b, {'t': 'join', 'code': 'ZZZZ', 'name': '玩家乙'})
        self.assertIn('不存在', self.b.last('err')['msg'])

    def test_password_required(self):
        """私密房密码错误被拒并标记 needPass。"""
        self._send(self.a, {'t': 'create', 'name': '甲', 'maxPlayers': 2,
                            'map': 'classic', 'diff': 'normal', 'password': 'abc123'})
        code = self.a.last('room')['room']['code']
        self._send(self.b, {'t': 'join', 'code': code, 'name': '乙'})
        err = self.b.last('err')
        self.assertTrue(err.get('needPass'))
        self._send(self.b, {'t': 'join', 'code': code, 'name': '乙', 'password': 'abc123'})
        self.assertIsNotNone(self.b.last('room'))

    def test_only_host_can_start(self):
        """非房主开始游戏被拒绝。"""
        self._send(self.a, {'t': 'create', 'name': '甲', 'maxPlayers': 2})
        code = self.a.last('room')['room']['code']
        self._send(self.b, {'t': 'join', 'code': code, 'name': '乙'})
        self._send(self.b, {'t': 'start'})
        self.assertIn('房主', self.b.last('err')['msg'])
        self._send(self.a, {'t': 'start'})
        self.assertIsNotNone(self.a.last('start'))
        self.assertIsNotNone(self.b.last('start'))

    def test_state_broadcast_and_dir(self):
        """开局后 tick 会广播 state，方向指令生效。"""
        self._send(self.a, {'t': 'create', 'name': '甲', 'maxPlayers': 2})
        code = self.a.last('room')['room']['code']
        self._send(self.b, {'t': 'join', 'code': code, 'name': '乙'})
        self._send(self.a, {'t': 'start'})
        for _ in range(80):
            self.svc.tick(20)
        state = self.a.last('state')
        self.assertIsNotNone(state)
        self.assertGreaterEqual(len(state['s']['snakes']), 2)
        self._send(self.a, {'t': 'dir', 'x': 1, 'y': 0})
        self.assertEqual(self.a.count('err'), 0)

    def test_rank_submit_valid_and_invalid(self):
        """成绩提交：正常入榜，篡改被拒。"""
        from shared.protocol import snake_sig
        rec = {'id': 'r1', 'mode': 'single', 'diff': 'normal', 'players': ['甲', ''],
               'scores': [100, 0], 'levels': [1, 1], 'lens': [6, 0], 'duration': 30,
               'mapId': 'classic', 'name': '甲', 'score': 100, 'length': 6,
               'mapName': '经典', 'date': '2026-10-31'}
        rec['sig'] = snake_sig(rec)
        self._send(self.a, {'t': 'rank', 'rec': rec})
        self.assertIsNotNone(self.a.last('rankSaved'))
        bad = dict(rec)
        bad['score'] = 999999
        bad['scores'] = [999999, 0]
        self._send(self.a, {'t': 'rank', 'rec': bad})
        self.assertIn('校验失败', self.a.last('err')['msg'])
        self.assertEqual(len(self.svc.online_board.top(30)), 1)

    def test_solo_score(self):
        """单机成绩上报会广播 lb。"""
        self._send(self.a, {'t': 'solo', 'name': '甲', 'score': 50, 'length': 5})
        self.assertIsNotNone(self.a.last('soloSaved'))
        self.assertIsNotNone(self.a.last('lb'))

    def test_ping_pong(self):
        """心跳回应。"""
        self._send(self.a, {'t': 'ping', 'ts': 123})
        self.assertEqual(self.a.last('pong')['ts'], 123)

    def test_custom_map_create(self):
        """上传的自制地图可用于建房。"""
        ok, _ = self.svc.custom_maps.upsert({
            'id': 'demo', 'name': '演示', 'author': '测试', 'mode': 'single',
            'cols': 20, 'rows': 20, 'walls': [[3, 3]], 'wallPass': False,
        })
        self.assertTrue(ok)
        self._send(self.a, {'t': 'create', 'name': '甲', 'maxPlayers': 2, 'map': 'demo'})
        room = self.a.last('room')['room']
        self.assertEqual(room['map'], 'demo')
        self.assertEqual(room['mapName'], '演示')
        self._send(self.b, {'t': 'join', 'code': room['code'], 'name': '乙'})
        self._send(self.a, {'t': 'start'})
        self.assertIn('start', [m['t'] for m in self.a.sent])


if __name__ == '__main__':
    unittest.main()
