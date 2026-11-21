"""房间内的权威对局引擎（由原 Node 版 Game 类逐条移植）。

所有判定都在服务端进行：移动、吃食、道具、护盾、穿墙、碰撞与结算；
规则与双人对战同源：一人一命、撞到即淘汰、不复活，最后存活者获胜；
客户端只负责渲染服务端下发的 snapshot。字段名与旧版保持完全一致，
以保证既有客户端与服务端协议零变更。
"""
from __future__ import annotations

import colorsys
import math
import random
import time

from shared.constants import DIFFS

# 单局回放最多录制的帧数（防止极端长局把内存撑爆；10 帧/秒时约合 160 秒）
MAX_REPLAY_FRAMES = 1600

# 镜头朝向索引，与客户端 DIR_LIST 顺序（右/下/左/上）一致
_DIR_IDX = {(1, 0): 0, (0, 1): 1, (-1, 0): 2, (0, -1): 3}

# 道具在回放食物串里的类型下标，与客户端 FOOD_KEYS 顺序一致
_POWER_IDX = {'speed': 3, 'slow': 4, 'ghost': 5, 'shield': 7}

_B36 = '0123456789abcdefghijklmnopqrstuvwxyz'


def _b36(n: int) -> str:
    """整数转 36 进制（与客户端坐标编码同源）。"""
    n = int(n)
    if n <= 0:
        return '0'
    out = []
    while n:
        n, r = divmod(n, 36)
        out.append(_B36[r])
    return ''.join(reversed(out))


def _enc(x: int, y: int, rows: int, w: int) -> str:
    """把格坐标编码成定长 36 进制字符串（客户端 decCell 可直接解码）。"""
    return _b36(x * rows + y).rjust(w, '0')


def hue_from_color(hex_color: str, idx: int = 0) -> int:
    """把 #RRGGBB 颜色换成 0-360 色相，供回放按玩家上色。

    Args:
        hex_color: 颜色字符串。
        idx: 玩家序号（用于兜底配色）。

    Returns:
        色相整数。
    """
    fallback = (152, 212, 45, 330)[idx % 4]
    s = str(hex_color or '').strip().lstrip('#')
    if len(s) != 6:
        return fallback
    try:
        r = int(s[0:2], 16) / 255.0
        g = int(s[2:4], 16) / 255.0
        b = int(s[4:6], 16) / 255.0
    except Exception:
        return fallback
    h, _, _ = colorsys.rgb_to_hsv(r, g, b)
    return int(round(h * 360)) % 360


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
        events: 待发送的瞬时事件（eat/die/power/shield）。
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
        # 倒计时按毫秒推进（与难度速度解耦），保证任何难度下都实打实等 3 秒
        self.countdown_ms = 3000.0
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
        # 回放录制：服务端权威录制，客户端只负责播放
        self.cell_w = 3 if (self.cols * self.rows - 1) >= 1296 else 2
        self.rec_obstacles = [[o['x'], o['y']] for o in self.obstacles]
        self.rec_frames: list[dict] = []
        self.spawn()

    # ------------------------------------------------------------------ 生成
    def spawn(self) -> None:
        """按双人对战的抬位生成初始蛇（同一横向赛道两端相向，留足反应空间）。

        2 人：两人同处地图中线上、左右相向（与双人对战完全一致）。
        3-4 人：分成上下两条赛道，每条最多两人相向，避免开局即撞墙或秒撞。
        """
        cols, rows = self.cols, self.rows
        n = len(self.room.players)
        cx, cy = cols // 2, rows // 2
        offset = max(3, cols // 6)
        lane_gap = max(5, rows // 4)
        lanes = [cy] if n <= 2 else [cy - lane_gap, cy + lane_gap]
        self.snakes = []
        for i, p in enumerate(self.room.players):
            lane = lanes[(i // 2) % len(lanes)]
            dx = 1 if i % 2 == 0 else -1
            dy = 0
            hx = cx - offset if dx > 0 else cx + offset
            body = self._spawn_body(hx, lane, dx)
            if body is None:
                c = self.free_cell() or {'x': cx, 'y': cy}
                hx, lane = c['x'], c['y']
                dy = 1 if lane < cy else -1
                dx = 0
                body = self._spawn_body(hx, lane, dx, dy)
                if body is None:
                    body = [{'x': max(0, hx - k), 'y': lane} for k in range(4)]
                    dx, dy = 1, 0
            self.snakes.append({
                'pid': p['id'], 'name': p['name'], 'color': p['color'], 'alive': True,
                'x': body[0]['x'], 'y': body[0]['y'], 'dir': {'x': dx, 'y': dy},
                'queue': [], 'body': body,
                'score': 0, 'kills': 0, 'grow': 0,
                'speedT': 0, 'slowT': 0, 'shield': 0, 'ghost': 0, 'next_at': 0.0,
            })
            self.effects[p['id']] = {'speed': 0, 'slow': 0, 'ghost': 0, 'shield': 0, 'portal': 0}
        self.lives = {s['pid']: 1 for s in self.snakes}
        self.foods = []
        for _ in range(int(self.diff['food'])):
            self.spawn_food()
        self.powers = []

    def _spawn_body(self, x: int, y: int, dx: int, dy: int = 0, ln: int = 4) -> list[dict] | None:
        """生成一条蛇的初始身体，越界或压到墙体时返回 None。

        Args:
            x: 蛇头列坐标。
            y: 蛇头行坐标。
            dx: 蛇头朝向的横向分量。
            dy: 蛇头朝向的纵向分量。
            ln: 初始长度。

        Returns:
            身体列表（头在前），不可用时为 None。
        """
        cells = [{'x': x - dx * k, 'y': y - dy * k} for k in range(ln)]
        for c in cells:
            if not (0 <= c['x'] < self.cols and 0 <= c['y'] < self.rows):
                return None
            if any(o['x'] == c['x'] and o['y'] == c['y'] for o in self.obstacles):
                return None
        return cells

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
            self.countdown_ms -= 1000.0 / max(1, self.diff['speed'])
            self.countdown = max(0, math.ceil(self.countdown_ms / 1000.0))
            if self.countdown_ms <= 0:
                self.countdown = 0
                self.phase = 'playing'
                self.started_at = time.time()
                # 开局即录一帧，回放一开始就能看到双方的初始站位与蛇色
                self.record_frame()
            return
        if self.phase != 'playing':
            return
        self.elapsed += 1000.0 / self.diff['speed']

        now = time.time()

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
        self.record_frame()
        self.check_end()

    # ------------------------------------------------------------------ 回放
    def record_frame(self) -> None:
        """录制一帧回放数据（字段与客户端 drawReplayFrame 完全对齐）。"""
        if len(self.rec_frames) >= MAX_REPLAY_FRAMES:
            return
        w, rows = self.cell_w, self.rows
        bodies = [''.join(_enc(c['x'], c['y'], rows, w) for c in s['body']) for s in self.snakes]
        segs = []
        for f in self.foods:
            segs.append(_enc(f['x'], f['y'], rows, w) + ('1' if f.get('k') == 2 else '0'))
        for p in self.powers:
            segs.append(_enc(p['x'], p['y'], rows, w) + _b36(_POWER_IDX.get(p.get('k'), 0)))
        self.rec_frames.append({
            'b': bodies,
            'f': ''.join(segs),
            'o': len(self.rec_obstacles),
            's': [int(s['score']) for s in self.snakes],
            'd': [_DIR_IDX.get((s['dir']['x'], s['dir']['y']), 0) for s in self.snakes],
            'pt': '',
        })

    def replay_payload(self) -> dict:
        """生成本局回放（记录信息 + 帧数组）。"""
        diff_name = self.diff['name']
        players = [s['name'] for s in self.snakes]
        skins = [hue_from_color(s['color'], i) for i, s in enumerate(self.snakes)]
        rec = {
            'mode': 'duel' if len(self.snakes) > 1 else 'single',
            'players': players,
            'skins': skins,
            'colors': [s['color'] for s in self.snakes],
            'cols': self.cols,
            'rows': self.rows,
            'cellCode': self.cell_w,
            'obstacles': self.rec_obstacles,
            'mapId': self.map.get('id', 'classic'),
            'mapName': self.map.get('name', '经典'),
            'diff': self.room.settings.get('diff', 'normal'),
            'diffName': diff_name,
            'date': time.strftime('%Y-%m-%d %H:%M'),
            'duration': int(round(self.elapsed / 1000)),
            'round': self.round,
            'code': self.room.code,
            'scores': [int(s['score']) for s in self.snakes],
            'lens': [len(s['body']) for s in self.snakes],
        }
        return {'rec': rec, 'frames': list(self.rec_frames)}

    def kill(self, s: dict, reason: str) -> None:
        """处理一次死亡：一命制，撞到即淘汰（与双人对战一致，不再复活）。

        Args:
            s: 蛇状态。
            reason: wall/head/body/self。
        """
        s['alive'] = False
        s['body'] = []
        self.lives[s['pid']] = max(0, self.lives.get(s['pid'], 1) - 1)
        self.events.append({'t': 'die', 'pid': s['pid'], 'reason': reason})
        if reason == 'body':
            for o in self.snakes:
                if o['pid'] == s['pid'] or not o['alive']:
                    continue
                if any(b['x'] == s['x'] and b['y'] == s['y'] for b in o['body']):
                    # 只记击杀数：双人对战里撞到对手身体不给分，这里同样不加分
                    o['kills'] += 1
                    break

    def alive_count(self) -> int:
        """返回当前存活的蛇数量。"""
        return sum(1 for s in self.snakes if s['alive'])

    def check_end(self) -> None:
        """检查结束条件（一命制：存活的只剩 1 人即结束，全员出局也算结束）。"""
        if self.phase != 'playing':
            return
        if len(self.snakes) > 1 and self.alive_count() <= 1:
            self.finish()
            return
        if self.elapsed > 4 * 60 * 1000:
            self.finish()

    def finish(self) -> None:
        """结算本局：最后存活者获胜（全员出局时按分数定冠军），并广播 over。"""
        if self.phase == 'over':
            return
        self.phase = 'over'
        self.room.state = 'over'
        rows = [{
            'pid': s['pid'], 'name': s['name'], 'score': s['score'], 'kills': s['kills'],
            'lives': self.lives.get(s['pid'], 0), 'alive': s['alive'], 'color': s['color'],
        } for s in self.snakes]
        rows.sort(key=lambda r: (-r['score'], -r['kills']))
        last = next((r for r in rows if r['alive']), None)
        if last:
            last['win'] = True
        self.room.last_result = rows
        self.room.service.leaderboard.match(
            [{'name': r['name'], 'score': r['score'], 'kills': r['kills'], 'win': bool(r.get('win'))} for r in rows])
        self.room.broadcast({
            't': 'over', 'round': self.round, 'result': rows,
            'draw': not any(r.get('win') for r in rows),
            'totals': [{
                'name': p['name'],
                'score': next((s['score'] for s in self.snakes if s['pid'] == p['id']), 0),
                'kills': next((s['kills'] for s in self.snakes if s['pid'] == p['id']), 0),
                'color': p['color'],
            } for p in self.room.players],
            'canRematch': True,
        })
        self.room.service.log('房间 %s 第 %d 局结束，冠军 %s' % (
            self.room.code, self.round,
            next((r['name'] for r in rows if r.get('win')), '-')))
        # 联机成绩自动入库 + 回放入库（名称固定为玩家 IP，同分只留更早的一条）
        try:
            self.room.service.publish_online_result(self.room, self)
        except Exception as e:  # 入榜失败不能影响对局结算与房间流程
            self.room.service.log('联机成绩入榜失败：%s' % e, 'warn')

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
