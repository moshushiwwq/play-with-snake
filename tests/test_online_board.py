"""联机入榜与回放测试：准备校验、IP 榜名、同分去重、服务端录制回放。"""
from __future__ import annotations

import json
import unittest

from tests.fixtures import FakeConn, make_service


class TestOnlineBoardAuto(unittest.TestCase):
    """联机对局结束后的自动入榜与回放。"""

    def _room(self, ips=('10.0.0.1', '10.0.0.2'), diff='normal'):
        """建一个两人房间并开局（全员准备）。"""
        svc = make_service()
        conns = []
        for i, ip in enumerate(ips):
            c = FakeConn(i + 1, '玩家%d' % (i + 1), ip=ip)
            svc.add_conn(c)
            svc.handle(c, json.dumps({'t': 'name', 'name': c.name}, ensure_ascii=False))
            conns.append(c)
        svc.handle(conns[0], json.dumps({
            't': 'create', 'name': '玩家1', 'maxPlayers': len(conns),
            'map': 'classic', 'diff': diff, 'isPublic': True,
        }, ensure_ascii=False))
        code = conns[0].room.code
        for c in conns[1:]:
            svc.handle(c, json.dumps({'t': 'join', 'code': code, 'name': c.name}, ensure_ascii=False))
        for c in conns:
            svc.handle(c, json.dumps({'t': 'ready', 'ready': True}, ensure_ascii=False))
        svc.handle(conns[0], json.dumps({'t': 'start'}))
        room = conns[0].room
        room.game.phase = 'playing'
        room.game.countdown_ms = 0.0
        room.game.countdown = 0
        return svc, conns, room

    def test_start_blocked_when_not_all_ready(self):
        """有玩家未准备时，房主手动开局被拒绝且不会创建对局。"""
        svc = make_service()
        a = FakeConn(1, '甲')
        b = FakeConn(2, '乙')
        for c in (a, b):
            svc.add_conn(c)
            svc.handle(c, json.dumps({'t': 'name', 'name': c.name}, ensure_ascii=False))
        svc.handle(a, json.dumps({'t': 'create', 'name': '甲', 'maxPlayers': 2}, ensure_ascii=False))
        code = a.room.code
        svc.handle(b, json.dumps({'t': 'join', 'code': code, 'name': '乙'}, ensure_ascii=False))
        svc.handle(a, json.dumps({'t': 'ready', 'ready': True}, ensure_ascii=False))

        svc.handle(a, json.dumps({'t': 'start'}))
        err = a.last('err')
        self.assertIsNotNone(err)
        self.assertIn('未准备', err['msg'])
        self.assertIsNone(a.room.game)
        self.assertEqual(a.room.state, 'waiting')

        svc.handle(b, json.dumps({'t': 'ready', 'ready': True}, ensure_ascii=False))
        svc.handle(a, json.dumps({'t': 'start'}))
        self.assertIsNotNone(a.room.game)

    def test_result_auto_submitted_with_ip_name(self):
        """对局结束自动入榜：名单为各自 IP，并携带同一条回放。"""
        svc, conns, room = self._room()
        g = room.game
        g.snakes[1]['score'] = 40
        g.snakes[0]['body'] = [{'x': 0, 'y': 10}, {'x': 1, 'y': 10}, {'x': 2, 'y': 10}, {'x': 3, 'y': 10}]
        g.snakes[0]['x'], g.snakes[0]['y'], g.snakes[0]['dir'] = 0, 10, {'x': -1, 'y': 0}
        g.step()

        rows = svc.online_board.top(30)
        self.assertEqual(len(rows), 2)
        names = sorted(r['name'] for r in rows)
        self.assertEqual(names, ['10.0.0.1', '10.0.0.2'])
        for r in rows:
            self.assertIn(r['name'], ('10.0.0.1', '10.0.0.2'))
            self.assertEqual(r['ip'], r['name'])
            self.assertTrue(r['hasReplay'])
            self.assertTrue(r['replayId'])
        self.assertEqual(len({r['replayId'] for r in rows}), 1)

        rid = rows[0]['replayId']
        payload = svc.replays.load(rid)
        self.assertIsNotNone(payload)
        self.assertGreater(len(payload['frames']), 0)
        rec = payload['rec']
        self.assertEqual(rec['mode'], 'duel')
        self.assertEqual(sorted(rec['players']), ['玩家1', '玩家2'])
        self.assertEqual(len(rec['skins']), 2)
        self.assertNotEqual(rec['skins'][0], rec['skins'][1])
        frame = payload['frames'][0]
        for key in ('b', 'f', 'o', 's', 'd', 'pt'):
            self.assertIn(key, frame)
        self.assertEqual(len(frame['b']), 2)

    def test_same_ip_same_score_keeps_earlier(self):
        """同一 IP 相同分数只保留更早的一条。"""
        svc, conns, room = self._room(ips=('10.0.0.9', '10.0.0.9'))
        g = room.game
        g.snakes[0]['score'] = 30
        g.snakes[1]['score'] = 30
        g.snakes[0]['body'] = [{'x': 0, 'y': 10}, {'x': 1, 'y': 10}, {'x': 2, 'y': 10}, {'x': 3, 'y': 10}]
        g.snakes[0]['x'], g.snakes[0]['y'], g.snakes[0]['dir'] = 0, 10, {'x': -1, 'y': 0}
        g.step()

        rows = svc.online_board.top(30)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['name'], '10.0.0.9')
        self.assertEqual(rows[0]['score'], 30)

    def test_replay_frames_bounded_and_snapshot_untouched(self):
        """回放帧有上限，且录制不影响权威快照字段。"""
        svc, conns, room = self._room()
        g = room.game
        for _ in range(50):
            g.step()
        self.assertGreater(len(g.rec_frames), 0)
        self.assertLessEqual(len(g.rec_frames), 1600)
        snap = g.snapshot()
        self.assertIn('snakes', snap)
        self.assertNotIn('rec_frames', snap)


if __name__ == '__main__':
    unittest.main()
