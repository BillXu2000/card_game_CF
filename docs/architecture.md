# 架构（阶段 5b）

```
浏览器 (static/)                       服务端 (cardgame/)
┌──────────────────────┐   WebSocket   ┌────────────────────────────────────┐
│ main.js  登录/大厅/房间 │ ◄──────────► │ server/app.py    协议、广播、在线状态 │
│ games/<id>.js 牌桌渲染  │   JSON 消息   │ server/rooms.py  房间、座位、历史、AI │
│ games/generic.js 兜底  │              │ server/auth.py   用户、密码、token    │
└──────────────────────┘               │ engine/          通用底层             │
                                       │ games/<id>/      各游戏规则与 AI      │
                                       └────────────────────────────────────┘
```

## 1. 通用底层 `cardgame/engine`

### GameState（`state.py`）

一局游戏的全部状态，可完整转为 JSON（`to_dict` / `from_dict`）：

| 字段 | 含义 |
|---|---|
| `cards` | 每张牌的静态属性（`{"suit":"S","rank":12}`、`{"city":"北京","province":"直辖市"}` …），以整数 id 区分 |
| `zones` | 牌区：有序的牌 id 列表 + 所有者 + 可见性 |
| `props` | 每张牌的动态属性（如强买牌已翻面），随牌一起显示 |
| `known` | 额外知情者：某张牌所在牌区本应隐藏，但某些座位见过它（如传出的牌） |
| `vars` | 公开的游戏变量（阶段、轮到谁、分数、出牌历史…） |
| `private` | 每个座位一份私有变量，只发给该座位 |
| `log` | 日志，可限定只给某些座位看 |
| `rng` | 随机数生成器状态。导入/回退后，后续洗牌结果完全一致 |
| `seq` | 已执行的动作数 |

牌区可见性：`public`（所有人可见）、`owner`（仅所有者可见，其他人只看到张数）、`hidden`（无人可见，如牌堆）。

**遮蔽**：`view(seat)` 生成某座位的视图。看不到的牌在牌区列表中是 `null`，`cards` 中也不出现它的属性，所以客户端拿不到任何隐藏信息（包括牌 id）。旁观者 `seat=None` 只看公开信息。

### Game（`game.py`）

规则模块是无状态对象，需实现：

```python
setup(st)                     # 建牌区、建牌、洗牌、发牌
prompts(st) -> {seat: prompt} # 当前哪些座位要做什么决定（可多人同时）
apply(st, seat, action)       # 校验并执行；不合法则抛 IllegalAction（执行前先校验）
is_over(st)
make_ai() -> AI               # AI.choose(view, prompt) -> action，只拿到遮蔽后的视图
```

可选：`option_specs`（房间选项，开局前房主可改）、`static_info`（发给前端的常量数据，如 Pattern 表）、`view`（在通用遮蔽基础上加工）、`ai_delay`（AI 出手节奏）、`describe`（历史记录的文字）。

日志中的 `{P0}`、`{P1}`… 由前端替换为玩家名字。

“谁该行动”由 `prompts` 从状态推导，不单独保存，所以任何快照都能直接继续游戏。多人同时决策（红心大战传牌）和响应窗口（城市交易所的点炮：一次弃牌后，所有可能点炮的玩家同时得到“点炮/不点”的提示）用同一机制表达。

## 2. 服务端 `cardgame/server`

- **auth**：首次登录即注册，scrypt 存储密码哈希，密码可空。登录后发 token，浏览器存在 localStorage，刷新页面自动 `resume`。
- **rooms**：房间 = 游戏 + 座位（人 / AI / 空）+ 当前状态 + 历史。
  - 每个动作在状态副本上执行，成功后替换，失败不影响原状态。
  - 每个动作后存一份快照（追加到 `data/rooms/<房号>.history.jsonl`），当前状态存 `data/rooms/<房号>.json`。服务器重启后恢复。
  - 回退 = 用历史快照替换当前状态并截断之后的历史。导入 = 追加一条“导入”快照。
  - AI：轮到 AI 时按 `ai_delay` 延时后出手；延时期间状态如有变化（人类出牌、回退）会重新判断。
- **app**：aiohttp。HTTP 只提供静态文件，其余都走 `/ws`。每次房间变化，向房间内每个连接分别推送它自己座位的视图和提示。
- **聊天**：存在房间里（`room.chat`，随房间存盘），和游戏状态无关。进入房间时发一次全部记录（`chat` 消息带 `reset`），之后每条新消息单独推送给正在看这个房间的连接，不会重绘牌桌。

## 3. 前端 `cardgame/static`

原生 ES 模块，无构建步骤。`main.js` 负责连接、登录、大厅、房间外框（座位、房主工具）。牌桌由 `games/<游戏id>.js` 的 `render(el, ctx)` 绘制，没有专门渲染器的游戏用 `generic.js`（列出所有牌区、变量、提示，可发送原始动作）。

## 4. 各游戏如何映射到底层

### 红心大战

| 底层概念 | 用法 |
|---|---|
| 牌 | 52 张，`{"suit","rank"}` |
| 牌区 | `deck`(hidden)、`hand:i`(owner)、`pass:i`(owner，已选待传的牌)、`trick`(public)、`won:i`(public) |
| 同时决策 | 传牌阶段四人同时有 `pass` 提示 |
| known | 传出的牌对传出者保持可见 |
| vars | 阶段、局数、传牌方向、轮到谁、红心是否已破、本局每墩记录、总分与历史 |

### 城市交易所（`games/city`）

| 规则元素 | 用法 |
|---|---|
| 牌 | 96 张城市牌 `{"kind":"city","city","province"}`，强买/周游列国 `{"kind":"buy"/"tour"}` |
| 牌区 | `deck`(hidden)、`hand:i`(owner)、`special:i`(public)、`discard:i`(public)、`removed`(public) |
| 翻面 | `props` 中的 `used: true` |
| 货币 | `vars.money[i]` |
| 摸牌阶段 | 摸 3 张（记在摸牌者的 `private.drawn`）后提示“从这 3 张中选一张弃置”或直接兑现 |
| 出牌阶段 | 一个 `main` 提示，列出当前可做的兑现、可回购的牌、可强买的牌、能否出游；每回合次数记在 `vars.used` |
| 点炮 | 每次弃牌在 `vars.offers` 里登记一个点炮机会，不改变阶段；能点炮的玩家的提示里多出 `claims`（没有别的事要做时提示类型为 `dianpao`），可随时回答，先到先结算；回合结束时清空。弃牌后 `vars.hold_until`（3 秒）和长考 `vars.think`（`until` 为 `None` 表示不限时，上限是房间选项）期间规则只接受点炮；时间用服务器时钟（`rules.now`，测试中替换），视图里换成剩余秒数 `hold`，客户端据此倒计时。AI 的等待由 `Game.ai_wait` 给出（不随 AI 速度缩放；无限长时不排 AI，等人类的下一个动作重新安排）。座位交给 AI 时调用 `Game.ai_takes_over`，城市交易所借此结束该座位的长考。`offers` 不出现在视图里，`Game.waiting` 只列正常流程该行动的人 |
| 桌面显示 | `vars.played[i]`：座位 i 从自己回合开始以来放到桌上的牌，按组记录（弃置 / 出游弃置 / 兑现 / 点炮，带 Pattern），该座位下一个回合开始时清空；`vars.events`：本回合的兑现、点炮、强买、回购、出游罚款及各自的金额变化 `[[座位, 金额]]`，每回合开始时清空。金额变化的飘字由前端比较前后两个视图得到 |
| 出游 | `tour` 阶段，按顺序逐人提示“弃一张手牌或付 6 元” |
| 斗地主 | 农民共用弃牌区（一个 `discard:farmers` 牌区）；背面交牌 = 移到对方手牌并对自己保持 known |
| 角色技能 | 规则模块内的钩子（兑现前后、弃牌后、回合开始/结束），技能状态存在 `vars` |

### 骗人游戏（`games/liar`）

| 规则元素 | 用法 |
|---|---|
| 牌 | 每副 52 张 `{"suit","rank"}` 加王 `{"joker": true, "color"}` |
| 牌区 | `deck`(hidden，只用于发牌)、`hand:i`(owner)、`claim`(hidden，最新声明的牌)、`table`(hidden，本轮更早的牌)、`discard`(hidden) |
| 打出的牌 | 进 `claim` 时打乱顺序，清除所有人的 known，只对出牌者保持 known（背面混在一起后谁也认不出来） |
| 质疑 | 翻开的牌对所有人 known；`claim`+`table` 全部移到输家手里 |
| vars | 阶段（`lead` 定数字并出牌 / `play` / `over`）、轮数、x、轮到谁、本轮各人是否 pass、本轮声明列表、出完顺序、上一轮怎么结束的（给界面展示） |
