"""游戏引擎测试：生成、推进、吃食、碰撞与快照字段。"""
from __future__ import annotations

import unittest

from tests.fixtures import FakeConn, make_service


class TestEngine(unittest.TestCase):
    """对阵引擎的基础行为。"""

    def _make_room(self):
        """创建一个两人房间并开局。"""
        svc = make_service()
        a = FakeConn(1, '甲')
        b = FakeConn(2, '乙')
        svc.add_conn(a)
        svc.add_conn(b)
        svc.handle(a, '{"t":"name","name":"甲"}')
        svc.handle(b, '{"t":"name","name":"乙"}')
        svc.handle(a, '{"t":"create","name":"甲","maxPlayers":2,"map":"classic","diff":"normal","isPublic":true}')
        code = a.room.code
        svc.handle(b, '{"t":"join","code":"%s","name":"乙"}' % code)
        svc.handle(a, '{"t":"start"}')
        return svc, a, b, a.room

    def test_room_and_game_created(self):
        """开局后房间与对局状态正确。"""
        svc, a, b, room = self._make_room()
        self.assertEqual(room.state, 'playing')
        self.assertIsNotNone(room.game)
        self.assertEqual(len(room.game.snakes), 2)
        self.assertEqual(len(room.game.lives), 2)
        self.assertGreaterEqual(len(room.game.foods), 1)

    def test_tick_and_snapshot(self):
        """推进若干 tick 后快照字段完整且数值合理。"""
        svc, a, b, room = self._make_room()
        for _ in range(400):
            svc.tick(20)
        snap = room.game.snapshot()
        for key in ('phase', 'cd', 'cols', 'rows', 'snakes', 'foods', 'powers',
                    'effects', 'obstacles', 'lives', 'elapsed'):
            self.assertIn(key, snap)
        for s in snap['snakes']:
            self.assertGreaterEqual(s['score'], 0)
            self.assertGreaterEqual(len(s['body']), 0)
            self.assertIn('dir', s)
            self.assertIn('color', s)
        self.assertGreaterEqual(snap['elapsed'], 0)

    def test_input_prevents_reverse(self):
        """方向输入不允许 180° 掉头。"""
        svc, a, b, room = self._make_room()
        g = room.game
        s = g.snakes[0]
        cur = s['dir']
        g.input(s['pid'], -cur['x'], -cur['y'])
        self.assertEqual(len(s['queue']), 0)

    def test_long_run_no_crash(self):
        """长时间推进不抛异常。"""
        svc, a, b, room = self._make_room()
        for i in range(1200):
            svc.tick(10)
            if i % 3 == 0:
                g = room.game
                if g is not None and g.phase == 'playing':
                    g.input(g.snakes[0]['pid'], 1, 0)
                    g.input(g.snakes[1]['pid'], -1, 0)
        self.assertIn(room.game.phase, ('countdown', 'playing', 'over'))

    def test_game_over_broadcast(self):
        """强制结算会广播 over 且带结果。"""
        svc, a, b, room = self._make_room()
        room.game.finish()
        over = a.last('over')
        self.assertIsNotNone(over)
        self.assertGreaterEqual(len(over['result']), 1)
        self.assertIn('totals', over)


if __name__ == '__main__':
    unittest.main()
