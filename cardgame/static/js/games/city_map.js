// Simplified map of China for 城市交易所: every city of the game at its real
// position, with standard map symbols, plus the map features that some
// Patterns stand for (长江, railways, 太湖, ports, provinces, and icons for
// 四大火炉 / 泉岭大球).  City names appear on hover; cities you hold are
// filled with their province colour.
// Geometry comes from static/data/china_map.json (tools/build_china_map.py).

const SVGNS = "http://www.w3.org/2000/svg";
const GAME_COLOR = { "直辖市": "#c0392b", "江苏": "#2471a3", "湖北": "#1e8449", "四川": "#b9770e", "广东": "#7d3c98" };
const CAPITAL = "北京";
const CAPITALS = ["南京", "武汉", "成都", "广州"];
const PORTS = ["上海", "天津", "深圳", "汕头"];      // 【沿海港口】
const FURNACES = ["重庆", "武汉", "南京", "广州"];   // 【四大火炉】
const HAMMERS = ["十堰", "襄阳", "中山", "广元"];    // 【泉岭大球】

// Patterns that correspond to something drawn on the map
const FEATURES = {
  "special:长江之歌": { kind: "river", label: "长江" },
  "special:京沪高铁": { kind: "rail", id: "jinghu", label: "京沪高铁" },
  "special:成襄铁路": { kind: "rail", id: "chengxiang", label: "成襄铁路" },
  "special:苏锡常": { kind: "lake", id: "太湖", label: "环太湖" },
  "special:沿海港口": { kind: "ports", label: "港口" },
  "special:四大火炉": { kind: "fire", label: "火炉" },
  "special:泉岭大球": { kind: "hammer", label: "榔头" },
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
const VIEW_WIDTH = { main: 440, yrd: 214, prd: 214, locator: 150 };
const VIEW_TITLE = { yrd: "长江三角洲", prd: "珠江三角洲", locator: "全国" };

let data = null;
let loading = null;
let panel = null;          // persistent DOM node, re-attached on every render
let current = { hand: {}, patterns: [], provinceOf: {}, pinned: null, hover: null };

function load() {
  if (!loading) {
    loading = fetch("/static/data/china_map.json").then((r) => r.json()).then((d) => { data = d; });
  }
  return loading;
}

function el(tag, attrs = {}, parent = null) {
  const e = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (parent) parent.append(e);
  return e;
}

// The map panel.  ``info`` is the game's static info, ``hand`` {city: count}.
export function mapPanel(info, hand, onReady) {
  current.patterns = info.patterns;
  current.provinceOf = {};
  for (const [p, cs] of Object.entries(info.provinces)) for (const c of cs) current.provinceOf[c] = p;
  current.hand = hand;
  if (!panel) {
    panel = document.createElement("details");
    panel.className = "panel c-map";
    panel.open = true;
    panel.innerHTML = "<summary>中国地图</summary><div class='cm-body muted'>地图加载中…</div>";
    load().then(() => { build(); refresh(); onReady?.(); });
  } else if (data) {
    refresh();
  }
  return panel;
}

// Highlight a Pattern while hovering something that refers to it (null clears).
export function hoverPattern(patternId) {
  current.hover = patternId;
  if (data && panel) refreshHighlight();
}

function build() {
  const body = panel.querySelector(".cm-body");
  body.className = "cm-body";
  body.innerHTML = "";
  const main = view("main");
  body.append(main);
  const row = document.createElement("div");
  row.className = "cm-insets";
  row.append(view("yrd"), view("prd"));
  body.append(row);
  const foot = document.createElement("div");
  foot.className = "cm-foot";
  foot.append(featureList(), legend(), view("locator"));
  body.append(foot);
  const src = document.createElement("div");
  src.className = "cm-source";
  src.textContent = `数据：${data.source}。${data.projection}。成襄铁路为规则书中的线路，沿宝成、阳安、襄渝铁路示意。`;
  body.append(src);
}

function view(name) {
  const [x, y, w, h] = data.views[name];
  const width = VIEW_WIDTH[name];
  const k = w / width;  // view units per px
  const wrap = document.createElement("div");
  wrap.className = `cm-view cm-${name}`;
  if (VIEW_TITLE[name]) {
    const t = document.createElement("div");
    t.className = "cm-title";
    t.textContent = VIEW_TITLE[name];
    wrap.append(t);
  }
  const svg = el("svg", { viewBox: `${x} ${y} ${w} ${h}`, width, height: Math.round(width * h / w), class: "cm-svg" });
  svg.dataset.view = name;
  svg.dataset.k = k;
  el("rect", { x: x - 1000, y: y - 1000, width: w + 2000, height: h + 2000, class: "cm-sea" }, svg);
  base(svg, name);
  if (name === "main") {
    for (const inset of ["yrd", "prd"]) {
      const [ix, iy, iw, ih] = data.views[inset];
      el("rect", { x: ix, y: iy, width: iw, height: ih, class: "cm-inset-box" }, svg);
    }
  }
  if (name === "locator") {
    const [mx, my, mw, mh] = data.views.main;
    el("rect", { x: mx, y: my, width: mw, height: mh, class: "cm-inset-box" }, svg);
  }
  el("g", { class: "cm-cities" }, svg);
  wrap.append(svg);
  return wrap;
}

// static geography (drawn once per view)
function base(svg, name) {
  el("path", { d: data.neighbours, class: "cm-neighbour" }, svg);
  const provinces = el("g", { class: "cm-provinces" }, svg);
  for (const p of data.provinces) {
    const path = el("path", { d: p.d, class: "cm-prov" + (p.game ? " game" : "") }, provinces);
    if (p.game) {
      path.style.setProperty("--pv", GAME_COLOR[p.game]);
      path.dataset.game = p.game;
    }
    el("title", {}, path).textContent = p.name;
  }
  el("path", { d: data.coast, class: "cm-coast" }, svg);
  el("path", { d: data.border, class: "cm-border" }, svg);
  el("path", { d: data.dashes, class: "cm-dashes" }, svg);
  if (name === "locator") return;
  for (const [lake, d] of Object.entries(data.lakes)) {
    const p = el("path", { d, class: "cm-lake" }, svg);
    p.dataset.lake = lake;
    el("title", {}, p).textContent = lake;
  }
  el("path", { d: data.yellow_river, class: "cm-river yellow" }, svg);
  el("path", { d: data.yangtze, class: "cm-river yangtze" }, svg);
  for (const [id, r] of Object.entries(data.railways)) {
    const g = el("g", { class: `cm-rail ${r.kind}` }, svg);
    g.dataset.rail = id;
    el("path", { d: r.d, class: "under" }, g);
    el("path", { d: r.d, class: "over" }, g);
    el("title", {}, g).textContent = r.name;
  }
  if (name === "main") {
    const k = data.views.main[2] / VIEW_WIDTH.main;
    for (const p of data.provinces) {
      // only provinces of the game; municipalities are cities
      if (!p.label || !p.game || p.game === "直辖市") continue;
      const t = el("text", { x: p.label[0], y: p.label[1], class: "cm-prov-label game", "font-size": 12 * k }, svg);
      t.textContent = p.short;
      if (p.game) t.style.fill = GAME_COLOR[p.game];
    }
  }
  // names of rivers, railways and lakes next to the features
  const [, , vw] = data.views[name];
  const k = vw / VIEW_WIDTH[name];
  for (const [text, [x, y]] of Object.entries(data.feature_labels)) {
    const kind = text === "长江" || text === "太湖" ? "water" : "rail";
    if (name === "main" && text === "太湖") continue;  // too small; shown in the 长三角 inset
    if (name !== "main" && text !== "太湖") continue;
    const t = el("text", { x, y, class: `cm-feature-label ${kind}`, "font-size": 10 * k, "stroke-width": 3 * k,
      "text-anchor": "middle" }, svg);
    t.textContent = text;
  }
}

function refresh() {
  for (const svg of panel.querySelectorAll(".cm-svg")) drawCities(svg);
  refreshHighlight();
}

function drawCities(svg) {
  const name = svg.dataset.view;
  const k = +svg.dataset.k;
  const g = svg.querySelector(".cm-cities");
  g.innerHTML = "";
  if (name === "locator") return;
  const [x0, y0, w, h] = data.views[name];
  for (const [city, [x, y]] of Object.entries(data.cities)) {
    if (x < x0 || x > x0 + w || y < y0 || y > y0 + h) continue;
    const prov = current.provinceOf[city];
    const count = current.hand[city] ?? 0;
    const node = el("g", { class: "cm-city" + (count ? " held" : ""), transform: `translate(${x},${y}) scale(${k})` }, g);
    node.dataset.city = city;
    node.style.setProperty("--pv", GAME_COLOR[prov]);
    el("circle", { r: 9, class: "halo" }, node);
    if (city === CAPITAL) {
      el("circle", { r: 5.5, class: "sym-capital-ring" }, node);
      el("path", { d: star(4.6), class: "sym-capital" }, node);
    } else if (prov === "直辖市" || CAPITALS.includes(city)) {
      el("circle", { r: 4.5, class: "sym-prov-outer" }, node);
      el("circle", { r: 2.1, class: "sym-prov-inner" }, node);
    } else {
      el("circle", { r: 3.2, class: "sym-pref" }, node);
      el("circle", { r: 0.9, class: "sym-pref-dot" }, node);
    }
    if (PORTS.includes(city)) el("text", { x: -12, y: 12, class: "sym-port" }, node).textContent = "⚓";
    if (FURNACES.includes(city)) fire(node, 8, -9);
    if (HAMMERS.includes(city)) hammer(node, 8, -9);
    const [dx, dy, anchor] = LABELS[name][city] ?? [7, 4, "start"];
    const t = el("text", { x: dx, y: dy, "text-anchor": anchor, class: "cm-label" }, node);
    t.textContent = city + (count ? ` ×${count}` : "");
    // bring the hovered city to the front so its name is not hidden by neighbours
    node.addEventListener("mouseenter", () => { if (g.lastChild !== node) g.append(node); });
    const patterns = current.patterns.filter((p) => city in p.need && !p.id.startsWith("four:")).map((p) => p.name);
    el("title", {}, node).textContent = `${city}（${prov}${CAPITALS.includes(city) ? "，省会" : ""}）`
      + (count ? `\n手里有 ${count} 张` : "\n手里没有") + `\nPattern：${patterns.join("、")}`;
  }
}

// 【四大火炉】 flame
function fire(parent, x, y) {
  const g = el("g", { class: "sym-fire", transform: `translate(${x},${y})` }, parent);
  el("path", { d: "M0,-5.5C2.8,-2.2 4,0 3.2,2.6C2.4,5 -2.4,5 -3.2,2.6C-3.9,0.4 -1.6,-0.6 0,-5.5Z", class: "outer" }, g);
  el("path", { d: "M0,-0.8C1.5,1 1.6,2.7 0,3.8C-1.6,2.7 -1.5,1 0,-0.8Z", class: "inner" }, g);
  return g;
}

// 【泉岭大球】 hammer
function hammer(parent, x, y) {
  const g = el("g", { class: "sym-hammer", transform: `translate(${x},${y}) rotate(-35)` }, parent);
  el("rect", { x: -0.9, y: -2.5, width: 1.8, height: 8.5, rx: 0.5, class: "handle" }, g);
  el("rect", { x: -4.6, y: -5.2, width: 9.2, height: 3.4, rx: 0.7, class: "head" }, g);
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

function refreshHighlight() {
  const pid = current.hover ?? current.pinned;
  const p = pid ? current.patterns.find((x) => x.id === pid) : null;
  const cities = new Set(p ? Object.keys(p.need) : []);
  const f = pid ? FEATURES[pid] : null;
  for (const svg of panel.querySelectorAll(".cm-svg")) {
    svg.classList.toggle("focus", !!p);
    for (const node of svg.querySelectorAll(".cm-city")) node.classList.toggle("on", cities.has(node.dataset.city));
    for (const r of svg.querySelectorAll(".cm-rail")) r.classList.toggle("on", f?.kind === "rail" && f.id === r.dataset.rail);
    for (const r of svg.querySelectorAll(".cm-river.yangtze")) r.classList.toggle("on", f?.kind === "river");
    for (const l of svg.querySelectorAll(".cm-lake")) l.classList.toggle("on", f?.kind === "lake" && f.id === l.dataset.lake);
    for (const pr of svg.querySelectorAll(".cm-prov.game")) pr.classList.toggle("on", f?.kind === "province" && f.id === pr.dataset.game);
    svg.classList.toggle("ports-on", f?.kind === "ports");
    svg.classList.toggle("fire-on", f?.kind === "fire");
    svg.classList.toggle("hammer-on", f?.kind === "hammer");
    svg.classList.toggle("capitals-on", f?.kind === "capitals");
  }
  for (const b of panel.querySelectorAll(".cm-feature")) b.classList.toggle("on", b.dataset.pattern === pid);
  const caption = panel.querySelector(".cm-caption");
  if (caption) caption.textContent = p ? `${p.name}：${Object.keys(p.need).join("、")}（${p.value} 元）` : "移到 Pattern 上查看它在地图上的位置";
}

function featureList() {
  const box = document.createElement("div");
  box.className = "cm-features";
  const cap = document.createElement("div");
  cap.className = "cm-caption";
  box.append(cap);
  for (const [pid, f] of Object.entries(FEATURES)) {
    const p = current.patterns.find((x) => x.id === pid);
    if (!p) continue;
    const b = document.createElement("button");
    b.className = "cm-feature ghost small";
    b.dataset.pattern = pid;
    b.textContent = p.name.replace(/[【】]/g, "") + (f.label && !p.name.includes(f.label) ? `·${f.label}` : "");
    b.onmouseenter = () => hoverPattern(pid);
    b.onmouseleave = () => hoverPattern(null);
    b.onclick = () => { current.pinned = current.pinned === pid ? null : pid; refreshHighlight(); };
    box.append(b);
  }
  return box;
}

function legend() {
  const box = document.createElement("div");
  box.className = "cm-legend";
  const items = [
    ["首都", (s) => { el("circle", { cx: 12, cy: 8, r: 5.5, class: "sym-capital-ring" }, s); el("path", { d: star(4.6), transform: "translate(12,8)", class: "sym-capital" }, s); }],
    ["省级行政中心", (s) => { el("circle", { cx: 12, cy: 8, r: 4.5, class: "sym-prov-outer" }, s); el("circle", { cx: 12, cy: 8, r: 2.1, class: "sym-prov-inner" }, s); }],
    ["地级行政中心", (s) => { el("circle", { cx: 12, cy: 8, r: 3.2, class: "sym-pref" }, s); el("circle", { cx: 12, cy: 8, r: 0.9, class: "sym-pref-dot" }, s); }],
    ["国界", (s) => el("path", { d: "M1,8H23", class: "cm-border" }, s)],
    ["省级界", (s) => el("path", { d: "M1,8H23", class: "cm-prov-line" }, s)],
    ["海岸线", (s) => el("path", { d: "M1,8H23", class: "cm-coast" }, s)],
    ["河流", (s) => el("path", { d: "M1,10C6,4 12,12 23,6", class: "cm-river" }, s)],
    ["湖泊", (s) => el("ellipse", { cx: 12, cy: 8, rx: 9, ry: 5, class: "cm-lake" }, s)],
    ["高速铁路", (s) => { const g = el("g", { class: "cm-rail hsr" }, s); el("path", { d: "M1,8H23", class: "under" }, g); el("path", { d: "M1,8H23", class: "over" }, g); }],
    ["铁路", (s) => { const g = el("g", { class: "cm-rail rail" }, s); el("path", { d: "M1,8H23", class: "under" }, g); el("path", { d: "M1,8H23", class: "over" }, g); }],
    ["港口", (s) => { const t = el("text", { x: 6, y: 13, class: "sym-port" }, s); t.textContent = "⚓"; }],
    ["火炉", (s) => fire(s, 12, 9)],
    ["泉岭大球", (s) => hammer(s, 12, 9)],
    ["手里有的城市", (s) => {
      const g = el("g", { class: "cm-city held", transform: "translate(12,8)" }, s);
      g.style.setProperty("--pv", GAME_COLOR["江苏"]);
      el("circle", { r: 3.2, class: "sym-pref" }, g);
      el("circle", { r: 0.9, class: "sym-pref-dot" }, g);
    }],
  ];
  for (const [label, draw] of items) {
    const item = document.createElement("span");
    item.className = "cm-legend-item";
    const s = el("svg", { width: 24, height: 16, viewBox: "0 0 24 16" });
    draw(s);
    item.append(s, document.createTextNode(label));
    box.append(item);
  }
  return box;
}
