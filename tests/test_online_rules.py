"""联机规则回归：一命制、淘汰不再复活、无击杀加分、倒计时按时间推进。

这些用例都区分旧实现（3 条命 + 12 tick 复活 + 击杀 +25 分 + 3 tick 倒计时）。
"""
from __future__ import annotations

import json
import unittest

from tests.fixtures import FakeConn, make_service


class TestOnlineRules(unittest.TestCase):
    """联机对局规则与双人对战对齐。"""

    def _room(self, k: int, diff: str = 'normal'):
        """建一个 k 人房间并开局，返回 (service, conns, room)。"""
        svc = make_service()
        conns = []
        for i in range(k):
            c = FakeConn(i + 1, '玩家%d' % (i + 1))
            svc.add_conn(c)
            svc.handle(c, json.dumps({'t': 'name', 'name': c.name}, ensure_ascii=False))
            conns.append(c)
        svc.handle(conns[0], json.dumps({
            't': 'create', 'name': '玩家1', 'maxPlayers': k,
            'map': 'classic', 'diff': diff, 'isPublic': True,
        }, ensure_ascii=False))
        code = conns[0].room.code
        for c in conns[1:]:
            svc.handle(c, json.dumps({'t': 'join', 'code': code, 'name': c.name}, ensure_ascii=False))
        for c in conns:
            svc.handle(c, json.dumps({'t': 'ready', 'ready': True}))
        svc.handle(conns[0], json.dumps({'t': 'start'}))
        room = conns[0].room
        g = room.game
        g.phase = 'playing'
        g.countdown_ms = 0.0
        g.countdown = 0
        return svc, conns, room

    @staticmethod
    def _place(s, x, y, dx, dy):
        """把一条蛇摆到指定位置与朝向（身体四节沿反方向铺开）。"""
        s['x'], s['y'] = x, y
        s['dir'] = {'x': dx, 'y': dy}
        s['queue'] = []
        s['body'] = [{'x': x - dx * i, 'y': y - dy * i} for i in range(4)]

    def test_two_players_first_crash_ends_round(self):
        """2 人局：一人撞墙即结束，幸存者获胜（双人行为）。"""
        svc, conns, room = self._room(2)
        g = room.game
        self.assertEqual(len(g.lives), 2)
        self.assertEqual(sorted(g.lives.values()), [1, 1])
        self._place(g.snakes[0], 0, 10, -1, 0)
        self._place(g.snakes[1], 24, 20, 1, 0)

        g.step()

        self.assertFalse(g.snakes[0]['alive'])
        self.assertEqual(g.lives[g.snakes[0]['pid']], 0)
        self.assertEqual(g.phase, 'over')
        self.assertEqual(room.state, 'over')
        over = conns[0].last('over')
        self.assertIsNotNone(over)
        win = [r for r in over['result'] if r.get('win')]
        self.assertEqual(len(win), 1)
        self.assertEqual(win[0]['name'], '玩家2')

    def test_four_players_elimination_continues(self):
        """4 人局：一人出局后继续，剩最后一人时结束。"""
        svc, conns, room = self._room(4)
        g = room.game
        for s in g.snakes:
            self.assertEqual(g.lives[s['pid']], 1)
        self._place(g.snakes[0], 0, 6, -1, 0)
        self._place(g.snakes[1], 20, 12, 1, 0)
        self._place(g.snakes[2], 30, 18, 1, 0)
        self._place(g.snakes[3], 8, 30, 1, 0)

        g.step()
        self.assertFalse(g.snakes[0]['alive'])
        self.assertEqual(g.alive_count(), 3)
        self.assertEqual(g.phase, 'playing')
        self.assertEqual(room.state, 'playing')

        self._place(g.snakes[1], 0, 12, -1, 0)
        g.step()
        self.assertEqual(g.alive_count(), 2)
        self.assertEqual(g.phase, 'playing')

        self._place(g.snakes[2], 0, 18, -1, 0)
        g.step()
        self.assertEqual(g.alive_count(), 1)
        self.assertEqual(g.phase, 'over')
        over = conns[3].last('over')
        win = [r for r in over['result'] if r.get('win')]
        self.assertEqual(win[0]['name'], '玩家4')

    def test_body_kill_gives_no_score(self):
        """撞到对手身体：只记击杀数，不给分数（双人无击杀加分）。"""
        svc, conns, room = self._room(2)
        g = room.game
        target, other = g.snakes[0], g.snakes[1]
        self._place(target, 9, 6, 1, 0)
        self._place(other, 10, 7, 0, 1)

        g.step()

        self.assertFalse(target['alive'])
        self.assertEqual(other['kills'], 1)
        self.assertEqual(other['score'], 0)
        self.assertEqual(g.phase, 'over')
        win = [r for r in conns[0].last('over')['result'] if r.get('win')]
        self.assertEqual(win[0]['name'], '玩家2')
        self.assertEqual(win[0]['score'], 0)
        self.assertEqual(win[0]['kills'], 1)

    def test_no_respawn_after_death(self):
        """出局后不再复活：推进大量 tick 仍是同一条死蛇。"""
        svc, conns, room = self._room(4)
        g = room.game
        for s in g.snakes:
            self._place(s, 10 + 8 * g.snakes.index(s), 20, 1, 0)
        self._place(g.snakes[0], 0, 20, -1, 0)
        g.step()
        pid = g.snakes[0]['pid']
        for _ in range(200):
            if g.phase != 'playing':
                break
            g.step()
        self.assertFalse(g.snakes[0]['alive'])
        self.assertEqual(g.lives[pid], 0)

    def test_all_dead_is_draw(self):
        """全员同时阵亡算平局：不冒出冠军，over 里带 draw 标记（同双人对战「平局」）。"""
        svc, conns, room = self._room(2)
        g = room.game
        self._place(g.snakes[0], 0, 10, -1, 0)
        self._place(g.snakes[1], g.cols - 1, 20, 1, 0)

        g.step()

        self.assertEqual(g.alive_count(), 0)
        self.assertEqual(g.phase, 'over')
        over = conns[0].last('over')
        self.assertIsNotNone(over)
        self.assertTrue(over.get('draw'))
        self.assertFalse(any(r.get('win') for r in over['result']))

    def test_countdown_is_time_based(self):
        """倒计时按真实时间走 3 秒（旧实现按 tick 走，约 0.33 秒）。"""
        svc = make_service()
        a = FakeConn(1, '甲')
        b = FakeConn(2, '乙')
        for c in (a, b):
            svc.add_conn(c)
            svc.handle(c, json.dumps({'t': 'name', 'name': c.name}, ensure_ascii=False))
        svc.handle(a, json.dumps({'t': 'create', 'name': '甲', 'maxPlayers': 2,
                                  'map': 'classic', 'diff': 'normal'}, ensure_ascii=False))
        code = a.room.code
        svc.handle(b, json.dumps({'t': 'join', 'code': code, 'name': '乙'}, ensure_ascii=False))
        svc.handle(a, json.dumps({'t': 'ready', 'ready': True}, ensure_ascii=False))
        svc.handle(b, json.dumps({'t': 'ready', 'ready': True}, ensure_ascii=False))
        svc.handle(a, json.dumps({'t': 'start'}))
        g = a.room.game
        speed = g.diff['speed']
        self.assertEqual(g.snapshot()['cd'], 3)

        for _ in range(int(2.0 * speed)):
            g.step()
        self.assertEqual(g.phase, 'countdown')
        self.assertEqual(g.snapshot()['cd'], 1)

        for _ in range(int(1.2 * speed) + 1):
            g.step()
        self.assertEqual(g.phase, 'playing')
        self.assertEqual(g.snapshot()['cd'], 0)


if __name__ == '__main__':
    unittest.main()
