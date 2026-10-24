// 骗人游戏 table: the other players along the top, in the middle the number
// being claimed, the cards on the table (the latest claim face down, ready to
// be challenged) and how the previous round ended, then your hand.
import { backEl, cardEl, pileEl, rankLabel } from "../cards.js";

const RANK_ORDER = [14, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13];   // A first, like the rules list

// UI state kept between renders (reset when the prompt changes)
let ui = { key: null, selected: new Set(), x: null, picking: false, picks: new Set() };

export function render(el, ctx) {
  const { view, prompt } = ctx;
  const v = view.vars;
  const n = view.num_players;
  const me = ctx.seat;
  const name = (i) => ctx.seatName(i);
  const card = (id) => view.cards[id];
  const key = `${v.round_no}:${v.claims.length}:${prompt?.type}`;
  if (key !== ui.key) ui = { key, selected: new Set(), x: null, picking: false, picks: new Set() };
  const rerender = () => render(el, ctx);

  el.className = "game liar";
  el.innerHTML = "";
  const felt = div("felt lg-table");
  el.append(felt);

  // ---- other players
  const top = div("lg-seats");
  const base = me ?? 0;
  for (let k = me == null ? 0 : 1; k < n; k++) top.append(seatBox((base + k) % n));
  felt.append(top);

  function seatBox(i) {
    const box = div("lg-seat" + (v.turn === i ? " turn" : "") + (v.out.includes(i) ? " out" : ""));
    const head = div("lg-head");
    head.append(span("lg-name", name(i) + (ctx.room.seats[i]?.ai ? " (AI)" : "")));
    const place = v.out.indexOf(i);
    if (place >= 0) head.append(span("lg-tag gold", `第 ${place + 1} 名`));
    else if (v.passed[i] && v.phase === "play") head.append(span("lg-tag", "pass"));
    box.append(head);
    const ids = view.zones[`hand:${i}`].cards;
    const backs = div("lg-backs");
    for (const id of ids.slice(0, 20)) backs.append(id == null ? miniBack() : miniFace(card(id)));
    box.append(backs, span("lg-count", ids.length ? `${ids.length} 张` : "没有手牌"));
    return box;
  }

  // ---- middle: the number, the table, the piles
  const mid = div("lg-mid");
  const centre = div("lg-centre");
  if (v.phase === "play") {
    centre.append(span("lg-x-label", "本轮声称的数字"), span("lg-x", rankLabel(v.x)));
  } else if (v.phase === "lead") {
    centre.append(span("lg-x-label", `第 ${v.round_no} 轮`), span("lg-x small", `${name(v.turn)} 定数字`));
  }
  if (v.claims.length) {
    const list = div("lg-claims");
    v.claims.forEach((c, k) => list.append(span("lg-claim" + (k === v.claims.length - 1 ? " last" : ""),
      `${name(c.seat)} ${c.count} 张`)));
    centre.append(list);
  }
  // the latest claim, face down; in a partial check the challenger picks cards here
  const claimIds = view.zones.claim.cards;
  if (claimIds.length) {
    const last = v.claims[v.claims.length - 1];
    const row = div("lg-claim-cards" + (ui.picking ? " picking" : ""));
    claimIds.forEach((id, k) => {
      const c = id == null ? backEl() : faceEl(card(id));
      if (ui.picking) {
        c.classList.add("pick");
        if (ui.picks.has(k)) c.classList.add("picked");
        c.onclick = () => {
          if (ui.picks.has(k)) ui.picks.delete(k);
          else if (ui.picks.size < prompt.challenge.reveal) ui.picks.add(k);
          rerender();
        };
      }
      row.append(c);
    });
    centre.append(span("lg-label", `${name(last.seat)} 最新声称：${last.count} 张 ${rankLabel(v.x)}`), row);
  }
  if (v.phase === "lead" && v.last_result) centre.append(resultBox(v.last_result, card, name));
  const piles = div("lg-piles");
  const tableCount = view.zones.table.cards.length;
  piles.append(pileEl({ label: "本轮已出", count: tableCount + claimIds.length, cls: "lg-pile" }));
  piles.append(pileEl({ label: "弃牌堆", count: view.zones.discard.cards.length, cls: "lg-pile" }));
  mid.append(centre, piles);
  felt.append(mid);

  // ---- status
  const status = div("status");
  status.textContent = statusText(ctx, v, prompt, name);
  felt.append(status);

  // ---- my hand and actions
  if (me != null) {
    const bottom = div("bottom lg-mine");
    const myBox = seatBox(me);
    myBox.classList.add("lg-me");
    myBox.querySelector(".lg-backs").remove();
    bottom.append(myBox);
    const handIds = sortCards(view.zones[`hand:${me}`].cards, card);
    const hand = div("my-hand lg-hand");
    const x = prompt?.type === "lead" ? ui.x : v.x;
    const canPick = prompt && (prompt.type === "lead" || prompt.can_play) && !ui.picking;
    for (const id of handIds) {
      const c = faceEl(card(id));
      if (x != null && (card(id).joker || card(id).rank === x)) c.classList.add("match");
      if (canPick) {
        c.classList.add("clickable");
        if (ui.selected.has(id)) c.classList.add("selected");
        c.onclick = () => {
          ui.selected.has(id) ? ui.selected.delete(id) : ui.selected.add(id);
          rerender();
        };
      }
      hand.append(c);
    }
    if (!handIds.length) hand.append(span("lg-empty", "没有手牌"));
    bottom.append(hand);
    const actions = div("lg-actions");
    buildActions(actions, ctx, prompt, handIds, card, rerender);
    if (actions.childElementCount) bottom.append(actions);
    felt.append(bottom);
  }

  if (v.phase === "over") felt.append(finalBox(v, name));

  const below = div("lg-below");
  below.append(logPanel(view.log, name));
  el.append(below);
}

function buildActions(box, ctx, prompt, handIds, card, rerender) {
  if (!prompt) return;
  const act = ctx.act;
  const sel = [...ui.selected];
  if (prompt.type === "lead") {
    const ranks = div("lg-ranks");
    for (const r of RANK_ORDER) {
      const have = handIds.filter((id) => card(id).rank === r).length;
      const b = button(rankLabel(r) + (have ? ` ×${have}` : ""), () => {
        ui.x = r;
        // picking a number selects the cards of it (the jokers stay as they are)
        ui.selected = new Set([...ui.selected].filter((id) => card(id).joker));
        for (const id of handIds) if (card(id).rank === r) ui.selected.add(id);
        rerender();
      }, false, ui.x === r ? "on" : "ghost");
      ranks.append(b);
    }
    box.append(span("lg-hint", "选一个数字，再选要打出的牌："), ranks);
    box.append(button(ui.x == null ? "出牌" : `打出 ${sel.length} 张，说都是 ${rankLabel(ui.x)}`,
      () => act({ type: "lead", x: ui.x, cards: sel }), ui.x == null || sel.length < prompt.min));
    return;
  }
  if (prompt.type !== "play") return;
  const ch = prompt.challenge;
  if (ui.picking) {
    box.append(span("lg-hint", `点选桌上 ${ch.reveal} 张要翻开的牌（已选 ${ui.picks.size}）`));
    box.append(button("翻开", () => act({ type: "challenge", picks: [...ui.picks] }), ui.picks.size !== ch.reveal, "danger"));
    box.append(button("取消", () => { ui.picking = false; ui.picks = new Set(); rerender(); }, false, "ghost"));
    return;
  }
  if (prompt.can_play) {
    box.append(button(`打出 ${sel.length} 张，说都是 ${rankLabel(prompt.x)}`,
      () => act({ type: "play", cards: sel }), sel.length < prompt.min));
  }
  const all = ch.reveal >= ch.count;
  box.append(button(all ? `质疑 ${ctx.seatName(ch.seat)}（翻开全部 ${ch.count} 张）` : `质疑 ${ctx.seatName(ch.seat)}（翻开 ${ch.reveal} 张）`, () => {
    if (all) act({ type: "challenge" });
    else { ui.picking = true; rerender(); }
  }, false, "danger"));
  box.append(button("pass", () => act({ type: "pass" }), false, "ghost"));
}

function statusText(ctx, v, prompt, name) {
  if (v.phase === "over") return "游戏结束";
  if (prompt?.type === "lead") return `你赢了上一轮：定一个数字，打出至少 ${prompt.min} 张牌`;
  if (prompt?.type === "play") {
    if (ui.picking) return "选择要翻开的牌";
    return prompt.can_play ? `轮到你：跟着说是 ${rankLabel(prompt.x)}，质疑，或者 pass`
      : `轮到你：牌不够 ${prompt.min} 张，只能质疑或者 pass`;
  }
  if (v.phase === "lead") return `等待 ${name(v.turn)} 定数字…`;
  return `等待 ${name(v.turn)}…`;
}

function resultBox(r, card, name) {
  const box = div("lg-result");
  if (r.type === "challenge") {
    box.append(span("lg-result-title", `${name(r.challenger)} 质疑 ${name(r.claimer)}：` +
      (r.truthful ? `都是 ${rankLabel(r.x)}，${name(r.taker)} 收下 ${r.taken} 张` : `有假，${name(r.taker)} 收回 ${r.taken} 张`)));
    const row = div("lg-claim-cards");
    for (const id of r.shown) {
      const c = card(id);
      if (!c) continue;
      const e = faceEl(c);
      if (!(c.joker || c.rank === r.x)) e.classList.add("fake");
      row.append(e);
    }
    box.append(row);
  } else {
    box.append(span("lg-result-title", `只剩 ${name(r.winner)} 没有 pass，${r.discarded} 张牌进入弃牌堆`));
  }
  return box;
}

function finalBox(v, name) {
  const box = div("score-sheet");
  const h = document.createElement("h3");
  h.textContent = `游戏结束，${name(v.out[0])} 第一个出完！`;
  box.append(h);
  const t = document.createElement("table");
  v.out.forEach((s, k) => {
    const r = t.insertRow();
    r.insertCell().textContent = `第 ${k + 1} 名`;
    r.insertCell().textContent = name(s);
    if (k === 0) r.cells[1].className = "winner";
  });
  box.append(t);
  return box;
}

function logPanel(log, name) {
  const det = document.createElement("details");
  det.className = "panel lg-log";
  det.open = true;
  det.innerHTML = "<summary>记录</summary>";
  const list = div("lg-log-list");
  for (const e of [...log].reverse().slice(0, 80)) list.append(span("", e.msg.replace(/\{P(\d+)\}/g, (_, i) => name(+i))));
  det.append(list);
  return det;
}

function sortCards(ids, card) {
  const key = (id) => (card(id).joker ? 99 : RANK_ORDER.indexOf(card(id).rank));
  return [...ids].sort((a, b) => key(a) - key(b) || a - b);
}

// a face-up card: a playing card, or a joker
function faceEl(c) {
  if (!c.joker) return cardEl(c);
  const d = div("card face joker" + (c.color === "red" ? " red" : ""));
  d.innerHTML = `<span class="corner tl">J<br>O<br>K<br>E<br>R</span><span class="pip">★</span>`;
  d.title = "王（可当任何数字）";
  return d;
}

function miniBack() { return div("card back lg-mini"); }

function miniFace(c) {
  const d = div("lg-mini-face" + (c.joker || c.suit === "H" || c.suit === "D" ? " red" : ""));
  d.textContent = c.joker ? "王" : rankLabel(c.rank);
  d.title = "大家都看到过这张牌";
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
