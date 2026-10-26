// 城市交易所 table, laid out like a card table: the map of China is only the
// cloth, its cities fitted into the free middle.  The other players sit round
// the edge (left, top, right), you at the bottom; the cards each player put
// out since their turn began lie on the table in front of them.  A column on
// the right holds whose turn it is, this turn's cash / 点炮 / money changes,
// the deck and the discards, and the log; the map legend and Pattern
// reference open from its top.
import { pileEl } from "../cards.js";
import {
  dropRedrawnHovers, fitMap, focusCities, hoverCity, hoverPattern, mapBackground, mapCaption, mapLegend, onFocusChange,
} from "./city_map.js";

const PROVINCE_CLASS = { "直辖市": "pv-m", "江苏": "pv-js", "湖北": "pv-hb", "四川": "pv-sc", "广东": "pv-gd" };
const CAPITALS = new Set(["南京", "武汉", "成都", "广州"]);
const POS = { 3: ["bottom", "left", "right"], 4: ["bottom", "left", "top", "right"] };
const MONEY_FX_MS = 4000;   // how long a money change stays marked at the player

// keep the map fitted when the table changes size
let fitTarget = null;
const resizer = typeof ResizeObserver === "undefined" ? null
  : new ResizeObserver(() => { if (fitTarget) fitMap(...fitTarget); });

// pattern reference panel state (kept for the whole session)
const patternUi = { open: false, all: false };

// UI state kept between renders (reset when the prompt changes)
let ui = { key: null, mode: null, picked: new Set(), selected: null, claims: {} };

// After a discard only 点炮 is allowed for a few seconds, longer while someone
// 长考s.  The server sends the seconds left; they count down from when each
// view arrived, the countdowns tick in place and the table is redrawn when one
// runs out.
const viewTime = new WeakMap();
let holdTimer = null;
let lastCtx = null;
setInterval(() => {
  for (const e of document.querySelectorAll(".c-countdown[data-until]")) {
    e.textContent = Math.max(0, Math.ceil((+e.dataset.until - performance.now()) / 1000));
  }
}, 250);

function holdInfo(view, me) {
  if (!viewTime.has(view)) viewTime.set(view, performance.now());
  const h = view.hold;
  const at = viewTime.get(view);
  const until = (left) => left == null ? Infinity : at + left * 1000;   // null: no time limit
  const wait = h && until(h.left) > performance.now() ? until(h.left) : null;
  const think = h?.think && until(h.think.left) > performance.now() ? { seat: h.think.seat, until: until(h.think.left) } : null;
  // when non-点炮 moves are allowed again, for this player
  const free = Math.max(wait ?? 0, think && think.seat !== me ? think.until : 0);
  return { wait, think, blocked: free > performance.now(), free, limit: h?.think_time ?? 0,
    canThink: !!h?.can_think && !(think && think.seat !== me) };
}

function countdown(until) {
  const e = span("c-countdown", String(Math.ceil((until - performance.now()) / 1000)));
  e.dataset.until = until;
  return e;
}

// Money changes are found by comparing each new view with the previous one;
// the change is shown next to the player's money for a few seconds (repeated
// changes add up).
const moneyFx = { code: null, view: null, money: null, fx: {} };
function trackMoney(ctx) {
  const money = ctx.view.vars.money;
  if (moneyFx.view === ctx.view) return;
  const t = performance.now();
  if (moneyFx.code === ctx.room.code && moneyFx.money?.length === money.length) {
    money.forEach((m, i) => {
      const d = m - moneyFx.money[i];
      if (!d) return;
      const old = moneyFx.fx[i];
      moneyFx.fx[i] = { delta: d + (old && t - old.at < MONEY_FX_MS ? old.delta : 0), at: t };
    });
  } else moneyFx.fx = {};
  Object.assign(moneyFx, { code: ctx.room.code, view: ctx.view, money: [...money] });
}

export function render(el, ctx) {
  const { view, prompt } = ctx;
  const v = view.vars;
  const n = view.num_players;
  const me = ctx.seat;
  // other players act in parallel (点炮), so selections survive their moves and
  // only reset when this player's own step changes
  const used = v.used ? `${+v.used.cash}${+v.used.buy}${+v.used.buyback}` : "";
  const key = `${v.turn_no}:${v.phase}:${v.tour?.idx ?? ""}:${prompt?.type}:${used}`;
  if (key !== ui.key) ui = { key, mode: null, picked: new Set(), selected: null, claims: ui.claims };
  // leave a buy/buy-back mode once that action is no longer offered
  if ((ui.mode === "buy" && !prompt?.buy) || (ui.mode === "buyback" && !prompt?.buyback?.length)) {
    ui.mode = null;
    ui.picked = new Set();
  }
  const open = new Set((prompt?.claims ?? []).map((c) => c.offer));
  for (const id of Object.keys(ui.claims)) if (!open.has(+id)) delete ui.claims[id];
  const rerender = () => render(el, ctx);
  const hold = holdInfo(view, me);
  lastCtx = ctx;
  clearTimeout(holdTimer);
  const next = [hold.wait, hold.think?.until].filter((t) => t != null && t !== Infinity);
  if (next.length) {
    holdTimer = setTimeout(() => { if (lastCtx === ctx) rerender(); }, Math.min(...next) - performance.now() + 30);
  }
  trackMoney(ctx);
  // 点炮 options appear only once the player has 长考'd on that discard (so
  // everybody sees the same 长考 button); offers on earlier discards, which
  // can no longer be 长考'd, show directly
  const windowCards = new Set(v.window?.cards ?? []);
  const claims = (prompt?.claims ?? []).filter((c) =>
    v.window?.thought.includes(me) || !c.cards.some((id) => windowCards.has(id)));
  const name = (i) => ctx.seatName(i);
  const card = (id) => view.cards[id];
  const info = ctx.room.static;
  const cityOrder = Object.values(info.provinces).flat();
  const patternOf = Object.fromEntries(info.patterns.map((p) => [p.id, p]));
  const inDiscards = new Set([...new Set(v.discard_of)].flatMap((z) => view.zones[z].cards));

  const nameTag = (i) => span("c-who", name(i));
  const patTag = (p) => {
    const t = span("c-pat", p?.name ?? "?");
    if (p) {
      t.onmouseenter = () => hoverPattern(p.id);
      t.onmouseleave = () => hoverPattern(null);
    }
    return t;
  };

  dropRedrawnHovers();
  el.className = "game city";
  el.innerHTML = "";
  const felt = div(`city-table n${n}`);
  el.append(felt);
  // on a wide screen the table fills the window below the room header
  el.parentElement?.classList.add("fit");
  el.parentElement?.style.setProperty("--fit-top", `${Math.max(0, el.getBoundingClientRect().top + scrollY)}px`);
  const held = new Set(me != null ? view.zones[`hand:${me}`].cards.map((id) => card(id).city) : []);
  felt.append(mapBackground(info, held));
  tableEl = el;
  const surface = div("c-surface");   // the table top; the map is fitted to it
  const side = div("c-side");         // log, legend, Pattern reference
  felt.append(surface, side);

  // ---- the other players round the table
  const base = me ?? 0;
  const pileShownBy = {};
  for (let k = 1; k < n; k++) {
    const i = (base + k) % n;
    const pod = div(`c-pod c-${POS[n][k]}`);
    pod.append(seatBox(i), playedEl(i));
    surface.append(pod);
  }

  function seatBox(i) {
    const box = div("c-seat" + (v.turn === i && v.phase !== "over" ? " turn" : ""));
    const head = div("c-head");
    head.append(span("c-name", name(i)));
    if (hold.think?.seat === i) head.append(span("c-thinking", "长考中"));
    else if (ctx.room.waiting.includes(i) && v.turn !== i) head.append(span("c-thinking", "思考中"));
    if (v.turn === i && v.phase !== "over") head.append(span("c-turn-tag", "回合中"));
    if (v.landlord != null) head.append(span("c-role " + (i === v.landlord ? "lord" : "farmer"), i === v.landlord ? "地主" : "农民"));
    head.append(moneyEl(i));
    box.append(head);

    // other players' hands: card backs, plus cards everybody saw them take;
    // then the special cards
    const row = div("c-row");
    if (i !== me) {
      const hand = div("c-backs");
      const ids = view.zones[`hand:${i}`].cards;
      for (const id of ids) hand.append(id == null ? back() : miniCard(card(id), "known"));
      row.append(hand, span("c-count", ids.length ? `${ids.length} 张` : "无手牌"));
    }
    const spZone = view.zones[v.special_of[i]];
    if (spZone.owner == null && spZone.cards.length) row.append(span("c-label", "共用"));
    for (const id of spZone.cards) {
      const c = card(id);
      const s = div(`c-sp ${c.kind}` + (c.used ? " used" : ""));
      s.textContent = c.kind === "tour" ? "周游列国" : "强买";
      s.title = c.used ? "已使用（翻面）" : "可以使用";
      row.append(s);
    }
    box.append(row);

    // discard pile
    const zone = v.discard_of[i];
    const pile = div("c-pile");
    if (zone in pileShownBy) {
      pile.append(span("c-label", `与 ${name(pileShownBy[zone])} 共用弃牌区`));
    } else {
      pileShownBy[zone] = i;
      const ids = view.zones[zone].cards;
      pile.append(span("c-label", (view.zones[zone].owner == null ? "共用弃牌区" : "弃牌区") + ` ${ids.length} 张`));
      const cards = div("c-pile-cards");
      for (const id of ids) {
        const m = miniCard(card(id));
        if (v.window?.cards.includes(id) || v.last_discard?.card === id) m.classList.add("hot");
        if (ui.mode === "buyback" && prompt?.buyback.includes(id)) {
          m.classList.add("pick");
          m.title = "点击回购这张牌";
          m.onclick = () => { if (!holdInfo(view, me).blocked) ctx.act({ type: "buyback", card: id }); };
        } else if (ui.mode === "buy" && prompt?.buy?.cards.includes(id)) {
          m.classList.add("pick");
          if (ui.picked.has(id)) m.classList.add("picked");
          m.title = "点击选择要强买的牌";
          m.onclick = () => {
            if (ui.picked.has(id)) ui.picked.delete(id);
            else if (ui.picked.size < prompt.buy.max) ui.picked.add(id);
            else ui.picked = new Set([id]);
            rerender();
          };
        }
        cards.append(m);
      }
      if (ids.length) pile.append(cards);
    }
    box.append(pile);
    return box;
  }

  function moneyEl(i) {
    const m = span("c-money", `${v.money[i]} 元`);
    const fx = moneyFx.fx[i];
    const age = fx ? performance.now() - fx.at : Infinity;
    if (age < MONEY_FX_MS) {
      const d = span(`c-delta ${fx.delta > 0 ? "up" : "down"}`, signed(fx.delta));
      // a redraw must not restart the animation
      d.style.animationDelay = m.style.animationDelay = `${-age}ms`;
      m.classList.add(fx.delta > 0 ? "up" : "down");
      m.append(d);
    }
    return m;
  }

  // cards put out since the player's turn began, in groups (a discard, a
  // cashed Pattern, a 点炮 ...)
  function playedEl(i) {
    const box = div("c-played");
    if (v.played?.[i]?.length) {
      box.append(span("c-played-title", v.turn === i && v.phase !== "over" ? "本回合" : "上一轮事件"));
    }
    for (const g of v.played?.[i] ?? []) {
      const grp = div(`c-group ${g.type}`);
      const label = div("c-group-label");
      const pat = patternOf[g.pattern];
      if (g.type === "discard") label.append("弃置");
      else if (g.type === "tour") label.append("周游列国 · 弃置");
      else if (g.type === "cash") label.append("兑现 ", patTag(pat), " ", moneyTag(pat.value));
      else if (g.type === "dianpao") label.append("点炮 ", nameTag(g.from), " · ", patTag(pat), " ", moneyTag(Math.floor(pat.value * 2 / 3)));
      grp.append(label);
      const cards = div("c-group-cards");
      const ids = g.type === "dianpao" ? [g.card, ...g.cards] : g.cards;
      for (const id of ids) {
        if (!card(id)) { cards.append(back()); continue; }
        const c = bigCard(card(id));
        c.classList.add("mid");
        if (id === g.card) { c.classList.add("claimed"); c.title += `\n${name(g.from)} 弃的牌`; }
        if (!inDiscards.has(id)) { c.classList.add("gone"); c.title += "\n已被拿走"; }
        else if (v.window?.cards.includes(id)) c.classList.add("hot");
        cards.append(c);
      }
      grp.append(cards);
      box.append(grp);
    }
    return box;
  }

  // ---- the cities of the map show in the free middle of the table
  const mapArea = div("c-maparea");
  mapArea.append(mapCaption());
  surface.append(mapArea);

  // ---- turn, status and this turn's events (top of the right column)
  const centre = div("c-info");
  const turnInfo = div("c-turn");
  turnInfo.textContent = v.phase === "over" ? "游戏结束"
    : v.turn != null ? `第 ${v.turn_no} 回合 · ${name(v.turn)} 的回合` : "";
  centre.append(turnInfo);
  const status = div("status");
  status.textContent = statusText(ctx, v, prompt, name, claims);
  if (hold.think) {
    const who = hold.think.seat === me ? " · 你在长考" : ` · ${name(hold.think.seat)} 长考中`;
    if (hold.think.until === Infinity) status.append(span("c-hold", who));
    else status.append(span("c-hold", who + "，还剩 "), countdown(hold.think.until), span("c-hold", " 秒"));
  } else if (hold.wait) {
    status.append(span("c-hold", " · 刚弃了牌，点炮时间 "), countdown(hold.wait), span("c-hold", " 秒"));
  }
  centre.append(status);
  const events = v.events ?? [];
  if (events.length) {
    const box = div("c-events");
    events.forEach((e, k) => box.append(eventEl(e, k === events.length - 1)));
    centre.append(box);
  }
  if (v.phase === "bid") {
    const focus = div("c-focus");
    focus.append(span("c-label", "翻开的牌（归地主）"));
    const row = div("c-row");
    for (const id of view.zones.bonus.cards) row.append(bigCard(card(id)));
    focus.append(row);
    centre.append(focus);
  }
  const piles = div("c-piles");
  piles.append(pileEl({ label: "牌堆", count: view.zones.deck.cards.length }));
  const last = v.last_discard;
  const lastShown = last && view.cards[last.card] && inDiscards.has(last.card);
  piles.append(discardPile(info, view, v, card, lastShown ? bigCard(card(last.card)) : null));


  function eventEl(e, latest) {
    const d = div(`c-event ${e.type}` + (latest ? " latest" : ""));
    const pat = patternOf[e.pattern];
    const city = (id) => span("c-city", card(id)?.city ?? "?");
    if (e.type === "cash") d.append(nameTag(e.seat), " 兑现 ", patTag(pat));
    else if (e.type === "dianpao") d.append(nameTag(e.seat), " 点炮 ", nameTag(e.from), " 的 ", city(e.card), "：", patTag(pat));
    else if (e.type === "buy") d.append(nameTag(e.seat), " 强买 ", nameTag(e.from), " 的 ", city(e.card));
    else if (e.type === "buyback") d.append(nameTag(e.seat), " 回购 ", city(e.card));
    else if (e.type === "fine") d.append(nameTag(e.seat), " 不弃牌，付钱给 ", nameTag(e.to));
    const money = span("c-event-money", "");
    for (const [s, a] of e.money) money.append(" ", nameTag(s), " ", moneyTag(a));
    if (e.money.length) d.append(money);
    return d;
  }

  // ---- me: seat, the cards I put out, hand and actions
  const mine = div("c-mine");
  mine.append(seatBox(base));
  const col = div("c-mine-col");
  col.append(playedEl(base));
  mine.append(col);
  surface.append(mine);
  if (me != null) {
    const hand = div("my-hand c-hand");
    const handIds = view.zones[`hand:${me}`].cards;
    const drawn = new Set(v.turn === me ? view.private.drawn ?? [] : []);
    const selectable = prompt?.type === "draw" ? (id) => drawn.has(id)
      : prompt?.type === "tour" || prompt?.type === "give" ? () => true : null;
    for (const id of sortCards(handIds, card, cityOrder)) {
      const c = bigCard(card(id));
      c.dataset.id = id;
      if (drawn.has(id)) c.classList.add("new");
      if (selectable) {
        if (selectable(id)) {
          c.classList.add("clickable");
          if (ui.selected === id) c.classList.add("selected");
          c.onclick = () => { ui.selected = ui.selected === id ? null : id; rerender(); };
        } else c.classList.add("dim");
      }
      hand.append(c);
    }
    if (!handIds.length) hand.append(span("c-empty", "没有手牌"));
    col.append(hand);
    const actions = div("c-actions");
    // hovering a Pattern button lifts the hand cards it would use
    const highlight = (patternId) => {
      const ids = patternId ? cardsForPattern(info, patternId, handIds, card) : new Set();
      for (const c of hand.querySelectorAll(".card")) c.classList.toggle("hl", ids.has(+c.dataset.id));
    };
    thinkButtons(actions, ctx, hold);
    buildActions(actions, ctx, prompt, claims, rerender, highlight, hold.blocked);
    if (actions.childElementCount) col.append(actions);
  }

  if (v.phase === "over") surface.append(finalBox(v, name));

  // ---- right column: legend and Pattern reference (they open over the
  // table), the turn, the piles, the log
  const tools = div("c-tools");
  const legend = mapLegend();
  const patterns = patternPanel(info, me != null ? view.zones[`hand:${me}`].cards.map((id) => card(id).city) : [], rerender);
  // one of them open at a time
  legend.ontoggle = () => { if (legend.open && patterns.open) patterns.open = false; };
  patterns.addEventListener("toggle", () => { if (patterns.open && legend.open) legend.open = false; });
  tools.append(legend, patterns);
  side.append(tools, centre, piles, logPanel(view.log, name, info.patterns));

  fadeOtherCities(focusCities());  // something may still be hovered after a re-render
  fitTarget = [felt, mapArea];
  if (resizer) { resizer.disconnect(); resizer.observe(felt); }
  requestAnimationFrame(() => fitMap(felt, mapArea));
}

function signed(a) {
  return (a > 0 ? "+" : "−") + Math.abs(a);
}

function moneyTag(a) {
  return span(a >= 0 ? "c-plus" : "c-minus", `${signed(a)} 元`);
}

function statusText(ctx, v, prompt, name, claims) {
  if (v.phase === "over") return "游戏结束";
  if (prompt?.type === "dianpao" && !claims.length) prompt = null;  // not shown before 长考
  if (prompt) {
    if (prompt.type === "dianpao") return "可以点炮！在下方选择要兑现的 Pattern，或者不点炮";
    const extra = claims.length ? "（另有点炮机会，见下方）" : "";
    return {
      draw: "摸牌阶段：点选一张本回合摸到的牌（蓝框）弃置",
      main: "出牌阶段：可以回购、出游、强买、兑现（顺序随意），然后结束回合",
      tour: prompt.by === ctx.seat
        ? "你的周游列国轮到你自己：点选一张手牌弃置继续，或者不弃（周游列国结束）"
        : `${name(prompt.by)} 发动周游列国：点选一张手牌弃置，或交给 TA ${prompt.fine} 元`,
      bid: "要当地主吗？地主获得中间翻开的牌",
      give: `回合结束：点选一张手牌，背面朝上交给 ${name(prompt.to)}`,
    }[prompt.type] + extra;
  }
  const waiting = ctx.room.waiting.map(name).join("、");
  if (v.phase === "bid") return `等待 ${waiting} 决定是否当地主…`;
  if (v.phase === "give") return `等待 ${name(v.turn)} 交牌…`;
  if (v.phase === "tour") return `周游列国：等待 ${waiting}…`;
  return `等待 ${name(v.turn)} 行动…`;
}

// 长考 is offered to everybody but the discarder, able to 点炮 or not
function thinkButtons(box, ctx, hold) {
  if (hold.think?.seat === ctx.seat) {
    const b = button("结束长考", () => ctx.act({ type: "think_end" }), false, "ghost");
    if (hold.think.until !== Infinity) b.append("（", countdown(hold.think.until), " 秒）");
    box.append(b);
  } else if (hold.canThink) {
    const b = button(hold.limit ? `长考（${hold.limit} 秒）` : "长考", () => ctx.act({ type: "think" }), false, "ghost");
    b.title = "长考后才能选择点炮或不点炮；其间其他人只能点炮，直到你不点炮或结束长考"
      + (hold.limit ? `（最多 ${hold.limit} 秒）` : "");
    box.append(b);
  }
}

// while only 点炮 is allowed (``blocked``), every other move is greyed out
function buildActions(box, ctx, prompt, claims, rerender, highlight, blocked) {
  if (!prompt) return;
  const act = ctx.act;
  const hoverable = (b, pattern) => {
    b.onmouseenter = () => { highlight(pattern); hoverPattern(pattern); };
    b.onmouseleave = () => { highlight(null); hoverPattern(null); };
  };
  // 点炮 offers come first; the rest of the turn goes on independently
  for (const claim of claims) {
    const sel = (ui.claims[claim.offer] ??= new Set());
    const row = div("c-claim");
    const cards = claim.cards.map((id) => ctx.view.cards[id].city).join("、");
    row.append(span("c-claim-title", `点炮！${ctx.seatName(claim.by)} 弃了 ${cards}：`));
    claim.options.forEach((o, i) => {
      const on = sel.has(i);
      const b = button(`${on ? "✓ " : ""}${o.name} +${o.gain}` + (o.cost ? `（弃牌者 −${o.cost}）` : ""), () => {
        on ? sel.delete(i) : sel.add(i);
        rerender();
      }, false, on ? "gold" : "ghost");
      hoverable(b, o.pattern);
      row.append(b);
    });
    // after a 点炮 the options are worked out afresh: start the next pick empty
    row.append(button("兑现所选", () => { act({ type: "dianpao", offer: claim.offer, choices: [...sel] }); sel.clear(); },
      !sel.size));
    row.append(button("不点炮", () => act({ type: "dianpao", offer: claim.offer, choices: [] }), false, "ghost"));
    box.append(row);
  }
  if (prompt.type === "draw") {
    box.append(button("弃置所选", () => act({ type: "discard", card: ui.selected }), ui.selected == null || blocked));
    for (const o of prompt.cash) {
      const b = button(`不弃，直接兑现 ${o.name} +${o.value}`, () => act({ type: "cash", pattern: o.pattern }), blocked, "gold");
      hoverable(b, o.pattern);
      box.append(b);
    }
  } else if (prompt.type === "main") {
    for (const o of prompt.cash) {
      const b = button(`兑现 ${o.name} +${o.value}`, () => act({ type: "cash", pattern: o.pattern }), blocked, "gold");
      hoverable(b, o.pattern);
      box.append(b);
    }
    if (prompt.buyback.length) box.append(modeButton("回购（−10）", "buyback", rerender));
    if (prompt.buy) box.append(modeButton(`强买（−${prompt.buy.price}/张）`, "buy", rerender));
    if (ui.mode === "buy")
      box.append(button(`确认强买 ${ui.picked.size} 张`, () => act({ type: "buy", cards: [...ui.picked] }), !ui.picked.size || blocked));
    if (prompt.tour) box.append(button("出游（周游列国）", () => {
      if (confirm("发动周游列国？其他人依次弃一张牌，第一个不弃的人付你 6 元。")) act({ type: "tour" });
    }, blocked));
    box.append(button("结束回合", () => act({ type: "end" }), blocked, "ghost"));
    if (ui.mode) box.append(span("c-hint", ui.mode === "buy"
      ? `点击桌上弃牌区里要买的牌（黄色虚线框，最多 ${prompt.buy.max} 张），钱付给弃这张牌的人`
      : "点击你弃牌区里要收回的牌（黄色虚线框）"));
  } else if (prompt.type === "tour") {
    box.append(button("弃置所选", () => act({ type: "tour", card: ui.selected }), ui.selected == null || blocked));
    box.append(button(prompt.by === ctx.seat ? "不弃，结束周游列国" : `不弃，付 ${prompt.fine} 元`,
      () => act({ type: "tour", card: null }), blocked, "ghost"));
  } else if (prompt.type === "bid") {
    box.append(button("当地主", () => act({ type: "bid", take: true }), blocked));
    box.append(button("不当", () => act({ type: "bid", take: false }), blocked, "ghost"));
  } else if (prompt.type === "give") {
    box.append(button(`交给 ${ctx.seatName(prompt.to)}`, () => act({ type: "give", card: ui.selected }), ui.selected == null || blocked));
  }
}

function modeButton(text, mode, rerender) {
  const on = ui.mode === mode;
  return button(on ? "取消" + text.replace(/（.*/, "") : text, () => {
    ui.mode = on ? null : mode;
    ui.picked = new Set();
    rerender();
  }, false, on ? "ghost" : "");
}

// hand cards that cashing ``patternId`` would use
function cardsForPattern(info, patternId, handIds, card) {
  const p = info.patterns.find((x) => x.id === patternId);
  const out = new Set();
  if (!p) return out;
  const left = { ...p.need };
  for (const id of handIds) {
    const c = card(id).city;
    if (left[c] > 0) { left[c]--; out.add(id); }
  }
  return out;
}

// one {el, n} per city, a row per province, for the pile lists
function cityRows(info, counts) {
  return Object.entries(info.provinces).map(([province, cities]) => cities.map((city) => {
    const n = counts[city] ?? 0;
    const el = div(`mcard ${PROVINCE_CLASS[province]}`);
    el.textContent = n ? `${city}×${n}` : city;
    return { el, n };
  }));
}

// all discard areas together; the list shows how many of each city were
// discarded, the ones never discarded faded
function discardPile(info, view, v, card, top) {
  const seen = {};
  let total = 0;
  for (const zone of new Set(v.discard_of)) {
    for (const id of view.zones[zone].cards) {
      const c = card(id).city;
      seen[c] = (seen[c] ?? 0) + 1;
      total++;
    }
  }
  return pileEl({ label: "弃牌堆", count: total, rows: cityRows(info, seen), top, title: "弃牌区里的牌", pop: "left" });
}

function finalBox(v, name) {
  const box = div("score-sheet");
  const h = document.createElement("h3");
  h.textContent = `游戏结束，获胜：${v.winners.map(name).join("、")}`;
  box.append(h);
  if (v.teams) box.append(span("", `地主 ${v.teams.landlord} 元 vs 农民合计 ${v.teams.farmers} 元`));
  const t = document.createElement("table");
  [...v.money.keys()].sort((a, b) => v.money[b] - v.money[a]).forEach((i, k) => {
    const r = t.insertRow();
    r.insertCell().textContent = `${k + 1}`;
    r.insertCell().textContent = name(i);
    const c = r.insertCell();
    c.textContent = `${v.money[i]} 元`;
    if (v.winners.includes(i)) c.className = "winner";
  });
  box.append(t);
  return box;
}

function patternPanel(info, myCities, rerender) {
  const provinceOf = {};
  for (const [p, cs] of Object.entries(info.provinces)) for (const c of cs) provinceOf[c] = p;
  const have = {};
  for (const c of myCities) have[c] = (have[c] ?? 0) + 1;
  const det = document.createElement("details");
  det.className = "c-patterns";
  det.open = patternUi.open;
  det.addEventListener("toggle", () => { patternUi.open = det.open; });
  det.innerHTML = "<summary>Pattern 速查</summary>";
  const body = div("c-pop");
  body.append(span("c-pop-title", "按还差几张排序"));
  // 四个X (four of one city) are left out: they are obvious from the hand
  const rows = info.patterns.filter((p) => !p.id.startsWith("four:")).map((p) => {
    let missing = 0;
    for (const [c, k] of Object.entries(p.need)) missing += Math.max(0, k - (have[c] ?? 0));
    return { p, missing };
  }).sort((a, b) => a.missing - b.missing || b.p.value - a.p.value);
  const table = document.createElement("table");
  const shown = patternUi.all ? rows : rows.filter((r) => r.missing <= 2);
  for (const { p, missing } of shown) {
    const tr = table.insertRow();
    tr.className = missing === 0 ? "ready" : missing === 1 ? "near" : "";
    tr.insertCell().textContent = p.name;
    tr.insertCell().textContent = p.value;
    const cities = tr.insertCell();
    for (const [c, k] of Object.entries(p.need)) {
      // each city behaves like a card of it when hovered
      cities.append(linkToMap(span("pc " + PROVINCE_CLASS[provinceOf[c]] + ((have[c] ?? 0) >= k ? " ok" : ""),
        k > 1 ? `${c}×${k}` : c), { city: c }));
    }
    tr.insertCell().textContent = missing ? `差 ${missing}` : "可兑现";
  }
  body.append(table);
  body.append(button(patternUi.all ? "只显示差 2 张以内的" : `显示全部 ${rows.length} 个 Pattern`, () => {
    patternUi.all = !patternUi.all;
    rerender();
  }, false, "ghost small"));
  det.append(body);
  return det;
}

// the log, newest first: player names in bold, Pattern names and money
// changes in colour, a line between turns
function logPanel(log, name, patterns) {
  const box = div("c-log");
  box.append(span("c-log-title", "记录"));
  const list = div("c-log-list");
  const names = patterns.map((p) => p.name).sort((a, b) => b.length - a.length)
    .map((x) => x.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  const re = new RegExp(`\\{P(\\d+)\\}|([+-]\\d+) 元|${names.join("|")}`, "g");
  for (const e of [...log].reverse().slice(0, 150)) {
    const line = div("c-log-line" + (/的回合：/.test(e.msg) ? " turn" : ""));
    let at = 0;
    for (const m of e.msg.matchAll(re)) {
      line.append(e.msg.slice(at, m.index));
      if (m[1] != null) line.append(span("c-who", name(+m[1])));
      else if (m[2] != null) line.append(span(m[2][0] === "+" ? "c-plus" : "c-minus", `${signed(+m[2])} 元`));
      else line.append(span("c-pat", m[0]));
      at = m.index + m[0].length;
    }
    line.append(e.msg.slice(at));
    list.append(line);
  }
  box.append(list);
  return box;
}

function sortCards(ids, card, cityOrder) {
  return [...ids].sort((a, b) => cityOrder.indexOf(card(a).city) - cityOrder.indexOf(card(b).city) || a - b);
}

// hovering a city card highlights that city's Patterns on the map
// while a city or Pattern is hovered (map, cards, Pattern table, buttons)
// every card of a city outside it fades
let tableEl = null;
function fadeOtherCities(cities) {
  if (!tableEl) return;
  for (const e of tableEl.querySelectorAll(".ccard[data-city], .mcard[data-city]")) {
    e.classList.toggle("faded", cities != null && !cities.has(e.dataset.city));
  }
}
onFocusChange(fadeOtherCities);

function linkToMap(d, c) {
  d.dataset.city = c.city;
  d.addEventListener("mouseenter", () => hoverCity(c.city));
  d.addEventListener("mouseleave", () => hoverCity(null));
  return d;
}

// a playing-card sized city card
function bigCard(c) {
  const d = linkToMap(div("card ccard " + PROVINCE_CLASS[c.province]), c);
  d.innerHTML = `<span class="cc-band"></span><span class="cc-name"></span><span class="cc-prov"></span>`;
  d.children[1].textContent = c.city;
  d.children[2].textContent = c.province + (CAPITALS.has(c.city) ? " ★" : "");
  d.title = `${c.city}（${c.province}${CAPITALS.has(c.city) ? "，省会" : ""}）`;
  return d;
}

// small card for piles and known cards
function miniCard(c, extra = "") {
  const d = linkToMap(div(`mcard ${PROVINCE_CLASS[c.province]} ${extra}`), c);
  d.textContent = c.city;
  d.title = `${c.city}（${c.province}${CAPITALS.has(c.city) ? "，省会" : ""}）`;
  return d;
}

function back(size = "") {
  return div(size === "big" ? "card back" : "card back mini-back");
}

function button(text, onclick, disabled = false, cls = "") {
  const b = document.createElement("button");
  b.textContent = text;
  b.className = cls;
  b.disabled = disabled;
  b.onclick = onclick;
  return b;
}

function span(cls, text) {
  const s = document.createElement("span");
  s.className = cls;
  s.textContent = text;
  return s;
}

function div(cls) {
  const d = document.createElement("div");
  d.className = cls;
  return d;
}
