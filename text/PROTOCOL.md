# 协议说明（Play With Snake v3.1.0）

## 端口

| 用途 | 端口 | 说明 |
|---|---|---|
| HTTP | 8080 | 页面分发（`/`）、REST 接口、面板（`/panel`） |
| WebSocket | 8081 | 权威对局协议（QWebSocketServer） |
| UDP | 41999 | 内网自动发现广播 |

浏览器玩家直接访问 `http://<服务器IP>:8080/` 即可；桌面客户端通过 Python 持有与 8081 的连接。

## HTTP 接口

| 路径 | 方法 | 说明 |
|---|---|---|
| `/`、`/index.html` | GET | 返回客户端页面（局域网浏览器即用即玩） |
| `/version.js` | GET | 页面版本信息（构建时生成） |
| `/panel` | GET | 服务器面板（仅访问密码与排行榜） |
| `/health` | GET | `{ok, v, wsPort}` |
| `/api/discover` | GET | 内网发现响应：`{ok, app:'snake-lan-server', name, version, port, wsPort, rooms, players, online, host}` |
| `/api/maps` | GET | `{ok, maps:[{id,name,cols,rows,custom}]}` |
| `/api/map` | GET | `?id=` 取单张自制地图完整数据 |
| `/api/map` | POST | 上传自制地图（见下） |
| `/api/online-board` | GET | 联机排行榜前 30 条，每条附 `ip` 与 `note` |
| `/api/rank` | POST | 提交联机成绩（需签名，异常数据返回 400） |
| `/api/solo-score` | POST | 提交单机成绩 `{name,score,length}` |
| `/api/auth/status` | GET | `{ok, enabled, authed}` |
| `/api/auth/login` | POST | `{password}`，成功下发 `snake_panel` Cookie |
| `/api/auth/set` | POST | `{oldPassword,newPassword}`（空字符串表示清除） |
| `/api/auth/logout` | POST | 清除会话 |
| `/api/leaderboard` | GET | 玩家统计前 30（需登录） |

所有 `/api/*` 均带 `Access-Control-Allow-Origin: *` 与 `OPTIONS 204`。

## 成绩签名

客户端与服务端共用的 FNV-1a 变体（密钥 `snake-magic-2026-v3`），字段顺序：

```
mode # diff # players(|) # scores(,) # levels(,) # lens(,) # duration # mapId
```

输出 8 位小写十六进制。服务端会重算并与上报的 `sig` 比对，不一致即视为异常数据并剔除。
实现见 `shared/protocol.py`（Python）与 `client/web/index.html` 的 `snakeSig()`（JS）。

## WebSocket 消息

所有消息统一使用 `t` 字段（文本帧 JSON）。

### 客户端 → 服务端

| t | 字段 | 说明 |
|---|---|---|
| `name` | `name` | 自报昵称（连接后自动发送，非必填步骤） |
| `lobby` | — | 请求大厅房间列表 |
| `leaderboard` | — | 请求玩家统计 |
| `create` | `name,maxPlayers,map,diff,password,isPublic` | 开房 |
| `join` | `code,name,password,spectate` | 加入/观战 |
| `leave` | — | 离开房间 |
| `ready` | `ready` | 准备状态 |
| `start` | — | 房主开始 |
| `settings` | `maxPlayers,map,diff,password,isPublic` | 房主改设置 |
| `dir` | `x,y` | 方向指令（±1） |
| `rematch` | — | 再来一局投票 |
| `rematchInvite` | — | 房主邀请上一局玩家 |
| `toLobby` | — | 房主结束对局回房间 |
| `solo` | `name,score,length` | 单机成绩上报 |
| `rank` | `rec` | 联机成绩上报（含 sig） |
| `ping` | `ts` | 心跳 |

### 服务端 → 客户端

| t | 字段 | 说明 |
|---|---|---|
| `hello` | `name,maps,diffs,lb,wsPort,httpPort` | 连接即下发（地图含自制图） |
| `me` | `name,stats` | 昵称确认 |
| `lobby` | `rooms,online,playing,matches` | 大厅概览 |
| `lb` | `top` | 玩家统计前 30 |
| `ob` | `top` | 联机排行榜前 30 |
| `room` | `room,self,players,spectators,readyCount` | 个性化房间快照 |
| `roomUpdate` | `room` | 他人房间变更 |
| `sys` | `msg` | 房间系统提示 |
| `err` | `msg,needPass,code,canSpectate` | 错误 |
| `start` | `round,by,map,diff,cols,rows,players` | 开局 |
| `state` | `s,events` | 权威快照（按配置频率） |
| `over` | `round,result,totals,canRematch` | 结算 |
| `toLobby` | — | 回到房间 |
| `left` | — | 已离开 |
| `invite` | `from,names,code,mapName,diffName,hasPass` | 邀请 |
| `rankSaved` / `soloSaved` | `msg` / `score` | 成绩已保存 |
| `pong` | `ts` | 心跳回应 |

### 快照 `state.s`

```json
{
  "phase": "countdown|playing|over",
  "cd": 3,
  "cols": 48, "rows": 36,
  "tick": 120,
  "map": "classic",
  "diff": "普通",
  "elapsed": 12,
  "snakes": [{"pid":1,"name":"甲","color":"#34e39b","alive":true,
              "body":[{"x":24,"y":18}],"score":30,"kills":0,"lives":3,
              "dir":{"x":1,"y":0}}],
  "foods": [{"x":10,"y":8,"k":1}],
  "powers": [{"x":5,"y":5,"k":"speed","life":200}],
  "effects": {"1": {"speed":60,"slow":0,"ghost":0,"shield":0,"portal":0}},
  "obstacles": [{"x":12,"y":12}],
  "lives": {"1": 3}
}
```

- 食物 `k`：1 普通（+10 分，蛇身 +3 节）、2 金星（+30 分，额外 +2 节）。
- 道具 `k`：`speed` / `slow` / `shield` / `ghost`，效果以 tick 计（60 tick ≈ 1 秒）。
- 护盾为可叠加层数（客户端状态栏显示 x1、x2…）。

### 自制地图上传

```json
{
  "id": "m1",
  "name": "演示地图",
  "author": "作者名",
  "mode": "single|duel",
  "cols": 20, "rows": 20,
  "walls": [[3,3],[3,4]],
  "wallPass": false
}
```

服务端校验：id 仅字母数字下划线短横线（≤32）、不得与经典地图冲突、尺寸 8–60、墙体在界内且不超过格子总数的 45%、最多 200 张。
