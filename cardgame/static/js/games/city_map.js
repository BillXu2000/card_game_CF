// Map of China used as the background of the 城市交易所 table: every city of
// the game at its real position with standard map symbols, plus the map
// features some Patterns stand for (长江, railways, ports, provinces,
// and icons for 四大火炉 / 泉岭大球 / 古来要塞).  City names appear on hover.
// Geometry comes from static/data/china_map.json (tools/build_china_map.py).

const SVGNS = "http://www.w3.org/2000/svg";
// 长江三角洲 / 珠江三角洲 close-ups in the legend box (disabled for now)
const SHOW_INSETS = false;
const GAME_COLOR = { "直辖市": "#c0392b", "江苏": "#2471a3", "湖北": "#1e8449", "四川": "#b9770e", "广东": "#7d3c98" };
const CAPITAL = "北京";
const CAPITALS = ["南京", "武汉", "成都", "广州"];
const PORTS = ["上海", "天津", "深圳", "汕头"];      // 【沿海港口】
const FURNACES = ["重庆", "武汉", "南京", "广州"];   // 【四大火炉】
const HAMMERS = ["十堰", "襄阳", "中山", "广元"];    // 【泉岭大球】
const FORTS = ["徐州", "荆州", "襄阳", "广元"];      // 【古来要塞】
// hammers sit a little to the lower right of the city (units of the symbol group)
const HAMMER_SHIFT = [5, 5];

// a city with special icons is drawn as those icons (stacked when there are two)
function iconsOf(city) {
  return [PORTS.includes(city) && anchor, FURNACES.includes(city) && fire,
          FORTS.includes(city) && fort, HAMMERS.includes(city) && hammer].filter(Boolean);
}

// Patterns that correspond to something drawn on the map
const FEATURES = {
  "special:长江之歌": { kind: "river", label: "长江" },
  "special:京沪高铁": { kind: "rail", id: "jinghu", label: "京沪高铁" },
  "special:成襄铁路": { kind: "rail", id: "chengxiang", label: "成襄铁路" },
  "special:沿海港口": { kind: "ports", label: "港口" },
  "special:四大火炉": { kind: "fire", label: "火炉" },
  "special:泉岭大球": { kind: "hammer", label: "榔头" },
  "special:古来要塞": { kind: "fort", label: "要塞" },
  "municipal": { kind: "province", id: "直辖市", label: "直辖市" },
  "province:江苏": { kind: "province", id: "江苏", label: "江苏省" },
  "province:湖北": { kind: "province", id: "湖北", label: "湖北省" },
  "province:四川": { kind: "province", id: "四川", label: "四川省" },
  "province:广东": { kind: "province", id: "广东", label: "广东省" },
  "capitals": { kind: "capitals", label: "省级行政中心" },
};

// where a city's name appears when hovered: [dx, dy, anchor] in px (default: right)
const LABELS = {
  main: { 北京: [-7, -5, "end"], 重庆: [-7, 4, "end"], 南京: [-7, -4, "end"], 宜昌: [-7, -3, "end"],
          十堰: [-7, -4, "end"], 成都: [-7, 4, "end"], 广州: [-7, -4, "end"] },
  yrd: { 南京: [4, -8, "start"], 常州: [0, -9, "middle"], 无锡: [-7, 11, "end"], 苏州: [2, 14, "middle"] },
  prd: { 中山: [-7, 4, "end"], 河源: [-7, -4, "end"] },
  locator: {},
};
const INSET_WIDTH = { yrd: 200, prd: 200, locator: 180 };
const INSET_TITLE = { yrd: "长江三角洲", prd: "珠江三角洲", locator: "全国" };
const CITY_MARGIN_KM = 140;   // room around the outermost cities when fitting the map
const SYMBOL_SCALE = 2;       // map symbols are drawn at twice their base size

let data = null;
let loading = null;
let bg = null;         // persistent background element (re-attached on every render)
let legendBox = null;  // persistent legend element
let caption = null;    // persistent caption element
let fitK = null;       // map units per px of the background
let pendingFit = null; // fit requested before the data arrived
let current = { patterns: [], provinceOf: {}, held: new Set(), pinned: null, hover: null, city: null };
const focusListeners = [];  // told whenever the hovered city / Pattern changes

function load() {
  if (!loading) {
    loading = fetch(new URL("../../data/china_map.json", import.meta.url)).then((r) => r.json()).then((d) => { data = d; });
  }
  return loading;
}

function el(tag, attrs = {}, parent = null) {
  const e = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (parent) parent.append(e);
  return e;
}

// ------------------------------------------------------------------ public
// The background map.  ``info`` is the game's static info; ``held`` the
// cities in the player's hand (shown normally, every other city is faded).
export function mapBackground(info, held = new Set()) {
  current.held = held;
  current.patterns = info.patterns;
  current.provinceOf = {};
  for (const [p, cs] of Object.entries(info.provinces)) for (const c of cs) current.provinceOf[c] = p;
  mapLegend();
  if (!bg) {
    bg = document.createElement("div");
    bg.className = "cm-bg";
    load().then(() => {
      buildBackground();
      buildLegend();
      if (pendingFit) fitMap(...pendingFit);
    });
  } else if (data) {
    drawCities(bg.querySelector("svg"), fitK);
    for (const svg of legendBox.querySelectorAll(".cm-svg")) drawCities(svg, +svg.dataset.k);
    refreshHighlight();
  }
  return bg;
}

export function mapLegend() {
  if (!legendBox) {
    legendBox = document.createElement("details");
    legendBox.className = "cm-legend-box";
    legendBox.open = window.innerWidth > 860;  // collapsed on phones
    legendBox.innerHTML = "<summary>图例</summary><div class='cm-legend-body muted'>地图加载中…</div>";
  }
  return legendBox;
}

export function mapCaption() {
  if (!caption) {
    caption = document.createElement("div");
    caption.className = "cm-caption empty";
  }
  return caption;
}

// Fit the cities into ``area`` (an element inside ``felt``); the rest of the
// map fills the whole table behind everything else.
export function fitMap(felt, area) {
  if (!data || !bg?.firstChild) {
    pendingFit = [felt, area];
    return;
  }
  pendingFit = null;
  const F = felt.getBoundingClientRect();
  const A = area.getBoundingClientRect();
  if (!F.width || !A.width || !A.height) return;
  const [gx, gy, gw, gh] = cityBox();
  const s = Math.min(A.width / gw, A.height / gh);   // px per map unit
  const vx = gx + gw / 2 - (A.left - F.left + A.width / 2) / s;
  const vy = gy + gh / 2 - (A.top - F.top + A.height / 2) / s;
  const svg = bg.querySelector("svg");
  svg.setAttribute("viewBox", `${vx} ${vy} ${F.width / s} ${F.height / s}`);
  const k = 1 / s;
  if (fitK === null || Math.abs(k - fitK) / k > 1e-3) {
    fitK = k;
    drawLabels(svg, k);
    drawCities(svg, k);
    refreshHighlight();
  }
}

export function hoverPattern(patternId) {
  if (current.hover === patternId) return;
  current.hover = patternId;
  if (data && bg) refreshHighlight();
  notifyFocus();
}

// Highlight every Pattern a city takes part in (hovering the city or a card of it).
export function hoverCity(city) {
  if (current.city === city) return;
  current.city = city;
  if (data && bg) refreshHighlight();
  notifyFocus();
}

// The cities being looked at: those of the hovered Pattern, else the hovered
// city, else null.
export function focusCities() {
  if (current.hover) {
    const p = current.patterns.find((x) => x.id === current.hover);
    if (p) return new Set(Object.keys(p.need));
  }
  return current.city ? new Set([current.city]) : null;
}

// Register ``fn(Set | null)`` to follow focusCities() (hovers on the map, cards or Patterns).
export function onFocusChange(fn) {
  if (!focusListeners.includes(fn)) focusListeners.push(fn);
}

function notifyFocus() {
  const cities = focusCities();
  for (const fn of focusListeners) fn(cities);
}

// ------------------------------------------------------------------- build
function cityBox() {
  const xs = Object.values(data.cities).map((c) => c[0]);
  const ys = Object.values(data.cities).map((c) => c[1]);
  const m = CITY_MARGIN_KM;
  return [Math.min(...xs) - m, Math.min(...ys) - m, Math.max(...xs) - Math.min(...xs) + 2 * m,
          Math.max(...ys) - Math.min(...ys) + 2 * m];
}

function buildBackground() {
  const svg = el("svg", { class: "cm-svg", preserveAspectRatio: "none", viewBox: data.views.main.join(" ") });
  svg.dataset.view = "main";
  const [x, y, w, h] = data.views.locator;
  el("rect", { x: x - 5000, y: y - 5000, width: w + 10000, height: h + 10000, class: "cm-sea" }, svg);
  base(svg, "main");
  el("g", { class: "cm-labels" }, svg);
  el("g", { class: "cm-cities" }, svg);
  bg.append(svg);
}

function buildLegend() {
  const body = legendBox.querySelector(".cm-legend-body");
  body.className = "cm-legend-body";
  body.innerHTML = "";
  body.append(legend());
  if (SHOW_INSETS) body.append(inset("yrd"), inset("prd"));
}

function inset(name) {
  const [x, y, w, h] = data.views[name];
  const width = INSET_WIDTH[name];
  const wrap = document.createElement("div");
  wrap.className = `cm-view cm-${name}`;
  const t = document.createElement("div");
  t.className = "cm-title";
  t.textContent = INSET_TITLE[name];
  wrap.append(t);
  const svg = el("svg", { viewBox: `${x} ${y} ${w} ${h}`, width, height: Math.round(width * h / w), class: "cm-svg" });
  svg.dataset.view = name;
  svg.dataset.k = w / width;
  el("rect", { x: x - 1000, y: y - 1000, width: w + 2000, height: h + 2000, class: "cm-sea" }, svg);
  base(svg, name);
  if (name === "locator") {
    const [cx, cy, cw, ch] = cityBox();
    el("rect", { x: cx, y: cy, width: cw, height: ch, class: "cm-inset-box" }, svg);
  }
  el("g", { class: "cm-labels" }, svg);
  el("g", { class: "cm-cities" }, svg);
  drawLabels(svg, w / width);
  drawCities(svg, w / width);
  wrap.append(svg);
  return wrap;
}

// static geography
function base(svg, name) {
  el("path", { d: data.neighbours, class: "cm-neighbour" }, svg);
  const provinces = el("g", { class: "cm-provinces" }, svg);
  for (const p of data.provinces) {
    const path = el("path", { d: p.d, class: "cm-prov" + (p.game ? " game" : "") }, provinces);
    if (p.game) {
      path.style.setProperty("--pv", GAME_COLOR[p.game]);
      path.dataset.game = p.game;
    }
  }
  el("path", { d: data.coast, class: "cm-coast" }, svg);
  el("path", { d: data.border, class: "cm-border" }, svg);
  el("path", { d: data.dashes, class: "cm-dashes" }, svg);
  if (name === "locator") return;
  el("path", { d: data.yellow_river, class: "cm-river yellow" }, svg);
  el("path", { d: data.yangtze, class: "cm-river yangtze" }, svg);
  for (const [id, r] of Object.entries(data.railways)) {
    const g = el("g", { class: `cm-rail ${r.kind}` }, svg);
    g.dataset.rail = id;
    el("path", { d: r.d, class: "under" }, g);
    el("path", { d: r.d, class: "over" }, g);
  }
}

// province and feature names are sized in px, so they are redrawn when the scale changes
function drawLabels(svg, k) {
  const name = svg.dataset.view;
  const g = svg.querySelector(".cm-labels");
  g.innerHTML = "";
  if (name === "locator") return;
  if (name === "main") {
    for (const p of data.provinces) {
      if (!p.label || !p.game) continue;  // only provinces (and municipalities) of the game
      const t = el("text", { x: p.label[0], y: p.label[1], class: "cm-prov-label", "font-size": 13 * k }, g);
      t.textContent = p.short;
      t.style.fill = GAME_COLOR[p.game];
    }
  }
  for (const [text, [x, y]] of Object.entries(data.feature_labels)) {
    const kind = text === "长江" ? "water" : "rail";
    if (name !== "main") continue;
    const t = el("text", { x, y, class: `cm-feature-label ${kind}`, "font-size": 11 * k, "stroke-width": 3 * k,
      "text-anchor": "middle" }, g);
    t.textContent = text;
  }
}

function drawCities(svg, k) {
  if (!svg || !k) return;
  const name = svg.dataset.view;
  const g = svg.querySelector(".cm-cities");
  g.innerHTML = "";
  if (name === "locator") return;
  const [x0, y0, w, h] = data.views[name];
  for (const [city, [x, y]] of Object.entries(data.cities)) {
    if (name !== "main" && (x < x0 || x > x0 + w || y < y0 || y > y0 + h)) continue;
    const prov = current.provinceOf[city];
    const node = el("g", { class: "cm-city" + (current.held.has(city) ? "" : " away"),
      transform: `translate(${x},${y}) scale(${k * SYMBOL_SCALE})` }, g);
    node.dataset.city = city;
    node.style.setProperty("--pv", GAME_COLOR[prov]);
    el("circle", { r: 7, class: "halo" }, node);
    const icons = iconsOf(city);
    if (icons.length) {
      // the icons replace the city sign
      for (const draw of icons) draw(node, ...(draw === hammer ? HAMMER_SHIFT : [0, 0]));
    } else if (city === CAPITAL) {
      el("circle", { r: 5.5, class: "sym-capital-ring" }, node);
      el("path", { d: star(4.6), class: "sym-capital" }, node);
    } else if (prov === "直辖市" || CAPITALS.includes(city)) {
      el("circle", { r: 4.5, class: "sym-prov-outer" }, node);
      el("circle", { r: 2.1, class: "sym-prov-inner" }, node);
    } else {
      el("circle", { r: 3.2, class: "sym-pref" }, node);
      el("circle", { r: 0.9, class: "sym-pref-dot" }, node);
    }
    const [dx, dy, align] = LABELS[name][city] ?? (icons.length ? [9, 4, "start"] : [7, 4, "start"]);
    const t = el("text", { x: dx, y: dy, "text-anchor": align, class: "cm-label" }, node);
    t.textContent = city;
    // bring the hovered city to the front so its name is not hidden by neighbours
    node.addEventListener("mouseenter", () => {
      if (g.lastChild !== node) g.append(node);
      hoverCity(city);
    });
    node.addEventListener("mouseleave", () => hoverCity(null));
  }
}

// ------------------------------------------------------------------- icons
// 【沿海港口】 black anchor with a white outline
function anchor(parent, x, y, size = 0.95) {
  const g = el("g", { class: "sym-port", transform: `translate(${x},${y}) scale(${size}) translate(0,0.6)` }, parent);
  const d = "M0,-3.4V4.6M-2.6,-2.3H2.6M-4.2,1.2A4.4,4.4 0 0 0 4.2,1.2"
    + "M-4.2,1.2l-1.2,0.9M-4.2,1.2l0.3,1.4M4.2,1.2l1.2,0.9M4.2,1.2l-0.3,1.4";
  for (const cls of ["halo-line", "ink"]) {
    const part = el("g", { class: cls }, g);
    el("circle", { cy: -4.6, r: 1.2 }, part);
    el("path", { d }, part);
  }
  return g;
}

// 【四大火炉】 flame
function fire(parent, x, y, size = 1.15) {
  const g = el("g", { class: "sym-fire", transform: `translate(${x},${y}) scale(${size}) translate(0,0.4)` }, parent);
  el("path", { d: "M0,-5.5C2.8,-2.2 4,0 3.2,2.6C2.4,5 -2.4,5 -3.2,2.6C-3.9,0.4 -1.6,-0.6 0,-5.5Z", class: "outer" }, g);
  el("path", { d: "M0,-0.8C1.5,1 1.6,2.7 0,3.8C-1.6,2.7 -1.5,1 0,-0.8Z", class: "inner" }, g);
  return g;
}

// 【泉岭大球】 hammer: big, dark head on a wooden handle, with a white outline
function hammer(parent, x, y, size = 1.3) {
  const g = el("g", { class: "sym-hammer", transform: `translate(${x},${y}) scale(${size}) rotate(-40) translate(0,-0.6)` }, parent);
  el("rect", { x: -1.1, y: -2.6, width: 2.2, height: 9.5, rx: 0.6, class: "handle" }, g);
  el("rect", { x: -5, y: -5.8, width: 10, height: 4, rx: 0.8, class: "head" }, g);
  return g;
}

// 【古来要塞】 castle: two crenellated towers with arrow slits, a crenellated
// curtain wall and an arched gate (the usual castle/fortress map sign)
function fort(parent, x, y, size = 1) {
  const g = el("g", { class: "sym-fort", transform: `translate(${x},${y}) scale(${size})` }, parent);
  el("path", {
    d: "M-6,5V-5.5H-5V-4.5H-4V-5.5H-3V-2.5H-2V-1.5H-1V-2.5H1V-1.5H2V-2.5H3V-5.5H4V-4.5H5V-5.5H6V5Z"
      + "M-1.3,5V2.6A1.3,1.3 0 0 1 1.3,2.6V5Z"          // gate
      + "M-4.75,-2.6h0.5v1.7h-0.5Z M4.25,-2.6h0.5v1.7h-0.5Z",  // arrow slits
    "fill-rule": "evenodd", class: "castle",
  }, g);
  return g;
}

function star(r) {
  const pts = [];
  for (let i = 0; i < 10; i++) {
    const a = -Math.PI / 2 + i * Math.PI / 5;
    const rr = i % 2 ? r * 0.42 : r;
    pts.push(`${(rr * Math.cos(a)).toFixed(2)},${(rr * Math.sin(a)).toFixed(2)}`);
  }
  return "M" + pts.join("L") + "Z";
}

// --------------------------------------------------------------- highlight
function refreshHighlight() {
  // a hovered Pattern wins over a hovered city, which wins over the pinned Pattern
  let pids = [];
  let text = "";
  if (current.hover) pids = [current.hover];
  else if (current.city) pids = current.patterns.filter((p) => current.city in p.need).map((p) => p.id);
  else if (current.pinned) pids = [current.pinned];
  const ps = pids.map((id) => current.patterns.find((x) => x.id === id)).filter(Boolean);
  if (current.city && !current.hover) {
    text = `${current.city}：` + ps.filter((p) => !p.id.startsWith("four:")).map((p) => p.name).join("、");
  } else if (ps.length) {
    const p = ps[0];
    text = `${p.name}：${Object.keys(p.need).join("、")}（${p.value} 元）`;
  }
  // hovering a city: only that city and the lines/areas of its Patterns stand out,
  // every other city fades; hovering a Pattern: all its cities stand out
  const cityMode = !!current.city && !current.hover;
  const cities = cityMode ? new Set() : new Set(ps.flatMap((p) => Object.keys(p.need)));
  const fs = pids.map((id) => FEATURES[id]).filter(Boolean);
  const has = (kind, id) => fs.some((f) => f.kind === kind && (id === undefined || f.id === id));
  const ICONS = ["ports", "fire", "hammer", "fort", "capitals"];
  const svgs = [bg?.querySelector("svg"), ...(legendBox?.querySelectorAll(".cm-svg") ?? [])].filter(Boolean);
  for (const svg of svgs) {
    svg.classList.toggle("focus", ps.length > 0);
    for (const node of svg.querySelectorAll(".cm-city")) {
      node.classList.toggle("on", cities.has(node.dataset.city));
      node.classList.toggle("this", cityMode && node.dataset.city === current.city);
    }
    for (const r of svg.querySelectorAll(".cm-rail")) r.classList.toggle("on", has("rail", r.dataset.rail));
    for (const r of svg.querySelectorAll(".cm-river.yangtze")) r.classList.toggle("on", has("river"));
    for (const pr of svg.querySelectorAll(".cm-prov.game")) pr.classList.toggle("on", has("province", pr.dataset.game));
    for (const kind of ICONS) svg.classList.toggle(`${kind}-on`, !cityMode && has(kind));
  }
  for (const b of legendBox?.querySelectorAll(".cm-feature") ?? []) b.classList.toggle("on", pids.includes(b.dataset.pattern));
  if (caption) {
    caption.textContent = text;
    caption.classList.toggle("empty", !text);
  }
}

// ------------------------------------------------------------------ legend
// The legend lists the Patterns one per row (whole provinces, four of a city
// and the city pairs are left out), each with its map symbol if it has
// one.  Hovering a row shows the Pattern on the map; clicking pins it.
const LEGEND_ROWS = {
  "special:长江之歌": { draw: (s) => el("path", { d: "M1,10C6,4 12,12 23,6", class: "cm-river" }, s), text: "长江" },
  "special:京沪高铁": { draw: (s) => railSymbol(s, "hsr") },
  "special:成襄铁路": { draw: (s) => railSymbol(s, "rail") },
  "special:沿海港口": { draw: (s) => anchor(s, 12, 8.5, 1.15), text: "港口" },
  "special:四大火炉": { draw: (s) => fire(s, 12, 8.5, 1.3), text: "火炉" },
  "special:泉岭大球": { draw: (s) => hammer(s, 12, 9, 1.15), text: "榔头！" },
  "special:古来要塞": { draw: (s) => fort(s, 12, 8.3, 1.15), text: "要塞" },
  "capitals": { draw: (s) => { el("circle", { cx: 12, cy: 8, r: 4.5, class: "sym-prov-outer" }, s); el("circle", { cx: 12, cy: 8, r: 2.1, class: "sym-prov-inner" }, s); } },
};
const NOT_IN_LEGEND = /^(four:|province:|pair:)/;

function railSymbol(s, kind) {
  const g = el("g", { class: `cm-rail ${kind}` }, s);
  el("path", { d: "M1,8H23", class: "under" }, g);
  el("path", { d: "M1,8H23", class: "over" }, g);
}

function legend() {
  const box = document.createElement("div");
  box.className = "cm-legend";
  for (const p of current.patterns) {
    if (NOT_IN_LEGEND.test(p.id)) continue;
    const row = LEGEND_ROWS[p.id] ?? {};
    const b = document.createElement("button");
    b.className = "cm-legend-item cm-feature";
    b.dataset.pattern = p.id;
    b.title = `${p.name}：${Object.keys(p.need).join("、")}（${p.value} 元）`;
    const s = el("svg", { width: 48, height: 32, viewBox: "0 0 24 16" });
    row.draw?.(s);
    const name = document.createElement("span");
    name.className = "cm-legend-name";
    name.textContent = row.text ?? p.name.replace(/[【】]/g, "");
    const value = document.createElement("span");
    value.className = "cm-legend-value";
    value.textContent = p.value;
    b.append(s, name, value);
    b.onmouseenter = () => hoverPattern(p.id);
    b.onmouseleave = () => hoverPattern(null);
    b.onclick = () => { current.pinned = current.pinned === p.id ? null : p.id; refreshHighlight(); };
    box.append(b);
  }
  return box;
}
