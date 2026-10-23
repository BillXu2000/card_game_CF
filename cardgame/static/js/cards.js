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
