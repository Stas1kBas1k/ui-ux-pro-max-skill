/* Fisch Macro interface. Talks to the Python engine through one bridge call: api(method, args). */
"use strict";

let bridge = null;
let S = null;                 // latest engine state (pushed ~5x a second)
let route = "dashboard";
const views = {};
const $ = (sel, root = document) => root.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function api(method, args = {}) {
  return new Promise((resolve, reject) => {
    bridge.call(method, JSON.stringify(args), (raw) => {
      const r = JSON.parse(raw);
      if (r.error) { toast(r.error, "bad"); reject(new Error(r.error)); } else resolve(r.result);
    });
  });
}

function toast(text, tone = "") {
  const el = document.createElement("div");
  el.className = `toast ${tone}`;
  el.innerHTML = `${icon(tone === "bad" ? "alert" : "info", 18)}<div>${esc(text)}</div>`;
  $("#toasts").appendChild(el);
  setTimeout(() => el.remove(), tone === "bad" ? 6000 : 3500);
}

function ask(title, text, value = "", okLabel = "Save") {
  return new Promise((resolve) => {
    const root = $("#modal-root");
    root.innerHTML = `<div class="modal" role="dialog" aria-modal="true" aria-label="${esc(title)}">
      <h3>${esc(title)}</h3><p class="muted small">${esc(text)}</p>
      <input class="input" id="ask-input" value="${esc(value)}">
      <div class="row" style="justify-content:flex-end;margin-top:18px">
        <button class="btn btn-ghost" id="ask-cancel" type="button">Cancel</button>
        <button class="btn btn-primary" id="ask-ok" type="button">${esc(okLabel)}</button></div></div>`;
    const input = $("#ask-input");
    input.focus(); input.select();
    const done = (v) => { root.innerHTML = ""; resolve(v); };
    $("#ask-cancel").onclick = () => done(null);
    $("#ask-ok").onclick = () => done(input.value.trim() || null);
    input.onkeydown = (e) => { if (e.key === "Enter") done(input.value.trim() || null); if (e.key === "Escape") done(null); };
  });
}

function confirmBox(title, text, okLabel = "Delete") {
  return new Promise((resolve) => {
    const root = $("#modal-root");
    root.innerHTML = `<div class="modal" role="alertdialog" aria-modal="true"><h3>${esc(title)}</h3>
      <p class="muted">${esc(text)}</p><div class="row" style="justify-content:flex-end;margin-top:18px">
      <button class="btn btn-ghost" id="c-no" type="button">Cancel</button>
      <button class="btn btn-danger" id="c-yes" type="button">${esc(okLabel)}</button></div></div>`;
    $("#c-no").onclick = () => { root.innerHTML = ""; resolve(false); };
    $("#c-yes").onclick = () => { root.innerHTML = ""; resolve(true); };
  });
}

/* ------------------------------------------------------------------ navigation */
const NAV = [
  ["dashboard", "Dashboard", "dashboard"], ["library", "Rod Library", "fish"], ["automation", "Automation", "zap"],
  ["profiles", "Profiles", "layers"], ["settings", "Settings", "settings"],
];

function renderNav() {
  $("#nav").innerHTML = NAV.map(([id, label, ic]) =>
    `<button class="nav-item ${route === id ? "active" : ""}" data-go="${id}" type="button" ${route === id ? 'aria-current="page"' : ""}>${icon(ic, 18)}<span>${label}</span></button>`).join("");
}

function go(id) {
  if (bridge) bridge.call("panel.close", "{}", () => {});  // leaving a tool page that was open over the content
  if (views[route] && views[route].leave) views[route].leave();
  route = id;
  renderNav();
  const main = $("#main");
  main.innerHTML = `<div class="page" id="page"></div>`;
  main.scrollTop = 0;
  views[id].render($("#page"));
}

document.addEventListener("click", (e) => {
  const g = e.target.closest("[data-go]");
  if (g) { e.preventDefault(); go(g.dataset.go); }
});

/* ------------------------------------------------------------------ shared bits */
const toneDot = (tone, live = false) => `<span class="dot ${tone} ${live ? "live" : ""}"></span>`;

async function toggleRun() {
  if (!S) return;
  if (S.running) await api("stop"); else {
    const r = await api("start");
    const failed = (r.start_report || []).filter((s) => !s.ok);
    if (!r.running && failed.length) toast(`Could not start: ${failed.map((f) => f.detail || f.stage).join("; ")}`, "bad");
  }
  refreshState();
}

function sideStatus() {
  if (!S) return;
  const tone = S.running ? (S.paused ? "warn" : "ok") : S.status === "Monitoring" ? "busy" : "";
  $("#side-dot").className = `dot ${tone} ${S.running && !S.paused ? "live" : ""}`;
  $("#side-status-title").textContent = S.running ? (S.paused ? "Paused" : S.step) : S.status === "Monitoring" ? "Watching" : "Ready";
  $("#side-status-sub").textContent = S.running ? `${S.hotkeys.stop} to stop` : `${S.hotkeys.start} to start`;
  const b = $("#side-start");
  b.className = `btn btn-block ${S.running ? "btn-danger" : "btn-primary"}`;
  b.innerHTML = S.running ? `${icon("stop", 16)} Stop` : `${icon("play", 16)} Start fishing`;
}
$("#side-start").onclick = () => { bridge.call("panel.close", "{}", () => {}); toggleRun(); };

async function refreshState() {
  S = await api("state");
  sideStatus();
  if (views[route] && views[route].update) views[route].update();
}

/* ------------------------------------------------------------------ fields (editor + settings) */
function fieldHtml(f) {
  let ctl = "";
  const id = `f-${f.path.replace(/\W/g, "-")}`;
  if (f.kind === "bool") {
    ctl = `<label class="switch"><input type="checkbox" id="${id}" data-path="${f.path}" ${f.value ? "checked" : ""} aria-label="${esc(f.label)}"><span></span></label>`;
  } else if (f.kind === "choice" && f.choices && f.choices.length <= 3) {
    ctl = `<div class="seg" role="group" aria-label="${esc(f.label)}">${f.choices.map((c) =>
      `<button type="button" class="${c === f.value ? "on" : ""}" data-path="${f.path}" data-value="${esc(c)}">${esc(choiceLabel(f, c))}</button>`).join("")}</div>`;
  } else if (f.kind === "choice" && f.choices) {
    ctl = `<select class="select" id="${id}" data-path="${f.path}" aria-label="${esc(f.label)}">${f.choices.map((c) =>
      `<option ${c === f.value ? "selected" : ""} value="${esc(c)}">${esc(choiceLabel(f, c))}</option>`).join("")}</select>`;
  } else if (f.kind === "slider") {
    const p = ((f.value - f.min) / (f.max - f.min)) * 100;
    const [lo, hi] = f.ends || ["", ""];
    ctl = `<span class="val">${f.value}</span>${lo ? `<span class="faint small">${esc(lo)}</span>` : ""}<input type="range" id="${id}" min="${f.min}" max="${f.max}" step="1" value="${f.value}" data-path="${f.path}" style="--p:${p}%" aria-label="${esc(f.label)}">${hi ? `<span class="faint small">${esc(hi)}</span>` : ""}`;
  } else if (f.kind === "int" || f.kind === "float") {
    const step = f.step || (f.kind === "int" ? 1 : 0.05);
    ctl = `<input class="input" type="number" id="${id}" style="width:110px;text-align:right" step="${step}" ${f.min != null ? `min="${f.min}"` : ""} ${f.max != null ? `max="${f.max}"` : ""} value="${f.value}" data-path="${f.path}" aria-label="${esc(f.label)}">${f.suffix ? `<span class="faint small">${esc(f.suffix.trim())}</span>` : ""}`;
  } else {
    ctl = `<input class="input" id="${id}" value="${esc(f.value)}" data-path="${f.path}" aria-label="${esc(f.label)}" style="width:160px">`;
  }
  return `<div class="field ${f.kind === "slider" ? "stack" : ""}"><div><div class="field-label">${esc(f.label)}${f.experimental ? ' <span class="tag">Experimental</span>' : ""}</div>${f.help ? `<div class="field-help">${esc(f.help)}</div>` : ""}</div><div class="field-ctl">${ctl}</div></div>`;
}
const cap = (s) => (typeof s === "string" && s.length ? s[0].toUpperCase() + s.slice(1) : s);
const choiceLabel = (f, c) => (f.choice_labels && f.choice_labels[c]) || cap(c);

function bindFields(root, onSet) {
  root.querySelectorAll("[data-path]").forEach((el) => {
    const path = el.dataset.path;
    if (el.tagName === "BUTTON") el.onclick = () => onSet(path, el.dataset.value);
    else if (el.type === "checkbox") el.onchange = () => onSet(path, el.checked);
    else if (el.type === "range") {
      el.oninput = () => { el.style.setProperty("--p", `${((el.value - el.min) / (el.max - el.min)) * 100}%`); el.parentElement.querySelector(".val").textContent = el.value; };
      el.onchange = () => onSet(path, Number(el.value));
    } else if (el.tagName === "SELECT") el.onchange = () => onSet(path, el.value);
    else el.onchange = () => onSet(path, el.type === "number" ? Number(el.value) : el.value);
  });
}

// The configuration of a rod / profile: the basics in plain words, everything else behind one switch.
function configHtml(sch, showAll) {
  const n = sch.sections.reduce((a, x) => a + x.fields.length, 0);
  return `<div class="basics">${sch.basic.map(fieldHtml).join("")}</div>
    <button class="disclose ${showAll ? "open" : ""}" data-all type="button" aria-expanded="${showAll}">${icon("chevronDown", 16)} ${showAll ? "Hide" : "Show"} all settings (${n})</button>
    ${showAll ? sch.sections.map((x) => `<div class="form-section"><div class="section-head"><div class="section-title">${esc(x.title)}</div></div>
      ${x.fields.map(fieldHtml).join("")}</div>`).join('<div style="height:12px"></div>') : ""}`;
}

/* ------------------------------------------------------------------ dashboard */
views.dashboard = {
  render(page) {
    page.innerHTML = `
      <div class="hero">
        <div>
          <div class="hero-state"><span id="d-dot" class="dot"></span><span class="hero-state-label" id="d-state">Ready</span></div>
          <h1 class="hero-title" id="d-title">Ready to fish</h1>
          <div class="hero-sub" id="d-sub"></div>
          <div class="hero-keys" id="d-keys"></div>
        </div>
        <div class="power">
          <button class="power-btn" id="d-power" type="button" aria-label="Start fishing">${icon("play", 44)}</button>
          <div class="power-label" id="d-power-label">Start</div>
          <button class="btn btn-sm btn-ghost" id="d-pause" type="button" hidden>${icon("pause", 15)} Pause</button>
        </div>
      </div>
      <div id="d-banner"></div>
      <div class="tiles" id="d-tiles"></div>
      <div class="section-label">This session</div>
      <div class="stats" id="d-stats"></div>`;
    $("#d-power").onclick = toggleRun;
    $("#d-pause").onclick = async () => { await api("pause"); refreshState(); };
    this.update();
  },
  update() {
    if (!S || !$("#d-title")) return;
    const run = S.running, paused = S.paused;
    $("#d-dot").className = `dot ${run ? (paused ? "warn" : "ok live") : ""}`;
    $("#d-state").textContent = run ? (paused ? "Paused" : "Fishing") : (S.simulated ? "Test mode" : "Ready");
    $("#d-title").textContent = run ? (paused ? "Paused" : S.step) : S.rod.name === "Any rod" ? "Ready to fish"
      : `${S.rod.name}${S.rod.skin !== "Default" ? " · " + S.rod.skin : ""}`;
    $("#d-sub").textContent = S.message || (run ? "Everything runs by itself. Move your mouse into the game only if you want to take over."
      : "Open Roblox, stand at the water with your rod, then press Start.");
    $("#d-keys").innerHTML = `<span class="kbd">${esc(S.hotkeys.start)} start</span><span class="kbd">${esc(S.hotkeys.pause)} pause</span><span class="kbd">${esc(S.hotkeys.stop)} stop</span>`;
    const p = $("#d-power");
    p.classList.toggle("running", run);
    p.innerHTML = icon(run ? "stop" : "play", 44);
    p.setAttribute("aria-label", run ? "Stop fishing" : "Start fishing");
    $("#d-power-label").textContent = run ? "Stop" : "Start";
    $("#d-pause").hidden = !run;
    $("#d-pause").innerHTML = paused ? `${icon("play", 15)} Resume` : `${icon("pause", 15)} Pause`;
    let banner = "";
    const failed = !run && (S.start_report || []).filter((x) => !x.ok && x.stage !== "game focused");
    if (failed && failed.length) banner = `<div class="banner bad">${icon("alert", 18)}<div><b>Fishing did not start:</b> ${failed.map((f) => esc(f.stage + (f.detail ? " - " + f.detail : ""))).join("; ")}</div></div>`;
    else if (S.error) banner = `<div class="banner bad">${icon("alert", 18)}<div>${esc(S.error)}</div></div>`;
    else if (S.observe_only) banner = `<div class="banner info">${icon("eye", 18)}<div>Observe only is on: the macro watches and decides, but sends no input. Turn it off in Settings.</div></div>`;
    else if (S.simulated) banner = `<div class="banner info">${icon("info", 18)}<div>Test mode: the built-in test game is used and nothing is sent to Roblox.</div></div>`;
    $("#d-banner").innerHTML = banner;
    const t = (title, tone, value, detail, extra = "", head = "") => `<div class="tile"><div class="tile-head"><span>${title}</span>${head}</div>
      <div class="tile-value">${toneDot(tone)}<span class="ellipsis">${esc(value)}</span></div><div class="tile-detail">${esc(detail)}</div>${extra}</div>`;
    const tr = S.tracking;
    $("#d-tiles").innerHTML =
      t("Game", S.game.tone, S.game.value, S.game.detail) +
      `<div class="tile"><div class="tile-head"><span>Rod &amp; skin</span><button class="btn btn-sm btn-ghost" data-go="library" type="button">Change</button></div>
        <div class="tile-value" style="margin-top:6px"><span class="rod-art">${rodPic(S.rod.img, S.rod.hue, 30, S.rod.special)}</span><span class="ellipsis">${esc(S.rod.name)}</span></div>
        <div class="tile-detail">${esc(S.rod.skin)} skin · ${esc(S.rod.special ? S.rod.behaviour + " minigame" : "Standard reel")}</div></div>` +
      t("Configuration", "ok", S.profile, "Saved profile in use", "", `<button class="btn btn-sm btn-ghost" data-go="profiles" type="button">Edit</button>`) +
      t("Calibration", S.calibration.tone, S.calibration.value, S.calibration.detail) +
      t("Fish tracking", tr.tone, tr.value, tr.detail, `<div class="meter"><i style="width:${Math.round((tr.level || 0) * 100)}%"></i></div>`) +
      t("Automation", run ? (paused ? "warn" : "ok") : "", run ? S.step : S.status === "Monitoring" ? "Watching" : "Stopped",
        run ? "Running" : "Press Start when Roblox is ready");
    const s = S.session;
    $("#d-stats").innerHTML = [["Caught", s.caught], ["Escaped", s.escaped], ["Per hour", s.per_hour || "-"], ["Time", s.time]]
      .map(([l, v]) => `<div class="stat"><div class="stat-v">${esc(v)}</div><div class="stat-l">${l}</div></div>`).join("");
  },
};

/* ------------------------------------------------------------------ rod library */
views.library = {
  query: "", category: "All", sel: null, draft: null, all: false,
  leave() { document.body.classList.remove("drawer"); },
  render(page) {
    page.innerHTML = `
      <div class="page-head"><div><h1 class="page-title">Rod Library</h1>
        <p class="page-sub">Find your rod, pick its skin and press Use. Every rod keeps its own configuration.</p></div></div>
      <div class="toolbar">
        <label class="search">${icon("search", 17)}<input class="input" id="l-q" placeholder="Search rods" value="${esc(this.query)}" aria-label="Search rods"></label>
        <div class="row" id="l-cats"></div>
      </div>
      <div class="lib" id="l-wrap"><div><div class="faint small" id="l-count" style="margin:-6px 0 10px"></div><div class="rod-grid" id="l-grid"></div></div><div id="l-detail" hidden></div></div>`;
    let t = null;
    $("#l-q").oninput = (e) => { clearTimeout(t); t = setTimeout(() => { this.query = e.target.value; this.load(); }, 120); };
    this.load();
    if (this.sel) this.open(this.sel, this.draft ? this.draft.skin : "Default");
  },
  async load() {
    const r = await api("rods", { query: this.query, category: this.category });
    $("#l-cats").innerHTML = r.categories.map((c) => `<button class="chip ${c === this.category ? "on" : ""}" data-cat="${c}" type="button">${c}</button>`).join("");
    $("#l-cats").querySelectorAll("[data-cat]").forEach((b) => (b.onclick = () => { this.category = b.dataset.cat; this.load(); }));
    $("#l-count").textContent = `${r.count} rod${r.count === 1 ? "" : "s"}`;
    $("#l-q").placeholder = `Search ${r.total || r.count} rods`;
    $("#l-grid").innerHTML = r.rods.length ? r.rods.map((x) => x.group ? `
      <div class="rod group ${x.name === this.sel ? "sel" : ""}" data-rod="${esc(x.name)}" role="button" tabindex="0" aria-label="${esc(x.name)}">
        <span class="group-art">${icon("folder", 24)}<b>${x.count}</b></span>
        <div class="grow"><div class="rod-name ellipsis">${esc(x.name)}</div><div class="rod-sub">${esc(x.behaviour)}</div>
          <div class="rod-tags">${x.configured ? '<span class="tag ok">Configured</span>' : ""}${x.active ? '<span class="tag ok">In use</span>' : ""}
            <button class="tag link" data-cat-go="Basic rods" type="button">See all</button></div></div>
      </div>` : `
      <div class="rod ${x.name === this.sel ? "sel" : ""}" data-rod="${esc(x.name)}" role="button" tabindex="0" aria-label="${esc(x.name)}">
        <span class="rod-art">${rodPic(x.img, x.hue, 52, x.special)}</span>
        <div class="grow"><div class="rod-name ellipsis">${esc(x.name)}</div><div class="rod-sub ellipsis">${esc(x.behaviour)}</div>
          <div class="rod-tags">${x.special ? '<span class="tag accent">Special</span>' : x.support === "needs-footage" ? '<span class="tag warn">Needs clip</span>' : x.custom_ui ? '<span class="tag">Custom UI</span>' : x.tuned ? '<span class="tag">Tuned</span>' : ""}${x.configured ? '<span class="tag ok">Configured</span>' : ""}${x.active ? '<span class="tag ok">In use</span>' : ""}</div></div>
        <button class="star-btn ${x.favourite ? "on" : ""}" data-fav="${esc(x.name)}" type="button" aria-label="Favourite ${esc(x.name)}" aria-pressed="${x.favourite}">${icon("star", 16)}</button>
      </div>`).join("") : `<div class="lib-empty">No rod matches "${esc(this.query)}".</div>`;
    $("#l-grid").querySelectorAll("[data-cat-go]").forEach((b) => (b.onclick = (e) => { e.stopPropagation(); this.category = b.dataset.catGo; this.load(); }));
    $("#l-grid").querySelectorAll("[data-rod]").forEach((el) => {
      el.onclick = (e) => { if (!e.target.closest("[data-fav]") && !e.target.closest("[data-cat-go]")) this.open(el.dataset.rod); };
      el.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); this.open(el.dataset.rod); } };
    });
    $("#l-grid").querySelectorAll("[data-fav]").forEach((b) => (b.onclick = async () => {
      const r2 = await api("rod.favourite", { rod: b.dataset.fav });
      b.classList.toggle("on", r2.favourite); b.setAttribute("aria-pressed", r2.favourite);
      if (this.category === "Favourites") this.load();
    }));
  },
  async open(rod, skin = "Default") {
    this.sel = rod;
    this.draft = await api("rod.open", { rod, skin });
    document.querySelectorAll(".rod").forEach((el) => el.classList.toggle("sel", el.dataset.rod === rod));
    document.body.classList.add("drawer");
    this.renderDetail();
  },
  renderDetail() {
    const d = this.draft, el = $("#l-detail");
    if (!d || !el) return;
    el.hidden = false;
    el.className = "card detail";
    const sch = d.schema;
    const state = !d.saved ? ["dirty", "New configuration - not saved yet"] : d.dirty ? ["dirty", "Unsaved changes"]
      : d.in_use ? ["", `In use · profile "${d.profile}"`] : ["", `Saved · profile "${d.profile}"`];
    const useLabel = !d.saved || d.dirty ? "Save and use" : d.in_use ? "In use" : "Use this rod";
    el.innerHTML = `
      <div class="detail-head"><span class="rod-art">${rodPic(d.img, d.hue, 64, sch.special)}</span>
        <div class="grow"><h2 class="detail-title">${esc(d.rod)}</h2>
          <div class="row small" style="gap:6px 8px;margin-top:6px;flex-wrap:wrap">${sch.special ? `<span class="tag accent">${esc(sch.behaviour)}</span>` : '<span class="tag">Standard reel</span>'}
            <span class="faint">${esc(sch.status_text)}</span></div></div>
        <button class="btn btn-icon btn-ghost" id="l-close" type="button" aria-label="Close">${icon("x", 18)}</button></div>
      ${d.mechanic ? `<div class="mech"><div class="mech-row"><b>In the game</b><span>${esc(d.mechanic.game)}</span></div>
        <div class="mech-row"><b>Player</b><span>${esc(d.mechanic.player)}</span></div>
        <div class="mech-row"><b>Macro</b><span>${esc(d.mechanic.macro)}</span></div>
        ${d.mechanic.notes.map((n) => `<div class="mech-row"><b>Note</b><span>${esc(n)}</span></div>`).join("")}
        <div class="mech-support ${esc(d.mechanic.support)}">${esc(d.mechanic.support_text)}${d.mechanic.availability ? ` · ${esc(d.mechanic.availability)}` : ""}</div></div>` : ""}
      <p class="detail-note">${d.group ? `One setup for all ${d.group_count} rods with the normal catch bar (Carbon Rod, Kings Rod, ...). Rods with their own minigame, custom UI or tuned settings have their own card.` : esc(sch.note)}</p>
      <div class="section-label" style="margin-top:22px">Skin</div>
      <div class="skins">${d.skins.map((s) => `<button class="skin ${s === d.skin ? "on" : ""}" data-skin="${esc(s)}" type="button">${rodArt((d.hue + (s === "Default" ? 0 : hashHue(s))) % 360, 40, sch.special)}<span class="ellipsis" style="max-width:70px">${esc(s)}</span></button>`).join("")}
        <button class="skin" id="l-addskin" type="button"><span class="add">${icon("plus", 18)}</span>Add skin</button></div>
      <div class="section-label" style="margin-top:22px">Configuration</div>
      <div id="l-form">${configHtml(sch, this.all)}</div>
      <div class="detail-foot">
        <div class="save-state ${state[0]}">${state[0] ? toneDot("warn") : toneDot("ok")}${esc(state[1])}</div>
        <button class="btn btn-primary" id="l-use" type="button" ${useLabel === "In use" ? "disabled" : ""}>${icon("check", 16)} ${useLabel}</button>
        <div class="row">
          <button class="btn btn-sm grow" id="l-reset" type="button">${icon("reset", 15)} Recommended</button>
          <button class="btn btn-sm grow" id="l-start" type="button">${icon("play", 15)} Use &amp; start</button>
        </div>
      </div>`;
    $("#l-close").onclick = () => { this.sel = null; this.draft = null; el.hidden = true; document.body.classList.remove("drawer"); document.querySelectorAll(".rod.sel").forEach((r) => r.classList.remove("sel")); };
    el.querySelectorAll("[data-skin]").forEach((b) => (b.onclick = () => this.open(this.sel, b.dataset.skin)));
    $("#l-addskin").onclick = async () => {
      const name = await ask("Add a skin", `Name of the ${d.rod} skin. It gets its own configuration, starting from this rod's settings.`, "", "Add");
      if (name) { this.draft = await api("rod.add_skin", { rod: d.rod, skin: name }); this.renderDetail(); }
    };
    el.querySelector("[data-all]").onclick = () => { this.all = !this.all; this.renderDetail(); };
    bindFields($("#l-form"), async (path, value) => { this.draft = await api("draft.set", { path, value }); this.renderDetail(); });
    $("#l-use").onclick = async () => { this.draft = await api("draft.save", { use: true }); toast(`Using ${d.rod}`); this.renderDetail(); this.load(); refreshState(); };
    $("#l-reset").onclick = async () => { this.draft = await api("draft.reset"); this.renderDetail(); toast("Recommended settings loaded - press Save to keep them"); };
    $("#l-start").onclick = async () => { this.draft = await api("draft.save", { use: true }); await api("start"); go("dashboard"); };
  },
};
// The rod's real picture (downloaded from the Fisch wiki) on a tile in its colour, or the drawn rod art.
function rodPic(img, hue, size, special) {
  if (!img) return rodArt(hue, size, special);
  return `<span class="rod-pic" style="width:${size}px;height:${size}px;--h:${hue}"><img src="${esc(img)}" alt="" loading="lazy" onerror="this.parentNode.outerHTML=rodArt(${+hue || 0}, ${size}, ${!!special})"></span>`;
}
const hashHue = (s) => [...s].reduce((a, c) => (a * 31 + c.charCodeAt(0)) % 360, 7);

/* ------------------------------------------------------------------ automation (simple flow) */
views.automation = {
  render(page) {
    page.innerHTML = `
      <div class="page-head"><div><h1 class="page-title">Automation</h1>
        <p class="page-sub">Five steps from choosing a rod to fishing. Done steps are ticked by themselves.</p></div>
        <button class="btn" id="a-wizard" type="button">${icon("wand", 16)} Guided setup</button></div>
      <div class="flow" id="a-flow"></div>
      <div class="section-label">Check it works</div>
      <div class="tools">
        <button class="tool" id="a-watch" type="button"><span class="tool-ic">${icon("eye", 20)}</span><span><div class="tool-title">Watch the game</div><div class="tool-sub">See what the macro sees, without pressing anything.</div></span></button>
        <button class="tool" id="a-test" type="button"><span class="tool-ic">${icon("activity", 20)}</span><span><div class="tool-title">Test this rod</div><div class="tool-sub" id="a-test-sub">Runs 3 catches in the built-in test game.</div></span></button>
        <button class="tool" data-go="settings" data-tab="diagnostics" type="button"><span class="tool-ic">${icon("monitor", 20)}</span><span><div class="tool-title">Live view</div><div class="tool-sub">Detections and inputs drawn on the game.</div></span></button>
      </div>
      <div class="section-label">Extras</div>
      <div class="tools">
        <button class="tool" data-panel="addons" type="button"><span class="tool-ic">${icon("box", 20)}</span><span><div class="tool-title">Add-ons</div><div class="tool-sub">Totems, potions, Sovereign recharge, appraising.</div></span></button>
        <button class="tool" data-panel="hunts" type="button"><span class="tool-ic">${icon("target", 20)}</span><span><div class="tool-title">Hunts &amp; events</div><div class="tool-sub">Get told when a hunt you follow starts.</div></span></button>
        <button class="tool" data-panel="assistant" type="button"><span class="tool-ic">${icon("sparkles", 20)}</span><span><div class="tool-title">AI assistant</div><div class="tool-sub">Ask about rods, fish and events.</div></span></button>
      </div>`;
    $("#a-wizard").onclick = () => api("wizard");
    $("#a-watch").onclick = async () => { await api("watch"); toast("Watching the game - open the live view to see it"); };
    $("#a-test").onclick = async () => { await api("test_minigame"); $("#a-test-sub").textContent = "Running..."; };
    page.querySelectorAll("[data-panel]").forEach((b) => (b.onclick = () => api("open_panel", { name: b.dataset.panel })));
    page.querySelector('[data-tab="diagnostics"]').addEventListener("click", () => { views.settings.tab = "diagnostics"; });
    this.update();
  },
  update() {
    if (!S || !$("#a-flow")) return;
    if (S.test_result && $("#a-test-sub")) $("#a-test-sub").textContent = S.test_result;
    const rodSet = S.rod.name !== "Any rod";
    const cal = S.calibration;
    const steps = [
      ["Choose your rod", rodSet ? `${S.rod.name}` : "Pick the rod you are holding", rodSet, `<button class="btn btn-sm" data-go="library" type="button">${rodSet ? "Change" : "Choose"}</button>`],
      ["Choose its skin", `${S.rod.skin} skin`, rodSet, `<button class="btn btn-sm" data-go="library" type="button">Change</button>`],
      ["Recommended configuration", `Profile "${S.profile}" is loaded`, rodSet, `<button class="btn btn-sm" data-go="profiles" type="button">Edit</button>`],
      ["Calibrate", cal.detail, cal.value !== "Not calibrated", `<button class="btn btn-sm" id="a-cal" type="button">${S.calibrating ? "Cancel" : "Calibrate"}</button><button class="btn btn-sm btn-ghost" id="a-manual" type="button">By hand</button>`],
      ["Start fishing", S.running ? S.step : "Press Start with Roblox open", S.running, `<button class="btn btn-sm ${S.running ? "btn-danger" : "btn-primary"}" id="a-run" type="button">${S.running ? icon("stop", 15) + " Stop" : icon("play", 15) + " Start"}</button>`],
    ];
    const cur = steps.findIndex((s) => !s[2]);
    $("#a-flow").innerHTML = steps.map((s, i) => `<div class="card step ${s[2] ? "done" : i === cur ? "current" : ""}">
      <div class="step-num">${s[2] ? icon("check", 18) : i + 1}</div>
      <div><div class="step-title">${s[0]}</div><div class="step-detail">${esc(s[1])}</div></div><div class="row">${s[3]}</div></div>`).join("");
    $("#a-cal").onclick = async () => { await api("calibrate"); refreshState(); };
    $("#a-manual").onclick = () => api("calibrate.manual");
    $("#a-run").onclick = toggleRun;
  },
};

/* ------------------------------------------------------------------ profiles (configuration editor) */
views.profiles = {
  sel: null, draft: null, all: false,
  render(page) {
    page.innerHTML = `
      <div class="page-head"><div><h1 class="page-title">Profiles</h1>
        <p class="page-sub">Each profile is a full configuration for one rod (and skin). Edit it here; changes are only kept when you press Save.</p></div>
        <button class="btn" id="p-import" type="button">${icon("upload", 16)} Import</button></div>
      <div class="split"><div class="plist" id="p-list"></div><div id="p-edit"></div></div>`;
    $("#p-import").onclick = async () => { const r = await api("profile.import"); if (r.imported) { toast(`Imported "${r.imported}"`); this.load(); } };
    this.load();
  },
  async load() {
    const r = await api("profiles");
    if (!this.sel || !r.profiles.some((p) => p.name === this.sel)) this.sel = r.active;
    $("#p-list").innerHTML = r.profiles.map((p) => `<button class="pitem ${p.name === this.sel ? "sel" : ""}" data-p="${esc(p.name)}" type="button">
      <span class="rod-art">${rodPic(p.img, p.hue, 40, p.behaviour !== "Standard")}</span>
      <span class="grow"><div class="rod-name ellipsis">${esc(p.name)}</div><div class="rod-sub ellipsis">${esc(p.rod)}${p.skin ? " · " + esc(p.skin) : ""}</div></span>
      ${p.in_use ? '<span class="tag ok">In use</span>' : ""}</button>`).join("");
    $("#p-list").querySelectorAll("[data-p]").forEach((b) => (b.onclick = () => this.open(b.dataset.p)));
    this.open(this.sel);
  },
  async open(name) {
    this.sel = name;
    document.querySelectorAll(".pitem").forEach((el) => el.classList.toggle("sel", el.dataset.p === name));
    this.draft = await api("profile.open", { name });
    this.renderEditor();
  },
  renderEditor() {
    const d = this.draft, el = $("#p-edit");
    if (!d || !el) return;
    el.className = "card editor";
    el.innerHTML = `
      <div class="editor-head"><span class="rod-art">${rodPic(d.img, d.hue, 48, d.schema.special)}</span>
        <div class="grow"><div class="detail-title">${esc(d.profile)}</div>
          <div class="save-state ${d.dirty ? "dirty" : ""}" style="margin-top:3px">${d.dirty ? toneDot("warn") + "Unsaved changes" : esc(d.schema.rod) + (d.in_use ? " · in use" : "")}</div></div>
        <div class="editor-actions">
          ${d.dirty ? `<button class="btn btn-sm btn-ghost" id="e-revert" type="button">Revert</button><button class="btn btn-sm btn-primary" id="e-save" type="button">${icon("check", 15)} Save</button>` :
            d.in_use ? "" : `<button class="btn btn-sm btn-primary" id="e-use" type="button">Use</button>`}
          <button class="btn btn-sm btn-icon" id="e-dup" type="button" aria-label="Duplicate" title="Duplicate">${icon("copy", 16)}</button>
          <button class="btn btn-sm btn-icon" id="e-ren" type="button" aria-label="Rename" title="Rename">${icon("pencil", 16)}</button>
          <button class="btn btn-sm btn-icon" id="e-exp" type="button" aria-label="Export" title="Export">${icon("download", 16)}</button>
          <button class="btn btn-sm btn-icon" id="e-del" type="button" aria-label="Delete" title="Delete" ${d.in_use ? "disabled" : ""}>${icon("trash", 16)}</button>
        </div></div>
      <div class="editor-body">
        <div class="row" style="justify-content:space-between;margin:14px 0 6px"><span class="faint small">${esc(d.schema.note)}</span>
          <button class="btn btn-sm btn-ghost" id="e-rec" type="button">${icon("reset", 15)} Recommended</button></div>
        <div id="e-form">${configHtml(d.schema, this.all)}</div></div>`;
    bindFields($("#e-form"), async (path, value) => { this.draft = await api("draft.set", { path, value }); this.renderEditor(); });
    el.querySelector("[data-all]").onclick = () => { this.all = !this.all; this.renderEditor(); };
    const on = (id, fn) => { const b = $(id); if (b) b.onclick = fn; };
    on("#e-save", async () => { this.draft = await api("draft.save", { use: false }); toast("Saved"); this.renderEditor(); refreshState(); });
    on("#e-revert", async () => { this.draft = await api("draft.revert"); this.renderEditor(); });
    on("#e-use", async () => { await api("profile.use", { name: d.profile }); this.load(); refreshState(); });
    on("#e-rec", async () => { this.draft = await api("draft.reset"); this.renderEditor(); });
    on("#e-dup", async () => { const n = await ask("Duplicate profile", "Name of the copy", `${d.profile} copy`, "Duplicate"); if (n) { await api("profile.duplicate", { name: d.profile, new: n }); this.sel = n; this.load(); } });
    on("#e-ren", async () => { const n = await ask("Rename profile", "New name", d.profile, "Rename"); if (n && n !== d.profile) { await api("profile.rename", { name: d.profile, new: n }); this.sel = n; this.load(); refreshState(); } });
    on("#e-exp", async () => { const r = await api("profile.export", { name: d.profile }); if (r.path) toast(`Exported to ${r.path}`); });
    on("#e-del", async () => { if (await confirmBox("Delete profile", `Delete "${d.profile}"? This cannot be undone.`)) { await api("profile.delete", { name: d.profile }); this.sel = null; this.load(); } });
  },
};

/* ------------------------------------------------------------------ settings */
views.settings = {
  tab: "general", timer: null, listening: null,
  render(page) {
    const tabs = [["general", "General"], ["hotkeys", "Hotkeys"], ["diagnostics", "Diagnostics"], ["tools", "Tools"], ["licence", "Licence"], ["about", "About"]];
    page.innerHTML = `<div class="page-head"><div><h1 class="page-title">Settings</h1>
      <p class="page-sub">How the app behaves. Settings for a rod are in its profile.</p></div></div>
      <div class="tabs" role="tablist">${tabs.map(([id, l]) => `<button class="tab ${id === this.tab ? "on" : ""}" data-tab="${id}" role="tab" aria-selected="${id === this.tab}" type="button">${l}</button>`).join("")}</div>
      <div id="s-body"></div>`;
    page.querySelectorAll("[data-tab]").forEach((b) => (b.onclick = () => { this.leave(); this.tab = b.dataset.tab; this.render(page); }));
    this[this.tab]($("#s-body"));
  },
  leave() { if (this.timer) { clearInterval(this.timer); this.timer = null; api("diagnostics.stop"); } },
  async general(body) {
    const r = await api("settings");
    body.innerHTML = `<div class="cols">${r.sections.map((s) => `<div class="card pad"><div class="section-title" style="margin-bottom:6px">${esc(s.title)}</div>${s.fields.map(fieldHtml).join("")}</div>`).join("")}</div>`;
    bindFields(body, async (path, value) => { await api("settings.set", { path, value }); toast("Saved"); refreshState(); });
  },
  async hotkeys(body) {
    const r = await api("settings");
    const names = { start: "Start / resume", pause: "Pause", stop: "Emergency stop", overlay: "Debug overlay", calibrate: "Calibration", snapshot: "Diagnostic snapshot" };
    body.innerHTML = `<div class="card pad" style="max-width:640px">${Object.entries(r.hotkeys).map(([k, v]) => `<div class="field"><div><div class="field-label">${names[k] || k}</div></div>
      <div class="field-ctl"><button class="keycap" data-key="${k}" type="button">${esc(v.toUpperCase())}</button></div></div>`).join("")}
      ${r.hotkey_warnings.map((w) => `<div class="banner warn">${icon("alert", 18)}<div>${esc(w)}</div></div>`).join("")}
      <p class="faint small" style="margin-top:14px">Click a key, then press the new key. Esc cancels.</p></div>`;
    body.querySelectorAll("[data-key]").forEach((b) => (b.onclick = () => {
      body.querySelectorAll(".keycap").forEach((x) => x.classList.remove("listening"));
      b.classList.add("listening"); b.textContent = "Press a key";
      const handler = async (e) => {
        e.preventDefault(); document.removeEventListener("keydown", handler, true);
        if (e.key === "Escape") { this.hotkeys(body); return; }
        const parts = [e.ctrlKey && "ctrl", e.altKey && "alt", e.shiftKey && !["Shift"].includes(e.key) && "shift"].filter(Boolean);
        let k = e.key.length === 1 ? e.key.toLowerCase() : e.key.toLowerCase();
        if (["control", "alt", "shift"].includes(k)) return;
        await api("hotkey.set", { action: b.dataset.key, key: [...parts, k].join("+") }).catch(() => null);
        this.hotkeys(body);
      };
      document.addEventListener("keydown", handler, true);
    }));
  },
  diagnostics(body) {
    body.innerHTML = `<div class="cols" style="grid-template-columns:minmax(0,1.6fr) minmax(0,1fr)">
      <div class="card pad"><div class="row" style="justify-content:space-between;margin-bottom:12px"><div class="section-title">Live view</div><span class="faint small" id="g-fps"></span></div>
        <div class="row" style="gap:10px;margin-bottom:12px;flex-wrap:wrap"><span class="small muted">Test a rod mechanic</span>
          <select class="select" id="g-mech" aria-label="Rod mechanic to test" style="width:auto"></select>
          <span class="small" id="g-mech-seen"></span></div>
        <div class="liveview" id="g-live">Start fishing or press "Watch the game" to see the live view.</div>
        <p class="faint small" style="margin:10px 0 0">Blue: catch bar · red: fish · cyan circles: falling objects (time to land) · yellow ring: next Stellarwave sign · green arc: Lullaby lit part · orange ticks: MiguRod marks.</p></div>
      <div class="flow"><div class="card pad"><div class="section-title" style="margin-bottom:10px">Now</div><dl class="kv" id="g-now"></dl></div>
        <div class="card pad"><div class="section-title" style="margin-bottom:8px">Last inputs</div><div class="log" id="g-inputs"></div></div>
        <div class="card pad"><div class="section-title" style="margin-bottom:8px">Rod minigame</div><div class="log" id="g-mini"></div></div></div></div>`;
    let mechFilled = false;
    const tick = async () => {
      const d = await api("diagnostics", { image: true });
      if (!mechFilled && d.mechanics) {
        mechFilled = true;
        const sel = $("#g-mech");
        sel.innerHTML = d.mechanics.map((m) => `<option value="${esc(m.kind)}" ${m.kind === d.mechanic ? "selected" : ""}>${esc(m.label)}</option>`).join("");
        sel.onchange = async () => { await api("diagnostics.mechanic", { kind: sel.value });
          toast(sel.value ? "Watching that mechanic - play a catch by hand; nothing is sent to the game" : "Mechanic test off"); };
      }
      $("#g-mech-seen").textContent = d.mechanic_seen || "";
      if (d.image) $("#g-live").innerHTML = `<img alt="Live view of the game with detections" src="${d.image}">`;
      $("#g-fps").textContent = d.fps ? `${d.fps} fps · ${d.vision_ms} ms per frame` : "";
      const t = d.tracking;
      $("#g-now").innerHTML = [["State", d.state], ["Fish", t.usable ? `${t.fish} · moving ${t.direction}` : "-"], ["Confidence", t.usable ? `${Math.round(t.confidence * 100)}%${t.coasting ? " (bridging)" : ""}` : "-"],
        ["Wrong detections ignored", t.ignored], ["Error", d.error || "none"]].map(([k, v]) => `<dt>${k}</dt><dd>${esc(v)}</dd>`).join("");
      $("#g-inputs").innerHTML = d.inputs.length ? d.inputs.map((i) => `<div>${esc(i.ago)}s ago · ${esc(i.what)}${i.sent ? "" : ` <span style="color:var(--warn)">not sent: ${esc(i.error)}</span>`}</div>`).join("") : '<div class="faint">No input yet</div>';
      $("#g-mini").innerHTML = d.minigame_log.length ? d.minigame_log.map((l) => `<div>${esc(l)}</div>`).join("") : '<div class="faint">Nothing yet</div>';
    };
    tick();
    this.timer = setInterval(() => { if ($("#g-live")) tick(); }, 300);
  },
  tools(body) {
    const items = [["vision", "eye", "Vision & calibration", "Regions, colours, templates and the calibration tools."],
      ["logs", "folder", "Logs & statistics", "Catch history, logs and the diagnostics export."],
      ["addons", "box", "Add-ons", "Totems, potions, Sovereign recharge, appraising."], ["hunts", "target", "Hunts", "Hunt and event alerts."],
      ["assistant", "sparkles", "AI assistant", "Questions and reading the game screen (needs an API key)."]];
    body.innerHTML = `<div class="tools">${items.map(([id, ic, t, s]) => `<button class="tool" data-panel="${id}" type="button"><span class="tool-ic">${icon(ic, 20)}</span><span><div class="tool-title">${t}</div><div class="tool-sub">${s}</div></span></button>`).join("")}</div>
      <p class="faint small" style="margin-top:14px">These open right here; Back or Esc returns.</p>`;
    body.querySelectorAll("[data-panel]").forEach((b) => (b.onclick = () => api("open_panel", { name: b.dataset.panel })));
  },
  async licence(body) {
    const l = await api("licence");
    body.innerHTML = `<div class="card pad" style="max-width:640px"><div class="row"><span class="tool-ic">${icon("shield", 20)}</span>
      <div><div class="section-title">${l.state === "development" ? "Development build" : esc(cap(l.state))}</div><div class="muted small">${esc(l.message)}</div></div></div>
      <div class="field" style="margin-top:12px"><div><div class="field-label">Licence key</div><div class="field-help">Paid licences will be activated here, one device per key.</div></div>
        <div class="field-ctl"><input class="input" id="lic-key" placeholder="XXXX-XXXX-XXXX" style="width:200px"><button class="btn btn-sm" id="lic-go" type="button">Activate</button></div></div>
      <div class="field"><div><div class="field-label">This device</div><div class="field-help">An anonymous id; the parts it is made from never leave this PC.</div></div><div class="field-ctl faint small">${esc(l.device_id.slice(0, 12))}...</div></div></div>`;
    $("#lic-go").onclick = async () => { const r = await api("licence.activate", { key: $("#lic-key").value }); toast(r.message); };
  },
  async about(body) {
    const a = await api("about");
    body.innerHTML = `<div class="card pad" style="max-width:640px"><div class="row"><img src="logo.svg" width="56" height="56" alt="" style="border-radius:14px">
      <div><div class="detail-title">${esc(a.name)}</div><div class="muted small">Version ${esc(a.version)}</div></div></div>
      <p class="muted" style="margin-top:16px">An external helper for Roblox Fisch: it looks at the screen and sends normal mouse and keyboard input, like a player. It never reads or changes game memory and never talks to Roblox servers.</p>
      <dl class="kv" style="margin-top:12px"><dt>Settings and profiles</dt><dd>${esc(a.data_dir)}</dd></dl></div>`;
  },
};

/* ------------------------------------------------------------------ boot */
function boot() {
  renderNav();
  go("dashboard");
  refreshState();
  bridge.stateChanged.connect((raw) => { S = JSON.parse(raw); sideStatus(); if (views[route].update) views[route].update(); });
  bridge.notice.connect((title, text) => toast(text));
  api("about").then((a) => ($("#brand-version").textContent = `Version ${a.version}`));
  document.addEventListener("keydown", (e) => {
    if (e.ctrlKey && e.key >= "1" && e.key <= "5") { go(NAV[+e.key - 1][0]); e.preventDefault(); }
  });
}

new QWebChannel(qt.webChannelTransport, (channel) => { bridge = channel.objects.bridge; boot(); });
