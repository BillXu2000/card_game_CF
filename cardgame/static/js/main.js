// Client shell: connection, login, lobby, room chrome.  The game table
// itself is drawn by a per-game renderer (static/js/games/<id>.js), falling
// back to the generic renderer.
import * as generic from "./games/generic.js";

const $ = (id) => document.getElementById(id);
const TOKEN_KEY = "cardgame.token";
const STATUS = { waiting: "等待开始", playing: "进行中", finished: "已结束" };

const app = {
  ws: null,
  user: null,
  lobby: null,
  room: null,          // last room message
  renderers: {},       // game id -> module
  wantRoom: null,      // room code to reopen after reconnect
};

function storageGet(k) { try { return localStorage.getItem(k); } catch { return null; } }
function storageSet(k, v) { try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch {} }

// ------------------------------------------------------------ connection
function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws`);
  app.ws = ws;
  $("conn").classList.remove("hidden");
  ws.onopen = () => {
    $("conn").classList.add("hidden");
    const token = storageGet(TOKEN_KEY);
    if (token) send({ op: "resume", token });
    else show("login");
  };
  ws.onmessage = (ev) => onMessage(JSON.parse(ev.data));
  ws.onclose = () => {
    $("conn").textContent = "连接断开，正在重连…";
    $("conn").classList.remove("hidden");
    setTimeout(connect, 1500);
  };
}

export function send(msg) {
  if (app.ws && app.ws.readyState === WebSocket.OPEN) app.ws.send(JSON.stringify(msg));
}

function toast(text, isError = false) {
  const t = $("toast");
  t.textContent = text;
  t.classList.toggle("error", isError);
  t.classList.remove("hidden");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => t.classList.add("hidden"), 3000);
}

function show(screen) {
  for (const s of ["login", "lobby", "room"]) $(s).classList.toggle("hidden", s !== screen);
}

// --------------------------------------------------------------- messages
function onMessage(m) {
  switch (m.op) {
    case "login_ok":
      app.user = m.username;
      storageSet(TOKEN_KEY, m.token);
      if (m.created) toast(`已注册新用户 ${m.username}`);
      if (app.wantRoom) send({ op: "join", code: app.wantRoom });
      break;
    case "lobby":
      app.lobby = m;
      if (!app.wantRoom) { app.room = null; renderLobby(); show("lobby"); }
      break;
    case "room":
      app.room = m.room;
      app.wantRoom = m.room.code;
      setHash(m.room.code);
      renderRoom();
      show("room");
      break;
    case "room_closed":
      toast(`房间 ${m.code} 已关闭`);
      leaveRoomView();
      break;
    case "history":
      showHistory(m.items);
      break;
    case "export":
      download(`${m.code}-${m.state.game}-${m.state.seq}.json`, JSON.stringify(m.state, null, 1));
      break;
    case "error":
      if (m.req === "resume") { storageSet(TOKEN_KEY, null); show("login"); }
      if (m.req === "join") leaveRoomView();
      toast(m.message, true);
      break;
  }
}

function setHash(code) {
  const h = code ? `#${code}` : "";
  if (location.hash !== h) history.replaceState(null, "", location.pathname + h);
}

function leaveRoomView() {
  app.wantRoom = null;
  app.room = null;
  setHash(null);
  send({ op: "lobby" });
}

function download(name, text) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type: "application/json" }));
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

// ------------------------------------------------------------------ login
$("login-form").addEventListener("submit", (e) => {
  e.preventDefault();
  send({ op: "login", username: $("login-name").value, password: $("login-pass").value });
  $("login-pass").value = "";
});
$("logout").onclick = () => {
  send({ op: "logout" });
  storageSet(TOKEN_KEY, null);
  app.user = null;
  show("login");
};

// ------------------------------------------------------------------ lobby
function renderLobby() {
  const m = app.lobby;
  $("lobby-user").textContent = `用户：${app.user}`;
  const sel = $("create-game");
  const prev = sel.value;
  sel.innerHTML = "";
  for (const g of m.games) sel.add(new Option(g.name, g.id));
  if (prev) sel.value = prev;
  updatePlayerChoices();

  const tbody = $("room-list");
  tbody.innerHTML = "";
  if (!m.rooms.length) {
    tbody.innerHTML = `<tr><td colspan="6" class="muted">还没有房间</td></tr>`;
  }
  for (const r of m.rooms) {
    const tr = document.createElement("tr");
    const seats = r.seats.map((s) => s ?? "—").join("，");
    tr.innerHTML = `<td class="code"></td><td></td><td></td><td></td><td></td><td><button>进入</button></td>`;
    const tds = tr.children;
    tds[0].textContent = r.code; tds[1].textContent = r.game_name; tds[2].textContent = r.host;
    tds[3].textContent = seats; tds[4].textContent = STATUS[r.status] ?? r.status;
    tr.querySelector("button").onclick = () => joinRoom(r.code);
    tbody.append(tr);
  }
}

function updatePlayerChoices() {
  const g = app.lobby?.games.find((x) => x.id === $("create-game").value);
  const sel = $("create-players");
  sel.innerHTML = "";
  if (!g) return;
  for (let n = g.min_players; n <= g.max_players; n++) sel.add(new Option(`${n} 人`, n));
  sel.classList.toggle("hidden", g.min_players === g.max_players);
}
$("create-game").onchange = updatePlayerChoices;
$("create").onclick = () => send({ op: "create", game: $("create-game").value, players: +$("create-players").value });
$("join-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const code = $("join-code").value.trim().toUpperCase();
  if (/^[A-Z]{4}$/.test(code)) joinRoom(code);
  else toast("房号是 4 位字母", true);
});

function joinRoom(code) {
  app.wantRoom = code;
  send({ op: "join", code });
}

// ------------------------------------------------------------------- room
$("room-back").onclick = leaveRoomView;
$("room-leave").onclick = () => {
  const r = app.room;
  if (r.status === "playing" && r.my_seat != null && !confirm("游戏进行中，离开后座位会保留，可以再回来。确定离开？")) return;
  app.wantRoom = null;
  setHash(null);
  send({ op: "leave", code: r.code });
};
$("btn-start").onclick = () => {
  const r = app.room;
  if (r.status === "playing" && !confirm("重新开始一局？当前进度和回退记录都会清空。")) return;
  send({ op: "start", code: r.code });
};
$("btn-history").onclick = () => send({ op: "history", code: app.room.code });
$("btn-export").onclick = () => send({ op: "export", code: app.room.code });
$("btn-import").onclick = () => $("import-file").click();
$("btn-close").onclick = () => { if (confirm("确定关闭房间？")) send({ op: "close", code: app.room.code }); };
$("import-file").onchange = async (e) => {
  const f = e.target.files[0];
  e.target.value = "";
  if (!f) return;
  try {
    send({ op: "import", code: app.room.code, state: JSON.parse(await f.text()) });
  } catch {
    toast("不是有效的 JSON 文件", true);
  }
};

function showHistory(items) {
  const list = $("history-list");
  list.innerHTML = "";
  for (const it of [...items].reverse()) {
    const row = document.createElement("div");
    row.className = "history-item";
    const t = new Date(it.time * 1000).toLocaleTimeString();
    row.innerHTML = `<span class="muted"></span><span></span><button class="ghost">回到这里</button>`;
    row.children[0].textContent = `#${it.index} ${t}`;
    row.children[1].textContent = it.label;
    row.querySelector("button").onclick = () => {
      send({ op: "rollback", code: app.room.code, index: it.index });
      $("history-dlg").close();
    };
    list.append(row);
  }
  $("history-dlg").showModal();
}

function renderRoom() {
  const r = app.room;
  $("room-title").textContent = `${r.game_name} · 房间 ${r.code}`;
  $("room-status").textContent = STATUS[r.status] ?? r.status;
  $("host-tools").classList.toggle("hidden", !r.is_host);
  $("btn-start").textContent = r.status === "waiting" ? "开始游戏" : "重新开始";
  $("btn-history").disabled = !r.history_len;
  $("btn-export").disabled = r.status === "waiting";
  renderSeats(r);
  renderOptions(r);
  renderGame(r);
}

function renderSeats(r) {
  const box = $("seats");
  box.innerHTML = "";
  r.seats.forEach((s, i) => {
    const d = document.createElement("div");
    d.className = "seat" + (i === r.my_seat ? " me" : "") + (r.waiting.includes(i) ? " active" : "");
    const name = document.createElement("span");
    name.className = "seat-name";
    name.textContent = s.name ?? "（空）";
    const dot = document.createElement("span");
    dot.className = "dot " + (s.online ? "on" : "off");
    dot.title = s.online ? "在线" : "离线";
    d.append(dot, name);
    if (s.ai) d.append(tag("AI"));
    if (s.user && s.user === r.host) d.append(tag("房主"));
    const canSit = r.my_seat == null && (s.ai || (s.name == null && r.status === "waiting"));
    if (canSit) d.append(button("坐这里", () => send({ op: "sit", code: r.code, seat: i })));
    else if (s.name == null && r.status === "waiting" && r.my_seat != null && i !== r.my_seat)
      d.append(button("换到这里", () => send({ op: "sit", code: r.code, seat: i })));
    if (r.is_host) {
      if (!s.ai) d.append(button("设为 AI", () => send({ op: "seat", code: r.code, seat: i, mode: "ai" }), "ghost"));
      if (s.name != null && r.status === "waiting" && i !== r.my_seat)
        d.append(button("清空", () => send({ op: "seat", code: r.code, seat: i, mode: "empty" }), "ghost"));
    }
    box.append(d);
  });
  if (r.is_host && r.status === "waiting" && r.min_players !== r.max_players) {
    const sel = document.createElement("select");
    for (let n = r.min_players; n <= r.max_players; n++) sel.add(new Option(`${n} 人`, n));
    sel.value = r.seats.length;
    sel.onchange = () => send({ op: "players", code: r.code, n: +sel.value });
    box.append(sel);
  }
}

function renderOptions(r) {
  const box = $("options");
  box.innerHTML = "";
  if (!r.option_specs.length) return;
  const editable = r.is_host && r.status !== "playing";
  for (const spec of r.option_specs) {
    const label = document.createElement("label");
    label.className = "opt";
    const value = r.options[spec.key];
    let input;
    if (spec.type === "bool") {
      input = document.createElement("input");
      input.type = "checkbox";
      input.checked = value;
      input.onchange = () => setOption(r, spec.key, input.checked);
      label.append(input, document.createTextNode(spec.label));
    } else {
      if (spec.type === "choice") {
        input = document.createElement("select");
        for (const [v, l] of spec.choices) input.add(new Option(l, v));
        input.value = value;
        input.onchange = () => setOption(r, spec.key, spec.choices.find((c) => String(c[0]) === input.value)[0]);
      } else {
        input = document.createElement("input");
        input.type = "number";
        input.value = value;
        if (spec.min != null) input.min = spec.min;
        if (spec.max != null) input.max = spec.max;
        input.onchange = () => setOption(r, spec.key, Math.round(+input.value));
      }
      label.append(document.createTextNode(spec.label + "："), input);
    }
    input.disabled = !editable;
    if (spec.help) label.title = spec.help;
    box.append(label);
  }
}

function setOption(r, key, value) {
  send({ op: "options", code: r.code, options: { [key]: value } });
}

function tag(text) {
  const t = document.createElement("span");
  t.className = "tag";
  t.textContent = text;
  return t;
}

function button(text, onclick, cls = "") {
  const b = document.createElement("button");
  b.textContent = text;
  b.className = "small " + cls;
  b.onclick = onclick;
  return b;
}

async function rendererFor(game) {
  if (!(game in app.renderers)) {
    try { app.renderers[game] = await import(`./games/${game}.js`); }
    catch { app.renderers[game] = generic; }
  }
  return app.renderers[game];
}

async function renderGame(r) {
  const el = $("game");
  const mod = await rendererFor(r.game);
  if (app.room !== r) return;  // a newer update arrived while loading
  if (!r.view) {
    el.className = "game";
    el.innerHTML = `<div class="waiting-msg">${r.is_host ? "坐满（空座位可设为 AI）后点击“开始游戏”。" : "等待房主开始游戏…"}</div>`;
    return;
  }
  const ctx = {
    room: r,
    view: r.view,
    prompt: r.prompt,
    seat: r.my_seat,
    seatName: (i) => r.seats[i]?.name ?? `座位${i + 1}`,
    act: (action) => send({ op: "action", code: r.code, action }),
    toast,
  };
  try {
    mod.render(el, ctx);
  } catch (err) {
    // keep the page usable and make the problem visible instead of a half-drawn table
    console.error("render failed", err);
    toast(`界面出错：${err.message}（刷新页面可恢复）`, true);
  }
}

// ------------------------------------------------------------------ start
const initial = location.hash.slice(1).toUpperCase();
if (/^[A-Z]{4}$/.test(initial)) app.wantRoom = initial;
connect();
