// Card drawing helpers shared by game renderers.
export const SUIT_SYMBOL = { C: "♣", D: "♦", S: "♠", H: "♥" };
export const RANK_LABEL = { 11: "J", 12: "Q", 13: "K", 14: "A" };

export function rankLabel(rank) { return RANK_LABEL[rank] ?? String(rank); }

// Text label for any card attribute dict (French cards or named cards).
export function cardLabel(attrs) {
  if (!attrs) return "?";
  if (attrs.suit && attrs.rank) return SUIT_SYMBOL[attrs.suit] + rankLabel(attrs.rank);
  return attrs.name ?? JSON.stringify(attrs);
}

export function isRed(attrs) { return attrs.suit === "H" || attrs.suit === "D"; }

// A face-up French playing card element.
export function cardEl(attrs, id = null) {
  const d = document.createElement("div");
  d.className = "card face" + (isRed(attrs) ? " red" : "");
  if (id != null) d.dataset.id = id;
  const r = rankLabel(attrs.rank), s = SUIT_SYMBOL[attrs.suit];
  d.innerHTML = `<span class="corner tl">${r}<br>${s}</span><span class="pip">${s}</span><span class="corner br">${r}<br>${s}</span>`;
  d.title = cardLabel(attrs);
  return d;
}

export function backEl() {
  const d = document.createElement("div");
  d.className = "card back";
  return d;
}

// A pile of cards (draw pile, discard pile, ...) drawn as a stack whose
// thickness follows its size, with "<label> N 张" under it.  Hovering or
// tapping it lists every kind of card: ``rows`` is a list of rows of
// {el, n}, and kinds with n = 0 are faded.
//   top   element shown on top of the stack (face-up pile); default a back
//   title heading of the list, e.g. what "faded" means for this pile
//   pop   where the list opens: "left", "right" or "below"
export function pileEl({ label, count, rows = [], top = null, title = "", pop = "below", cls = "" }) {
  const pile = document.createElement("div");
  pile.className = `pile pop-${pop} ${cls}`;
  pile.tabIndex = 0;
  const stack = document.createElement("div");
  stack.className = "pile-stack" + (count ? "" : " empty");
  const layers = count ? Math.min(4, Math.ceil(count / 12)) : 0;
  for (let k = layers; k >= 1; k--) {
    const under = document.createElement("div");
    under.className = "card pile-under" + (top ? " face-up" : "");
    under.style.translate = `${k * 2}px ${k * 2}px`;
    stack.append(under);
  }
  if (count) stack.append(top ?? backEl());
  else stack.append(Object.assign(document.createElement("div"), { className: "card pile-slot" }));
  const caption = document.createElement("span");
  caption.className = "pile-label";
  caption.textContent = `${label} ${count} 张`;
  pile.append(stack, caption);
  if (rows.length) {
    const list = document.createElement("div");
    list.className = "pile-pop";
    if (title) {
      const h = document.createElement("div");
      h.className = "pile-title";
      h.textContent = title;
      list.append(h);
    }
    for (const row of rows) {
      const r = document.createElement("div");
      r.className = "pile-row";
      for (const { el, n } of row) {
        if (!n) el.classList.add("absent");
        r.append(el);
      }
      list.append(r);
    }
    pile.append(list);
  }
  return pile;
}
