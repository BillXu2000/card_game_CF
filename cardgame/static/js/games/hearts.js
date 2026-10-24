// Hearts table, laid out like Windows XP Hearts: you at the bottom, the
// player on your left (next in turn) at the left, then top, then right.
import { backEl, cardEl, cardLabel, pileEl } from "../cards.js";

const SUIT_ORDER = { C: 0, D: 1, S: 2, H: 3 };
const POS = ["bottom", "left", "top", "right"];
const DIR_NAME = { left: "左边", right: "右边", across: "对面" };

// UI state kept between renders
let selected = new Set();
let selectedKey = null;

export function render(el, ctx) {
  const { view, prompt } = ctx;
  const v = view.vars;
  const me = ctx.seat ?? 0;
  const rel = (i) => (i - me + 4) % 4;
  const cardOf = (id) => view.cards[id];

  // reset pass selection when a new hand/prompt starts
  const key = `${v.hand_no}:${prompt?.type}`;
  if (key !== selectedKey) { selected = new Set(); selectedKey = key; }

  el.className = "game hearts";
  el.innerHTML = "";
  const table = div("felt");
  el.append(table);

  // ---- players around the table
  for (let i = 0; i < 4; i++) {
    const p = rel(i);
    const box = div(`hp hp-${POS[p]}` + (v.turn === i && v.phase === "play" ? " turn" : ""));
    const name = div("hp-name");
    name.textContent = ctx.seatName(i) + (ctx.room.seats[i]?.ai ? " (AI)" : "");
    const score = div("hp-score");
    score.textContent = `本局 ${v.points_taken[i]} · 总分 ${v.scores[i]}`;
    box.append(name, score);
    if (p !== 0 || ctx.seat == null) {
      // opponents' cards are always drawn face down, even the ones we passed
      const backs = div("hp-backs");
      for (let k = 0; k < view.zones[`hand:${i}`].cards.length; k++) backs.append(backEl());
      box.append(backs);
      const passing = view.zones[`pass:${i}`].cards.length;
      if (v.phase === "pass") {
        const s = div("hp-note");
        s.textContent = passing ? "已选好传牌" : "正在选牌…";
        box.append(s);
      }
    }
    // point cards taken this hand
    const won = view.zones[`won:${i}`].cards.filter((id) => id != null && isPoint(cardOf(id)));
    if (won.length) {
      const pts = div("hp-points");
      pts.title = "本局吃到的分牌";
      for (const id of sortCards(won, cardOf)) {
        const c = div("mini" + (cardOf(id).suit === "H" ? " red" : ""));
        c.textContent = cardLabel(cardOf(id));
        pts.append(c);
      }
      box.append(pts);
    }
    table.append(box);
  }

  // ---- centre: current trick, or the last finished trick
  const centre = div("trick");
  const trick = view.zones.trick.cards;
  let shown = trick.map((id, k) => [v.trick_seats[k], id]);
  let finished = false;
  if (!trick.length && v.last_trick && v.phase !== "pass") {
    shown = v.last_trick.seats.map((s, k) => [s, v.last_trick.cards[k]]);
    finished = true;
  }
  for (const [seat, id] of shown) {
    const c = cardEl(cardOf(id), id);
    c.classList.add(`t-${POS[rel(seat)]}`);
    if (finished) c.classList.add(seat === v.last_trick.winner ? "won" : "dim");
    centre.append(c);
  }
  if (finished) {
    const n = div("trick-note");
    n.textContent = `${ctx.seatName(v.last_trick.winner)} 吃到这一墩`;
    centre.append(n);
  }
  table.append(centre);
  table.append(discardPile(view, cardOf));

  // ---- status line
  const status = div("status");
  status.textContent = statusText(ctx, v, prompt);
  table.append(status);

  // ---- my hand
  if (ctx.seat != null) {
    const handIds = view.zones[`hand:${me}`].cards;
    const passIds = view.zones[`pass:${me}`].cards;
    const legal = new Set(prompt?.type === "play" ? prompt.legal : []);
    const received = new Set(v.trick_no === 0 && !v.tricks.length ? view.private.received?.cards ?? [] : []);
    const hand = div("my-hand");
    for (const id of sortCards(handIds, cardOf)) {
      const c = cardEl(cardOf(id), id);
      if (received.has(id) && !trick.includes(id)) c.classList.add("received");
      if (prompt?.type === "pass") {
        c.classList.add("clickable");
        if (selected.has(id)) c.classList.add("selected");
        c.onclick = () => {
          if (selected.has(id)) selected.delete(id);
          else if (selected.size < 3) selected.add(id);
          render(el, ctx);
        };
      } else if (prompt?.type === "play") {
        if (legal.has(id)) {
          c.classList.add("clickable");
          c.onclick = () => ctx.act({ type: "play", card: id });
        } else c.classList.add("dim");
      }
      hand.append(c);
    }
    for (const id of passIds) {
      const c = cardEl(cardOf(id), id);
      c.classList.add("selected", "dim");
      hand.append(c);
    }
    const bottom = div("bottom");
    bottom.append(hand);
    if (prompt?.type === "pass") {
      const b = document.createElement("button");
      b.textContent = `传给${DIR_NAME[prompt.direction]}（${ctx.seatName(prompt.to)}）`;
      b.disabled = selected.size !== 3;
      b.onclick = () => ctx.act({ type: "pass", cards: [...selected] });
      bottom.append(b);
    }
    table.append(bottom);
  }

  // ---- score sheet between hands / at the end
  if (v.phase === "score" || v.phase === "over") table.append(scoreSheet(ctx, v, prompt));
}

function statusText(ctx, v, prompt) {
  const hand = `第 ${v.hand_no + 1} 局`;
  if (v.phase === "pass") {
    if (prompt?.type === "pass") return `${hand}：选择三张牌传给${DIR_NAME[prompt.direction]}的 ${ctx.seatName(prompt.to)}`;
    return `${hand}：等待其他玩家传牌…`;
  }
  if (v.phase === "play") {
    const broken = v.hearts_broken ? " · 红心已破" : "";
    if (prompt?.type === "play") {
      const lead = !ctx.view.zones.trick.cards.length;
      const tip = v.trick_no === 0 && lead ? "请出 ♣2" : lead ? "轮到你出牌" : "轮到你跟牌";
      return `${hand}${broken}：${tip}`;
    }
    return `${hand}${broken}：等待 ${ctx.seatName(v.turn)} 出牌…`;
  }
  if (v.phase === "over") return "游戏结束";
  return `${hand} 结束`;
}

function scoreSheet(ctx, v, prompt) {
  const box = div("score-sheet");
  const title = document.createElement("h3");
  const moon = v.last_hand?.moon;
  if (v.phase === "over") {
    title.textContent = `游戏结束，获胜：${v.winners.map(ctx.seatName).join("、")}`;
  } else {
    title.textContent = moon != null ? `${ctx.seatName(moon)} 射月成功！` : `第 ${v.hand_no + 1} 局结束`;
  }
  box.append(title);
  const t = document.createElement("table");
  const head = t.createTHead().insertRow();
  head.insertCell().textContent = "局";
  for (let i = 0; i < 4; i++) head.insertCell().textContent = ctx.seatName(i);
  const body = t.createTBody();
  const totals = [0, 0, 0, 0];
  v.score_history.forEach((pts, h) => {
    const r = body.insertRow();
    r.insertCell().textContent = h + 1;
    pts.forEach((p, i) => { totals[i] += p; r.insertCell().textContent = `${totals[i]}（+${p}）`; });
  });
  const foot = t.createTFoot().insertRow();
  foot.insertCell().textContent = "总分";
  const low = Math.min(...v.scores);
  v.scores.forEach((s) => {
    const c = foot.insertCell();
    c.textContent = s;
    if (s === low) c.className = v.phase === "over" ? "winner" : "leader";
  });
  box.append(t);
  if (prompt?.type === "continue") {
    const b = document.createElement("button");
    b.textContent = "继续下一局";
    b.onclick = () => ctx.act({ type: "continue" });
    box.append(b);
  } else if (v.phase === "score") {
    const n = div("muted");
    n.textContent = "等待其他玩家…";
    box.append(n);
  }
  return box;
}

// the finished tricks of this hand; hovering lists all 52 cards with the
// ones not played yet faded
function discardPile(view, cardOf) {
  const played = new Set();
  for (let i = 0; i < 4; i++) {
    for (const id of view.zones[`won:${i}`].cards) {
      const c = cardOf(id);
      if (c) played.add(c.suit + c.rank);
    }
  }
  const rows = Object.keys(SUIT_ORDER).map((suit) => {
    const row = [];
    for (let rank = 2; rank <= 14; rank++) {
      const el = div("mini" + (suit === "H" || suit === "D" ? " red" : ""));
      el.textContent = cardLabel({ suit, rank });
      row.push({ el, n: +played.has(suit + rank) });
    }
    return row;
  });
  return pileEl({ label: "弃牌堆", count: played.size, rows, title: "本局已出的牌", pop: "left", cls: "hp-pile" });
}

function isPoint(c) { return c.suit === "H" || (c.suit === "S" && c.rank === 12); }

function sortCards(ids, cardOf) {
  return [...ids].sort((a, b) => {
    const x = cardOf(a), y = cardOf(b);
    return SUIT_ORDER[x.suit] - SUIT_ORDER[y.suit] || x.rank - y.rank;
  });
}

function div(cls) {
  const d = document.createElement("div");
  d.className = cls;
  return d;
}
