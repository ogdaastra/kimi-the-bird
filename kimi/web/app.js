// Kimi's web page. Reads Kimi's state from this PC and draws Bramblewick.
// Every bit of text from Kimi's world is inserted with textContent (never as HTML).
"use strict";

const $ = (id) => document.getElementById(id);
const store = {
  get() { return sessionStorage.getItem("kimiPass") || localStorage.getItem("kimiPass") || ""; },
  set(v, remember) { sessionStorage.setItem("kimiPass", v); if (remember) localStorage.setItem("kimiPass", v); },
  clear() { sessionStorage.removeItem("kimiPass"); localStorage.removeItem("kimiPass"); },
};
const S = { layout: null, state: null, feed: null, kimi: null, timers: [], requestId: null };
const NEED_COLOURS = { hunger: "--hunger", energy: "--energy", curiosity: "--curiosity", happiness: "--happiness", social: "--social" };
const NEED_NAMES = { hunger: "Hunger", energy: "Energy", curiosity: "Curiosity", happiness: "Happiness", social: "Social" };
const PLACE_COLOURS = { nest: "#7a5236", shrub: "#5d9157", shrine: "#8f978a", square: "#c9bfa9", cafe: "#c0624b", print_shop: "#6a7fa8", library: "#9aa5b5" };

class AuthError extends Error {}

async function api(path, options = {}) {
  const headers = Object.assign({}, options.headers || {}, { Authorization: "Bearer " + store.get() });
  const r = await fetch(path, Object.assign({}, options, { headers, cache: "no-store", credentials: "omit" }));
  if (r.status === 401) { store.clear(); showLogin("That passcode isn't right."); throw new AuthError("auth"); }
  if (r.status === 429) {
    const data = await r.json().catch(() => ({}));
    showLogin(`Too many wrong passcodes. Try again in about ${Math.ceil((data.retryAfter || 60) / 60)} minute(s).`);
    throw new AuthError("locked");
  }
  if (r.status === 503) { showLogin("No passcode is set yet. Set one in Kimi's Settings → Web page."); throw new AuthError("none"); }
  return { status: r.status, data: await r.json() };
}

function showLogin(message) {
  S.timers.forEach(clearInterval); S.timers = [];
  $("app").hidden = true;
  $("login").hidden = false;
  if (message) $("login-msg").textContent = message;
  $("pass").focus();
}

async function start() {
  $("login").hidden = true;
  try {
    S.layout = (await api("/api/layout")).data;
    await refreshState();
    await refreshFeed();
  } catch (e) { if (!(e instanceof AuthError)) console.error(e); return; }
  $("app").hidden = false;
  S.timers.push(setInterval(() => { if (!document.hidden) refreshState().catch(() => {}); }, 2500));
  S.timers.push(setInterval(() => { if (!document.hidden) refreshFeed().catch(() => {}); }, 20000));
  requestAnimationFrame(frame);
}

// -- state ------------------------------------------------------------------------
async function refreshState() {
  const { data } = await api("/api/state");
  S.state = data;
  if (!S.kimi) S.kimi = { x: data.kimi.x, z: data.kimi.z };
  $("status").textContent = data.status;
  $("when").textContent = `Day ${data.day} · ${data.clock} · ${data.weather}`;
  $("where").textContent = data.place ? `at ${data.place}` : "in Bramblewick";
  $("activity").textContent = data.curiosity ? `Looking closely at ${data.curiosity}` : capital(data.activity || "pottering about");
  $("mood").textContent = data.thinking ? "Thinking…" : (data.mood ? `Feeling ${data.mood}` : "");
  const t = $("thought");
  t.hidden = !data.thought.text;
  t.textContent = data.thought.text ? `“${data.thought.text}”` : "";
  renderNeeds(data.needs, data.needLabels);
  renderAsk(data.request);
  const spent = Number(data.spentToday || 0).toFixed(4);
  $("spend").textContent = `AI spending today: $${spent} of $${Number(data.budget || 0).toFixed(2)}`;
}

function renderNeeds(needs, labels) {
  const box = $("needs");
  box.replaceChildren();
  for (const key of Object.keys(NEED_NAMES)) {
    const name = document.createElement("span");
    name.textContent = NEED_NAMES[key];
    const bar = document.createElement("div");
    bar.className = "bar";
    const fill = document.createElement("span");
    fill.style.width = `${Math.max(0, Math.min(100, needs[key] || 0))}%`;
    fill.style.background = `var(${NEED_COLOURS[key]})`;
    bar.appendChild(fill);
    bar.setAttribute("role", "img");
    bar.setAttribute("aria-label", `${NEED_NAMES[key]} ${Math.round(needs[key] || 0)} out of 100`);
    const lab = document.createElement("span");
    lab.className = "lab";
    lab.textContent = (labels && labels[key]) || "";
    box.append(name, bar, lab);
  }
}

function renderAsk(req) {
  const card = $("ask");
  if (!req || req.status !== "open") { card.hidden = true; S.requestId = null; return; }
  if (S.requestId === req.id) return;          // keep whatever the person is typing
  S.requestId = req.id;
  card.hidden = false;
  const wish = req.kind === "artefact";
  $("ask-title").textContent = wish ? `A wish: ${req.title}` : `A question about ${req.title}`;
  $("ask-body").textContent = req.body;
  $("ask-label").textContent = wish ? "A note for Kimi (optional)" : "Your answer";
  $("ask-yes").textContent = wish ? "Add to wishlist" : "Send answer";
  $("ask-text").value = "";
  $("ask-msg").textContent = wish ? "Wishes you agree to go on Kimi's wishlist, to be built into Bramblewick later." : "";
}

async function reply(action) {
  const id = S.requestId;
  if (!id) return;
  const text = $("ask-text").value.trim();
  if (action === "answer" && text.length < 2) { $("ask-msg").textContent = "Write a few words for Kimi first."; return; }
  $("ask-yes").disabled = $("ask-no").disabled = true;
  try {
    const { data } = await api(`/api/requests/${id}`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action, text }),
    });
    $("ask-msg").textContent = data.message;
    if (data.ok) { setTimeout(() => { $("ask").hidden = true; }, 1800); refreshFeed().catch(() => {}); }
  } catch (e) { if (!(e instanceof AuthError)) $("ask-msg").textContent = "Couldn't reach Kimi. Is it running?"; }
  finally { $("ask-yes").disabled = $("ask-no").disabled = false; }
}

// -- feed -------------------------------------------------------------------------
async function refreshFeed() {
  const { data } = await api("/api/feed");
  S.feed = data;
  const ev = $("events");
  ev.replaceChildren(...data.events.map((e) => {
    const li = document.createElement("li");
    const time = document.createElement("time");
    time.textContent = `Day ${e.day} ${e.clock}`;
    li.append(time, document.createTextNode(e.text));
    return li;
  }));
  const diary = $("diary");
  if (data.diary.length) {
    diary.replaceChildren(...data.diary.slice(0, 2).map((d) => {
      const div = document.createElement("div");
      div.className = "diary-entry";
      const h = document.createElement("h3");
      h.textContent = `${d.title} · Day ${d.day}`;
      const p = document.createElement("p");
      p.textContent = d.body;
      div.append(h, p);
      return div;
    }));
  }
  $("curio-count").textContent = `${data.curiosities.seen} of ${data.curiosities.total} curiosities examined.`;
  $("curios").replaceChildren(...data.curiosities.recent.map((c) => {
    const li = document.createElement("li");
    const b = document.createElement("strong");
    b.textContent = c.name;
    li.append(b, document.createTextNode(` (${c.visits}×): ${c.detail}`));
    return li;
  }));
  const board = $("board");
  board.replaceChildren(...(data.board.length ? data.board : [{ author: "", body: "Nothing pinned yet." }]).map((m) => {
    const li = document.createElement("li");
    if (m.author) { const b = document.createElement("strong"); b.textContent = `${m.author}: `; li.append(b); }
    li.append(document.createTextNode(m.body));
    return li;
  }));
}

// -- map --------------------------------------------------------------------------
function frame() {
  if (!$("app").hidden) draw();
  requestAnimationFrame(frame);
}

function draw() {
  const L = S.layout, st = S.state;
  if (!L || !st) return;
  const canvas = $("map");
  const dpr = window.devicePixelRatio || 1;
  const size = canvas.clientWidth;
  if (canvas.width !== Math.round(size * dpr)) { canvas.width = Math.round(size * dpr); canvas.height = Math.round(size * dpr); }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const R = L.islandRadius * 1.08;
  const k = size / (2 * R);
  const P = (x, z) => [size / 2 + x * k, size / 2 + z * k];

  ctx.fillStyle = "#86b9d1";
  ctx.fillRect(0, 0, size, size);
  circle(ctx, ...P(0, 0), L.islandRadius * k + 6, "#e4d5a5");
  circle(ctx, ...P(0, 0), L.islandRadius * k, "#8fbd75");
  circle(ctx, ...P(0, 0), L.townRadius * k, "#a9cc8a");

  ctx.lineCap = "round";
  for (const [w, colour] of [[44, "#bfa678"], [34, "#e8d8b4"]]) {
    ctx.strokeStyle = colour;
    ctx.lineWidth = w * k;
    for (const line of L.paths) {
      ctx.beginPath();
      line.forEach(([x, z], i) => { const [px, py] = P(x, z); if (i) ctx.lineTo(px, py); else ctx.moveTo(px, py); });
      ctx.stroke();
    }
  }
  circle(ctx, ...P(L.square.x, L.square.z), L.square.r * k, "#d3cab8");
  circle(ctx, ...P(L.pond.x, L.pond.z), L.pond.r * k, "#7fb9d6");

  const seen = new Set(st.curiositiesSeen || []);
  for (const c of L.curiosities) {
    const [x, y] = P(c.x, c.z);
    if (x < 0 || y < 0 || x > size || y > size) continue;
    const r = Math.max(3, size / 150);
    ctx.beginPath();
    ctx.moveTo(x, y - r); ctx.lineTo(x + r, y); ctx.lineTo(x, y + r); ctx.lineTo(x - r, y); ctx.closePath();
    ctx.fillStyle = seen.has(c.id) ? "#e8b73a" : "#fbf3df";
    ctx.strokeStyle = "#6b4a33";
    ctx.lineWidth = 1;
    ctx.fill(); ctx.stroke();
  }

  ctx.font = `600 ${Math.max(11, size / 46)}px Georgia, serif`;
  ctx.textAlign = "center";
  for (const p of L.places) {
    const [x, y] = P(p.x, p.z);
    const r = (p.id === "square" ? 0 : 70) * k;
    if (r) circle(ctx, x, y, r, PLACE_COLOURS[p.id] || "#8a7a68");
    const label = p.name;
    const tw = ctx.measureText(label).width + 12;
    const ty = y - r - 10;
    ctx.fillStyle = st.location === p.id ? "#eef5e6" : "rgba(251,243,223,.92)";
    roundRect(ctx, x - tw / 2, ty - 12, tw, 18, 6);
    ctx.fill();
    ctx.strokeStyle = st.location === p.id ? "#3f6e4e" : "#8a6f4f";
    ctx.stroke();
    ctx.fillStyle = "#3a2e24";
    ctx.fillText(label, x, ty + 2);
  }

  // Kimi glides towards where the world says it is.
  const tgt = st.kimi;
  S.kimi.x += (tgt.x - S.kimi.x) * 0.08;
  S.kimi.z += (tgt.z - S.kimi.z) * 0.08;
  const [kx, ky] = P(S.kimi.x, S.kimi.z);
  const kr = Math.max(7, size / 55);
  circle(ctx, kx, ky + kr * 0.9, kr * 0.9, "rgba(0,0,0,.18)");
  circle(ctx, kx, ky, kr, "#7d95b8");
  circle(ctx, kx + kr * 0.25, ky + kr * 0.3, kr * 0.55, "#f6c6a3");
  circle(ctx, kx + kr * 0.35, ky - kr * 0.3, kr * 0.15, "#211b18");
  ctx.strokeStyle = "#ffffff";
  ctx.lineWidth = 2;
  ctx.beginPath(); ctx.arc(kx, ky, kr + 2, 0, Math.PI * 2); ctx.stroke();

  const dark = 1 - Number(st.light || 1);
  if (dark > 0.01) {
    ctx.fillStyle = `rgba(18,24,58,${dark * 0.55})`;
    ctx.fillRect(0, 0, size, size);
  }
}

function circle(ctx, x, y, r, colour) {
  ctx.beginPath(); ctx.arc(x, y, Math.max(0, r), 0, Math.PI * 2); ctx.fillStyle = colour; ctx.fill();
}

function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath();
}

function capital(s) { return s ? s[0].toUpperCase() + s.slice(1) : s; }

// -- wiring -------------------------------------------------------------------------
$("login-form").addEventListener("submit", (e) => {
  e.preventDefault();
  store.set($("pass").value, $("remember").checked);
  $("pass").value = "";
  start();
});
$("ask-yes").addEventListener("click", () => reply(S.requestId && $("ask-yes").textContent.startsWith("Add") ? "wishlist" : "answer"));
$("ask-no").addEventListener("click", () => reply("decline"));
$("logout").addEventListener("click", () => { store.clear(); showLogin("Passcode forgotten on this device."); });

fetch("/api/hello", { cache: "no-store" }).then((r) => r.json()).then((h) => {
  if (!h.passcodeSet) showLogin("No passcode is set yet. Set one in Kimi's Settings → Web page.");
  else if (store.get()) start();
  else showLogin();
}).catch(() => showLogin("Can't reach Kimi. Is it running?"));
