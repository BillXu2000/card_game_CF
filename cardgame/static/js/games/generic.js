// Fallback renderer: works for any game built on the common engine.  Shows
// every zone (hidden cards as backs), public variables, the current prompt
// and lets the player send a raw action.  Useful while developing a game.
import { cardLabel } from "../cards.js";

export function render(el, ctx) {
  const { view, prompt } = ctx;
  el.className = "game generic";
  el.innerHTML = "";

  const zones = document.createElement("div");
  zones.className = "panel";
  zones.innerHTML = "<h3>牌区</h3>";
  for (const [name, z] of Object.entries(view.zones)) {
    const row = document.createElement("div");
    row.className = "zone-row";
    const owner = z.owner == null ? "" : `（${ctx.seatName(z.owner)}）`;
    const label = document.createElement("b");
    label.textContent = `${name}${owner} [${z.cards.length}]：`;
    row.append(label);
    for (const id of z.cards) {
      const c = document.createElement("span");
      c.className = "chip";
      c.textContent = id == null ? "🂠" : cardLabel(view.cards[id]);
      if (id != null) c.title = `#${id}`;
      row.append(c);
    }
    zones.append(row);
  }

  const vars = document.createElement("div");
  vars.className = "panel";
  vars.innerHTML = "<h3>状态</h3><pre></pre>";
  vars.querySelector("pre").textContent = JSON.stringify({ vars: view.vars, private: view.private }, null, 1);

  const act = document.createElement("div");
  act.className = "panel";
  act.innerHTML = "<h3>你的决定</h3><pre></pre><textarea rows=3></textarea><button>发送动作</button>";
  act.querySelector("pre").textContent = prompt ? JSON.stringify(prompt, null, 1) : "（无）";
  const ta = act.querySelector("textarea");
  ta.value = prompt ? JSON.stringify({ type: prompt.type }) : "";
  act.querySelector("button").onclick = () => {
    try { ctx.act(JSON.parse(ta.value)); } catch { ctx.toast("动作不是有效的 JSON", true); }
  };

  el.append(zones, vars, act);
}
