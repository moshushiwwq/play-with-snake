"""WebSocket 消息分发：完整复刻原 Node 版 handleMsg 的全部 case。

消息统一以 `t` 字段区分；字段名与服务端返回结构与旧版保持一致，
因此既有客户端页面无需改动协议即可工作。
"""
from __future__ import annotations

import json

from shared.constants import MAX_ROOMS
from server.core.room import Room, hash_pass
from server.core.util import clean_name


def handle_message(service, conn, text: str) -> None:
    """解析并处理一条客户端消息。

    Args:
        service: GameService。
        conn: 来源连接（需含 id/name/ip/room/role/closed/send/last_solo_submit）。
        text: 原始 JSON 文本。
    """
    try:
        m = json.loads(text)
    except Exception:
        return
    if not isinstance(m, dict) or not isinstance(m.get('t'), str):
        return

    t = m['t']

    if t == 'name':
        conn.name = clean_name(m.get('name'), '玩家')
        old = service.leaderboard.get(conn.name)
        e = service.leaderboard.entry(conn.name)
        if conn.ip:
            e['ip'] = conn.ip
        conn.send({'t': 'me', 'name': conn.name, 'stats': old})
        service.broadcast_lobby()
        return

    if t == 'lobby':
        conn.send({
            't': 'lobby', 'rooms': service.public_rooms(), 'online': len(service.conns),
            'playing': service.player_count(), 'matches': service.match_count(),
        })
        return

    if t == 'leaderboard':
        conn.send({
            't': 'lb', 'top': service.leaderboard.top(30),
            'me': service.leaderboard.get(conn.name) if conn.name else None,
        })
        return

    if t == 'create':
        if conn.room is not None:
            conn.send({'t': 'err', 'msg': '你已经在房间里了（每人同时只能开/加入一个房间）'})
            return
        if len(service.rooms) >= MAX_ROOMS:
            conn.send({'t': 'err', 'msg': '服务器房间已达上限'})
            return
        settings = {
            'maxPlayers': max(2, min(4, _int(m.get('maxPlayers'), 4))),
            'map': str(m.get('map') or 'classic'),
            'diff': str(m.get('diff') or 'normal'),
            'password': str(m.get('password') or '')[:12],
            'isPublic': m.get('isPublic') is not False,
        }
        # 地图必须存在（经典或已上传的自制图），否则回落经典
        valid_ids = {x['id'] for x in service.map_list()}
        if settings['map'] not in valid_ids:
            settings['map'] = 'classic'
        if settings['diff'] not in service.diffs:
            settings['diff'] = 'normal'
        room = Room(service, conn, settings)
        if not room.code:
            conn.send({'t': 'err', 'msg': '房间号分配失败，请重试'})
            return
        service.rooms[room.code] = room
        conn.name = clean_name(m.get('name') or conn.name, '房主')
        room.add_player(conn, conn.name)
        room.send_room(conn)
        service.broadcast_lobby()
        service.log('房主 %s 开房 %s（%d人 / %s / %s%s）' % (
            conn.name, room.code, settings['maxPlayers'], room.map_def()['name'],
            service.diffs[settings['diff']]['name'], ' / 有密码' if settings['password'] else ''))
        return

    if t == 'join':
        if conn.room is not None:
            conn.send({'t': 'err', 'msg': '你已经在房间里了'})
            return
        code = str(m.get('code') or '').strip().upper()
        room = service.rooms.get(code)
        if room is None:
            conn.send({'t': 'err', 'msg': '房间不存在或已解散'})
            return
        if room.pass_hash and hash_pass(m.get('password') or '') != room.pass_hash:
            conn.send({'t': 'err', 'msg': '房间密码错误', 'needPass': True, 'code': code})
            return
        conn.name = clean_name(m.get('name') or conn.name, '玩家')
        as_spectator = bool(m.get('spectate')) or room.is_full
        if as_spectator and not m.get('spectate'):
            conn.send({'t': 'err', 'msg': '房间已满（%d/%d），可切换为观战' % (
                len(room.players), room.settings['maxPlayers']), 'canSpectate': True})
            return
        if as_spectator:
            room.spectators.append({'id': conn.id, 'conn': conn, 'name': conn.name})
            conn.room = room
            conn.role = 'spectator'
            room.send_room(conn)
            room.broadcast({'t': 'sys', 'msg': conn.name + ' 进入观战'})
            if room.game is not None:
                conn.send({'t': 'state', 's': room.game.snapshot(), 'events': []})
        else:
            if room.state == 'playing':
                conn.send({'t': 'err', 'msg': '本局已开始，可切换为观战', 'canSpectate': True})
                return
            room.add_player(conn, conn.name)
            room.send_room(conn)
            room.broadcast({'t': 'sys', 'msg': conn.name + ' 加入了房间'})
            room.try_auto_start()
            if room.last_result:
                others = [r['name'] for r in room.last_result if r['name'] != conn.name]
                conn.send({'t': 'invite', 'from': '上一局', 'names': others, 'code': room.code})
        service.broadcast_lobby()
        service.log('%s 加入房间 %s%s' % (conn.name, code, '（观战）' if as_spectator else ''))
        return

    if t == 'leave':
        if conn.room is None:
            return
        room = conn.room
        kind = room.remove_by_conn(conn)
        conn.room = None
        conn.role = None
        if kind == 'player':
            room.broadcast({'t': 'sys', 'msg': (conn.name or '玩家') + ' 离开了房间'})
            if room.host_id == conn.id and room.players:
                room.host_id = room.players[0]['id']
                room.broadcast({'t': 'sys', 'msg': room.players[0]['name'] + ' 成为新房主'})
        if not room.players and not room.spectators:
            service.rooms.pop(room.code, None)
            service.log('房间 %s 已解散（无人）' % room.code)
        else:
            room.send_room()
            room.try_auto_start()
        conn.send({'t': 'left'})
        service.broadcast_lobby()
        return

    if t == 'ready':
        room = conn.room
        if room is None or conn.role != 'player':
            return
        p = next((x for x in room.players if x['conn'] is conn), None)
        if p:
            p['ready'] = bool(m.get('ready'))
        room.send_room()
        room.try_auto_start()
        return

    if t == 'start':
        room = conn.room
        if room is None:
            return
        if room.host_id != conn.id:
            conn.send({'t': 'err', 'msg': '只有房主可以开始游戏'})
            return
        r = room.start_game(conn.name)
        if not r.get('ok'):
            conn.send({'t': 'err', 'msg': r.get('msg')})
        return

    if t == 'settings':
        room = conn.room
        if room is None:
            return
        if room.host_id != conn.id:
            conn.send({'t': 'err', 'msg': '只有房主可以修改房间设置'})
            return
        if room.state == 'playing':
            conn.send({'t': 'err', 'msg': '对局中不能修改设置'})
            return
        if m.get('maxPlayers'):
            room.settings['maxPlayers'] = max(
                len(room.players), max(2, min(4, _int(m.get('maxPlayers'), 4))))
        valid_ids = {x['id'] for x in service.map_list()}
        if m.get('map') and str(m['map']) in valid_ids:
            room.settings['map'] = str(m['map'])
        if m.get('diff') and str(m['diff']) in service.diffs:
            room.settings['diff'] = str(m['diff'])
        if isinstance(m.get('isPublic'), bool):
            room.settings['isPublic'] = m['isPublic']
        if isinstance(m.get('password'), str):
            room.settings['password'] = m['password'][:12]
            room.pass_hash = hash_pass(m['password']) if m['password'] else None
        room.send_room()
        service.broadcast_lobby()
        room.broadcast({'t': 'sys', 'msg': '房主更新了房间设置'})
        return

    if t == 'dir':
        room = conn.room
        if room is None or room.game is None or room.game.phase != 'playing':
            return
        try:
            dx, dy = int(m.get('x', 0)), int(m.get('y', 0))
        except Exception:
            return
        if abs(dx) + abs(dy) != 1:
            return
        room.game.input(conn.id, dx, dy)
        return

    if t == 'rematch':
        room = conn.room
        if room is None or conn.role != 'player':
            return
        if room.state != 'over' and not (room.game is not None and room.game.phase == 'over'):
            return
        room.rematch_votes.add(conn.id)
        needed = len(room.players)
        room.broadcast({'t': 'sys', 'msg': '%s 想再来一局（%d/%d）' % (
            conn.name, len(room.rematch_votes), needed)})
        if len(room.rematch_votes) >= needed:
            room.game = None
            room.start_game('全员再来一局')
        else:
            room.send_room()
        return

    if t == 'rematchInvite':
        room = conn.room
        if room is None or room.host_id != conn.id:
            conn.send({'t': 'err', 'msg': '只有房主可以发起邀请'})
            return
        names = [r['name'] for r in (room.last_result or [])
                 if not any(p['name'] == r['name'] for p in room.players)]
        if not names:
            conn.send({'t': 'err', 'msg': '上一局的人都在房间里了'})
            return
        sent = 0
        for c in list(service.conns):
            if getattr(c, 'room', None) is not None:
                continue
            if c.name in names:
                c.send({
                    't': 'invite', 'from': conn.name, 'names': names, 'code': room.code,
                    'mapName': room.map_def()['name'],
                    'diffName': service.diffs[room.settings['diff']]['name'],
                    'hasPass': bool(room.pass_hash),
                })
                sent += 1
        conn.send({'t': 'sys', 'msg': ('已向 %d 位玩家发送邀请' % sent) if sent
                   else '没有找到在线的上一局玩家（他们可能已关闭页面）'})
        return

    if t == 'toLobby':
        room = conn.room
        if room is None or room.host_id != conn.id:
            return
        room.end_game(True)
        return

    if t == 'solo':
        import time
        now = time.time()
        if now - getattr(conn, 'last_solo_submit', 0) < 1.5:
            return
        conn.last_solo_submit = now
        name = clean_name(m.get('name') or conn.name, '玩家')
        try:
            score = max(0, min(1000000, int(m.get('score') or 0)))
        except Exception:
            score = 0
        if score > 0:
            service.leaderboard.solo(name, score, int(m.get('length') or 0), conn.ip)
            service.broadcast_all({'t': 'lb', 'top': service.leaderboard.top(30)})
            conn.send({'t': 'soloSaved', 'score': score, 'open': True})
        return

    if t == 'rank':
        r = service.online_board.submit(m.get('rec') or {}, conn.ip)
        if not r.get('ok'):
            conn.send({'t': 'err', 'msg': r.get('msg')})
            service.log('过滤异常数据（签名不符）：%s 来源 %s' % (
                (m.get('rec') or {}).get('name') or '-', conn.ip), 'warn')
        else:
            service.broadcast_all({'t': 'ob', 'top': service.online_board.top(30)})
            conn.send({'t': 'rankSaved', 'ok': True, 'msg': r.get('msg')})
        return

    if t == 'ping':
        conn.send({'t': 'pong', 'ts': m.get('ts')})
        return


def _int(value, default: int = 0) -> int:
    """安全转整数（非数字输入回落到默认值，避免畸形消息导致崩溃）。

    Args:
        value: 原始值。
        default: 转换失败时的返回值。

    Returns:
        整数。
    """
    try:
        return int(value)
    except Exception:
        return default
