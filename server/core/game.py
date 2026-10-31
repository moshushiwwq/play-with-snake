"""房间内的权威对局引擎（由原 Node 版 Game 类逐条移植）。

所有判定都在服务端进行：移动、吃食、道具、护盾、穿墙、碰撞、复活与结算；
客户端只负责渲染服务端下发的 snapshot。字段名与旧版保持完全一致，
以保证既有客户端与服务端协议零变更。
"""
from __future__ import annotations

import math
import random
import time

from shared.constants import DIFFS, DIRS


class Game:
    """单个房间的一局对战。

    Attributes:
        phase: countdown / playing / over。
        countdown: 倒计时秒数。
        elapsed: 已进行的毫秒数。
        snakes: 蛇状态列表（含 pid/name/color/alive/body/score/kills/dir）。
        foods: 食物列表 [{x,y,k}]，k=1 普通、k=2 金星。
        powers: 道具列表 [{x,y,k,life}]，k 为 speed/slow/shield/ghost。
        effects: 按 pid 的效果字典 {pid: {speed,slow,ghost,shield,portal}}。
        events: 待发送的瞬时事件（eat/die/power/shield/respawn）。
    """

    def __init__(self, room, map_def: dict):
        """初始化一局对战。

        Args:
            room: 所属 Room。
            map_def: 已解析的地图字典（含 id/cols/rows/obstacles）。
        """
        self.room = room
        self.map = map_def
        self.diff = DIFFS.get(room.settings['diff'], DIFFS['normal'])
        self.cols = int(map_def['cols'])
        self.rows = int(map_def['rows'])
        self.obstacles = [{'x': int(o['x']), 'y': int(o['y'])} for o in map_def['obstacles']]
        self.phase = 'countdown'
        self.countdown = 3
        self.tick = 0
        self.round = room.round
        self.foods: list[dict] = []
        self.powers: list[dict] = []
        self.effects: dict[int, dict] = {}
        self.snakes: list[dict] = []
        self.events: list[dict] = []
        self.lives: dict[int, int] = {}
        self.started_at = time.time()
        self.elapsed = 0.0
        self.spawn()

    # ------------------------------------------------------------------ 生成
    def spawn(self) -> None:
        """在地图中央环状分布所有玩家的初始蛇（4 节、方向朝外）。"""
        cols, rows = self.cols, self.rows
        n = len(self.room.players)
        cx, cy = cols // 2, rows // 2
        radius = max(6, int(min(cols, rows) / 3))
        self.snakes = []
        for i, p in enumerate(self.room.players):
            ang = (math.pi * 2 * i) / max(1, n) - math.pi / 2
            hx = int(round(cx + math.cos(ang) * radius))
            hy = int(round(cy + math.sin(ang) * radius))
            hx = max(4, min(cols - 5, hx))
            hy = max(4, min(rows - 5, hy))
            dx = 1 if math.cos(ang) >= 0 else -1
            dy = 0
            if abs(math.sin(ang)) > 0.85:
                dx = 0
                dy = 1 if math.sin(ang) > 0 else -1
            body = [{'x': hx - dx * k, 'y': hy - dy * k} for k in range(4)]
            self.snakes.append({
                'pid': p['id'], 'name': p['name'], 'color': p['color'], 'alive': True, 'respawn': 0,
                'x': hx, 'y': hy, 'dir': {'x': dx, 'y': dy}, 'queue': [], 'body': body,
                'score': 0, 'kills': 0, 'grow': 0,
                'speedT': 0, 'slowT': 0, 'shield': 0, 'ghost': 0, 'next_at': 0.0,
            })
            self.effects[p['id']] = {'speed': 0, 'slow': 0, 'ghost': 0, 'shield': 0, 'portal': 0}
        self.lives = {s['pid']: 3 for s in self.snakes}
        self.foods = []
        for _ in range(int(self.diff['food'])):
            self.spawn_food()
        self.powers = []

    def occupied(self, x: int, y: int) -> bool:
        """判断某格是否已被墙体/蛇身/食物/道具占用。

        Args:
            x: 列坐标。
            y: 行坐标。

        Returns:
            被占用返回 True。
        """
        if any(o['x'] == x and o['y'] == y for o in self.obstacles):
            return True
        for s in self.snakes:
            for b in s['body']:
                if b['x'] == x and b['y'] == y:
                    return True
        for f in self.foods:
            if f['x'] == x and f['y'] == y:
                return True
        for p in self.powers:
            if p['x'] == x and p['y'] == y:
                return True
        return False

    def free_cell(self) -> dict | None:
        """在可玩区域内随机找一个空格。

        Returns:
            {'x','y'} 或 None（找不到时）。
        """
        for _ in range(300):
            x = 1 + int(random.random() * (self.cols - 2))
            y = 1 + int(random.random() * (self.rows - 2))
            if not self.occupied(x, y):
                return {'x': x, 'y': y}
        return None

    def spawn_food(self) -> None:
        """生成一个食物（18% 概率为金星）。"""
        c = self.free_cell()
        if c:
            self.foods.append({'x': c['x'], 'y': c['y'], 'k': 2 if random.random() < 0.18 else 1})

    def spawn_power(self) -> None:
        """生成一个限时道具（速度/减速/护盾/穿墙，寿命 240 tick）。"""
        c = self.free_cell()
        if not c:
            return
        kinds = ['speed', 'slow', 'shield', 'ghost']
        self.powers.append({'x': c['x'], 'y': c['y'], 'k': kinds[int(random.random() * len(kinds))], 'life': 240})

    # ------------------------------------------------------------------ 输入
    def input(self, pid: int, dx: int, dy: int) -> None:
        """接收一个方向输入（禁止 180° 掉头，队列最多 2 个）。

        Args:
            pid: 玩家连接 id。
            dx: 横向方向 -1/0/1。
            dy: 纵向方向 -1/0/1。
        """
        s = next((v for v in self.snakes if v['pid'] == pid), None)
        if not s or not s['alive']:
            return
        last = s['queue'][-1] if s['queue'] else s['dir']
        if dx == -last['x'] and dy == -last['y']:
            return
        if dx == last['x'] and dy == last['y']:
            return
        if len(s['queue']) >= 2:
            s['queue'].pop(0)
        s['queue'].append({'x': dx, 'y': dy})

    # ------------------------------------------------------------------ 推进
    def step(self) -> None:
        """推进一个逻辑帧（由 GameService 按难度速度调用）。"""
        self.tick += 1
        if self.phase == 'countdown':
            self.countdown -= 1
            if self.countdown <= 0:
                self.phase = 'playing'
                self.started_at = time.time()
            return
        if self.phase != 'playing':
            return
        self.elapsed += 1000.0 / self.diff['speed']

        now = time.time()
        for s in self.snakes:
            if not s['alive']:
                s['respawn'] -= 1
                if s['respawn'] <= 0 and self.lives.get(s['pid'], 0) > 0:
                    self.respawn_snake(s)

        heads: dict[str, list[int]] = {}
        for s in self.snakes:
            if not s['alive']:
                continue
            if s['speedT'] > 0:
                s['speedT'] -= 1
            if s['slowT'] > 0:
                s['slowT'] -= 1
            if s['shield'] > 0:
                s['shield'] -= 1
            if s['ghost'] > 0:
                s['ghost'] -= 1
            if s['next_at'] and now < s['next_at']:
                continue
            if s['speedT'] > 0:
                s['next_at'] = now + int(500 / self.diff['speed']) / 1000.0
            elif s['slowT'] > 0:
                s['next_at'] = now + int(1500 / self.diff['speed']) / 1000.0
            else:
                s['next_at'] = 0.0

            d = s['queue'].pop(0) if s['queue'] else s['dir']
            s['dir'] = d
            s['x'] += d['x']
            s['y'] += d['y']
            s['body'].insert(0, {'x': s['x'], 'y': s['y']})
            if s['grow'] > 0:
                s['grow'] -= 1
            else:
                s['body'].pop()

            # 进食
            for i in range(len(self.foods) - 1, -1, -1):
                f = self.foods[i]
                if f['x'] == s['x'] and f['y'] == s['y']:
                    gain = 30 if f['k'] == 2 else 10
                    s['score'] += gain
                    s['grow'] += int(self.diff['grow']) + (2 if f['k'] == 2 else 0)
                    self.foods.pop(i)
                    self.spawn_food()
                    self.events.append({'t': 'eat', 'pid': s['pid'], 'p': gain, 'x': f['x'], 'y': f['y']})
            # 道具
            for i in range(len(self.powers) - 1, -1, -1):
                p = self.powers[i]
                if p['x'] == s['x'] and p['y'] == s['y']:
                    self.powers.pop(i)
                    if p['k'] == 'speed':
                        s['speedT'] = 60
                        self.effects[s['pid']]['speed'] = 60
                    elif p['k'] == 'slow':
                        s['slowT'] = 60
                        self.effects[s['pid']]['slow'] = 60
                    elif p['k'] == 'shield':
                        s['shield'] = 200
                        self.effects[s['pid']]['shield'] = 200
                    elif p['k'] == 'ghost':
                        s['ghost'] = 90
                        self.effects[s['pid']]['ghost'] = 90
                    self.events.append({'t': 'power', 'pid': s['pid'], 'k': p['k']})
            # 自然补充
            if len(self.foods) < int(self.diff['food']):
                self.spawn_food()
            if len(self.powers) < 2 and random.random() < 0.01:
                self.spawn_power()

            key = '%d,%d' % (s['x'], s['y'])
            heads.setdefault(key, []).append(s['pid'])

        # 碰撞判定
        for s in self.snakes:
            if not s['alive'] or s['ghost'] > 0:
                continue
            hit = None
            if s['x'] < 0 or s['y'] < 0 or s['x'] >= self.cols or s['y'] >= self.rows:
                hit = 'wall'
            elif any(o['x'] == s['x'] and o['y'] == s['y'] for o in self.obstacles):
                hit = 'wall'
            if not hit and len(heads.get('%d,%d' % (s['x'], s['y']), [])) > 1:
                hit = 'head'
            if not hit:
                for o in self.snakes:
                    if o is s:
                        for i in range(1, len(o['body'])):
                            if o['body'][i]['x'] == s['x'] and o['body'][i]['y'] == s['y']:
                                hit = 'self'
                                break
                    else:
                        if o['alive'] and o['x'] == s['x'] and o['y'] == s['y']:
                            hit = 'head'
                        else:
                            for b in o['body']:
                                if b['x'] == s['x'] and b['y'] == s['y']:
                                    hit = 'body'
                                    break
                    if hit:
                        break
            if hit:
                if s['shield'] > 0 and hit != 'self':
                    s['shield'] = 0
                    self.effects[s['pid']]['shield'] = 0
                    self.events.append({'t': 'shield', 'pid': s['pid']})
                else:
                    self.kill(s, hit)

        self.effects = {}
        for s in self.snakes:
            self.effects[s['pid']] = {
                'speed': s['speedT'], 'slow': s['slowT'], 'ghost': s['ghost'],
                'shield': s['shield'] if s['shield'] > 0 else 0, 'portal': 0,
            }
        for i in range(len(self.powers) - 1, -1, -1):
            self.powers[i]['life'] -= 1
            if self.powers[i]['life'] <= 0:
                self.powers.pop(i)
        self.check_end()

    def kill(self, s: dict, reason: str) -> None:
        """处理一次死亡：扣命、置复活倒计时、记录击杀归属。

        Args:
            s: 蛇状态。
            reason: wall/head/body/self。
        """
        s['alive'] = False
        s['body'] = []
        self.lives[s['pid']] = max(0, self.lives.get(s['pid'], 1) - 1)
        s['respawn'] = 12 if self.lives[s['pid']] > 0 else 0
        self.events.append({'t': 'die', 'pid': s['pid'], 'reason': reason})
        if reason == 'body':
            for o in self.snakes:
                if o['pid'] == s['pid'] or not o['alive']:
                    continue
                if any(b['x'] == s['x'] and b['y'] == s['y'] for b in o['body']):
                    o['kills'] += 1
                    o['score'] += 25
                    break

    def respawn_snake(self, s: dict) -> None:
        """在随机空格复活一条蛇（4 节、60 tick 无敌护盾）。

        Args:
            s: 蛇状态。
        """
        c = self.free_cell()
        if not c:
            s['respawn'] = 6
            return
        s['alive'] = True
        s['x'] = c['x']
        s['y'] = c['y']
        d = DIRS[int(random.random() * 4)]
        s['dir'] = {'x': d[0], 'y': d[1]}
        s['body'] = [{'x': c['x'] - d[0] * k, 'y': c['y'] - d[1] * k} for k in range(4)]
        s['queue'] = []
        s['shield'] = 60
        s['next_at'] = 0.0
        self.events.append({'t': 'respawn', 'pid': s['pid']})

    def alive_count(self) -> int:
        """返回当前存活的蛇数量。"""
        return sum(1 for s in self.snakes if s['alive'])

    def check_end(self) -> None:
        """检查结束条件（全员无命，或多人局仅剩 1 条命，或超过 4 分钟）。"""
        if self.phase != 'playing':
            return
        with_lives = [s for s in self.snakes if self.lives.get(s['pid'], 0) > 0 or s['alive']]
        if not with_lives:
            self.finish()
            return
        if len(self.snakes) > 1 and self.alive_count() <= 1 and \
                len([s for s in with_lives if s['alive'] or self.lives.get(s['pid'], 0) > 0]) <= 1:
            self.finish()
        if self.elapsed > 4 * 60 * 1000:
            self.finish()

    def finish(self) -> None:
        """结算本局：按分数排序、写入玩家统计并广播 over。"""
        if self.phase == 'over':
            return
        self.phase = 'over'
        self.room.state = 'over'
        rows = [{
            'pid': s['pid'], 'name': s['name'], 'score': s['score'], 'kills': s['kills'],
            'lives': self.lives.get(s['pid'], 0), 'alive': s['alive'], 'color': s['color'],
        } for s in self.snakes]
        rows.sort(key=lambda r: (-r['score'], -r['kills']))
        if rows:
            rows[0]['win'] = True
        self.room.last_result = rows
        self.room.service.leaderboard.match(
            [{'name': r['name'], 'score': r['score'], 'kills': r['kills'], 'win': bool(r.get('win'))} for r in rows])
        self.room.broadcast({
            't': 'over', 'round': self.round, 'result': rows,
            'totals': [{
                'name': p['name'],
                'score': next((s['score'] for s in self.snakes if s['pid'] == p['id']), 0),
                'kills': next((s['kills'] for s in self.snakes if s['pid'] == p['id']), 0),
                'color': p['color'],
            } for p in self.room.players],
            'canRematch': True,
        })
        self.room.service.log('房间 %s 第 %d 局结束，冠军 %s' % (
            self.room.code, self.round, rows[0]['name'] if rows else '-'))

    # ------------------------------------------------------------------ 快照
    def snapshot(self) -> dict:
        """生成下发给客户端的权威快照（字段名与旧版完全一致）。

        Returns:
            快照字典。
        """
        return {
            'phase': self.phase,
            'cd': self.countdown,
            'cols': self.cols,
            'rows': self.rows,
            'tick': self.tick,
            'map': self.map['id'],
            'diff': self.diff['name'],
            'elapsed': int(round(self.elapsed / 1000)),
            'snakes': [{
                'pid': s['pid'], 'name': s['name'], 'color': s['color'], 'alive': s['alive'],
                'body': s['body'], 'score': s['score'], 'kills': s['kills'],
                'lives': self.lives.get(s['pid'], 0), 'dir': s['dir'],
            } for s in self.snakes],
            'foods': self.foods,
            'powers': self.powers,
            'effects': self.effects,
            'obstacles': self.obstacles,
            'lives': self.lives,
        }
