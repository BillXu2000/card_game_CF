// 城市交易所 table.
const PROVINCE_CLASS = { "直辖市": "pv-m", "江苏": "pv-js", "湖北": "pv-hb", "四川": "pv-sc", "广东": "pv-gd" };
const CAPITALS = new Set(["南京", "武汉", "成都", "广州"]);

// pattern reference panel state (kept for the whole session)
const patternUi = { open: true, all: false };

// UI state kept between renders (reset when the prompt changes)
let ui = { key: null, mode: null, picked: new Set(), selected: null, dianpao: new Set() };

export function render(el, ctx) {
  const { view, prompt } = ctx;
  const v = view.vars;
  const n = view.num_players;
  const me = ctx.seat;
  const key = `${view.seq}:${prompt?.type}`;
  if (key !== ui.key) ui = { key, mode: null, picked: new Set(), selected: null, dianpao: new Set() };
  const rerender = () => render(el, ctx);
  const name = (i) => ctx.seatName(i);
  const card = (id) => view.cards[id];

  el.className = "game city";
  el.innerHTML = "";

  // ---- status
  const status = div("c-status");
  const deck = view.zones.deck.cards.length;
  status.innerHTML = `<span>第 ${v.turn_no} 回合</span><span>牌堆 ${deck} 张</span>`;
  const msg = document.createElement("b");
  msg.textContent = statusText(ctx, v, prompt, name);
  status.append(msg);
  el.append(status);

  // ---- players, starting with me
  const players = div("c-players");
  const order = [...Array(n).keys()].map((k) => ((me ?? 0) + k) % n);
  for (const i of order) {
    const p = div("c-player" + (v.turn === i ? " turn" : "") + (i === me ? " me" : ""));
    const head = div("c-head");
    const nm = document.createElement("b");
    nm.textContent = name(i);
    const money = span("c-money", `${v.money[i]} 元`);
    const handCount = span("muted", `手牌 ${view.zones[`hand:${i}`].cards.length}`);
    head.append(nm, money, handCount);
    for (const id of view.zones[`special:${i}`].cards) {
      const c = card(id);
      const s = span("c-special " + c.kind + (c.used ? " used" : ""), c.kind === "tour" ? "周游" : "强买");
      s.title = c.name + (c.used ? "（已使用）" : "");
      head.append(s);
    }
    p.append(head);
    // known cards in another player's hand (bought / bought back)
    if (i !== me) {
      const known = view.zones[`hand:${i}`].cards.filter((id) => id != null);
      if (known.length) {
        const k = div("c-known");
        k.append(span("muted", "已知手牌："));
        for (const id of known) k.append(chip(card(id)));
        p.append(k);
      }
    }
    const pile = div("c-discard");
    const discard = view.zones[`discard:${i}`].cards;
    if (!discard.length) pile.append(span("muted", "弃牌区为空"));
    for (const id of discard) {
      const c = chip(card(id));
      if (v.pending?.cards.includes(id)) c.classList.add("hot");
      if (ui.mode === "buyback" && prompt?.buyback.includes(id)) {
        c.classList.add("pick");
        c.onclick = () => ctx.act({ type: "buyback", card: id });
      } else if (ui.mode === "buy" && prompt?.buy?.cards.includes(id)) {
        c.classList.add("pick");
        if (ui.picked.has(id)) c.classList.add("picked");
        c.onclick = () => {
          if (ui.picked.has(id)) ui.picked.delete(id);
          else if (ui.picked.size < prompt.buy.max) ui.picked.add(id);
          rerender();
        };
      }
      pile.append(c);
    }
    p.append(pile);
    players.append(p);
  }
  el.append(players);

  // ---- my hand and actions
  if (me != null) {
    const area = div("c-mine");
    const handIds = view.zones[`hand:${me}`].cards;
    const drawn = new Set(view.private.drawn ?? []);
    const hand = div("c-hand");
    const selectable = prompt?.type === "draw" ? (id) => drawn.has(id) : prompt?.type === "tour" ? () => true : null;
    const cityOrder = Object.values(ctx.room.static.provinces).flat();
    for (const id of sortCards(handIds, card, cityOrder)) {
      const c = bigCard(card(id));
      if (drawn.has(id) && v.turn === me) c.classList.add("new");
      if (selectable && selectable(id)) {
        c.classList.add("pick");
        if (ui.selected === id) c.classList.add("picked");
        c.onclick = () => { ui.selected = ui.selected === id ? null : id; rerender(); };
      }
      hand.append(c);
    }
    if (!handIds.length) hand.append(span("muted", "没有手牌"));
    area.append(hand);
    const actions = div("c-actions");
    buildActions(actions, ctx, prompt, rerender);
    area.append(actions);
    el.append(area);
  }

  if (v.phase === "over") el.append(finalBox(v, name));

  // ---- reference + log
  const bottom = div("c-bottom");
  const info = ctx.room.static;
  bottom.append(patternPanel(info, me != null ? view.zones[`hand:${me}`].cards.map((id) => card(id).city) : [], rerender));
  bottom.append(logPanel(view.log, name));
  el.append(bottom);
}

function statusText(ctx, v, prompt, name) {
  if (v.phase === "over") return "游戏结束";
  if (prompt) {
    return {
      draw: "摸牌阶段：从本回合摸到的三张牌中选一张弃置",
      main: "出牌阶段：回购 / 出游 / 强买 / 兑现，完成后结束回合",
      dianpao: `${name(prompt.by)} 弃置的牌可以让你兑现 Pattern（点炮）`,
      tour: `${name(prompt.by)} 发动周游列国：弃置一张手牌，或交给 TA ${prompt.fine} 元`,
    }[prompt.type];
  }
  const waiting = ctx.room.waiting.map(name).join("、");
  if (v.phase === "dianpao") return `等待 ${waiting} 决定是否兑现…`;
  if (v.phase === "tour") return `周游列国：等待 ${waiting}…`;
  return `等待 ${name(v.turn)} 行动…`;
}

function buildActions(box, ctx, prompt, rerender) {
  if (!prompt) return;
  const act = ctx.act;
  if (prompt.type === "draw") {
    box.append(button("弃置所选", () => act({ type: "discard", card: ui.selected }), ui.selected == null));
    for (const o of prompt.cash)
      box.append(button(`不弃牌，直接兑现 ${o.name}（+${o.value}）`, () => act({ type: "cash", pattern: o.pattern })));
  } else if (prompt.type === "main") {
    for (const o of prompt.cash) box.append(button(`兑现 ${o.name}（+${o.value}）`, () => act({ type: "cash", pattern: o.pattern })));
    if (prompt.buyback.length)
      box.append(toggle("回购（10 元）", "buyback", rerender, "点击你弃牌区中要收回的牌"));
    if (prompt.buy)
      box.append(toggle(`强买（每张 ${prompt.buy.price} 元）`, "buy", rerender,
        `点击弃牌区中要买的牌（最多 ${prompt.buy.max} 张）`));
    if (ui.mode === "buy")
      box.append(button(`确认强买 ${ui.picked.size} 张`, () => act({ type: "buy", cards: [...ui.picked] }), !ui.picked.size));
    if (prompt.tour) box.append(button("出游（周游列国）", () => {
      if (confirm("发动周游列国？")) act({ type: "tour" });
    }));
    box.append(button("结束回合", () => act({ type: "end" }), false, "ghost"));
  } else if (prompt.type === "dianpao") {
    const list = div("c-options");
    prompt.options.forEach((o, i) => {
      const label = document.createElement("label");
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = ui.dianpao.has(i);
      cb.onchange = () => { cb.checked ? ui.dianpao.add(i) : ui.dianpao.delete(i); rerender(); };
      label.append(cb, document.createTextNode(` 兑现 ${o.name}：你 +${o.gain}，弃牌者 -${o.cost}`));
      list.append(label);
    });
    box.append(list);
    box.append(button("兑现所选", () => act({ type: "dianpao", choices: [...ui.dianpao] }), !ui.dianpao.size));
    box.append(button("不兑现", () => act({ type: "dianpao", choices: [] }), false, "ghost"));
  } else if (prompt.type === "tour") {
    box.append(button("弃置所选", () => act({ type: "tour", card: ui.selected }), ui.selected == null));
    box.append(button(`不弃，付 ${prompt.fine} 元`, () => act({ type: "tour", card: null }), false, "ghost"));
  }
}

function toggle(text, mode, rerender, hint) {
  const b = button(ui.mode === mode ? `取消${text.replace(/（.*/, "")}` : text, () => {
    ui.mode = ui.mode === mode ? null : mode;
    ui.picked = new Set();
    rerender();
  }, false, ui.mode === mode ? "ghost" : "");
  if (ui.mode === mode) b.title = hint;
  const wrap = document.createElement("span");
  wrap.className = "row";
  wrap.append(b);
  if (ui.mode === mode) wrap.append(span("muted", hint));
  return wrap;
}

function finalBox(v, name) {
  const box = div("c-final panel");
  const ranking = [...v.money.keys()].sort((a, b) => v.money[b] - v.money[a]);
  const h = document.createElement("h3");
  h.textContent = `游戏结束，获胜：${v.winners.map(name).join("、")}`;
  box.append(h);
  ranking.forEach((i, k) => box.append(span("c-rank", `${k + 1}. ${name(i)}：${v.money[i]} 元`)));
  return box;
}

function patternPanel(info, myCities, rerender) {
  const provinceOf = {};
  for (const [p, cs] of Object.entries(info.provinces)) for (const c of cs) provinceOf[c] = p;
  const have = {};
  for (const c of myCities) have[c] = (have[c] ?? 0) + 1;
  const det = document.createElement("details");
  det.className = "panel c-patterns";
  det.open = patternUi.open;
  det.ontoggle = () => { patternUi.open = det.open; };
  det.innerHTML = "<summary>Pattern 速查（按差几张排序）</summary>";
  const rows = info.patterns.map((p) => {
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
      const s = span("pc " + PROVINCE_CLASS[provinceOf[c]] + ((have[c] ?? 0) >= k ? " ok" : ""), k > 1 ? `${c}×${k}` : c);
      cities.append(s);
    }
    tr.insertCell().textContent = missing ? `差 ${missing}` : "可兑现";
  }
  det.append(table);
  const more = button(patternUi.all ? "只显示差 2 张以内的" : `显示全部 ${rows.length} 个 Pattern`, () => {
    patternUi.all = !patternUi.all;
    rerender();
  }, false, "ghost small");
  det.append(more);
  return det;
}

function logPanel(log, name) {
  const box = div("panel c-log");
  box.innerHTML = "<h3>记录</h3>";
  const list = div("c-log-list");
  for (const e of [...log].reverse().slice(0, 60)) {
    const d = div("");
    d.textContent = e.msg.replace(/\{P(\d+)\}/g, (_, i) => name(+i));
    list.append(d);
  }
  box.append(list);
  return box;
}

function sortCards(ids, card, cityOrder) {
  return [...ids].sort((a, b) => cityOrder.indexOf(card(a).city) - cityOrder.indexOf(card(b).city) || a - b);
}

function chip(c) {
  const s = span("pc " + PROVINCE_CLASS[c.province], c.city + (CAPITALS.has(c.city) ? "★" : ""));
  s.title = `${c.city}（${c.province}${CAPITALS.has(c.city) ? "省会" : ""}）`;
  return s;
}

function bigCard(c) {
  const d = div("ccard " + PROVINCE_CLASS[c.province]);
  d.innerHTML = `<span class="cc-name"></span><span class="cc-prov"></span>`;
  d.children[0].textContent = c.city + (CAPITALS.has(c.city) ? "★" : "");
  d.children[1].textContent = c.province;
  return d;
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
