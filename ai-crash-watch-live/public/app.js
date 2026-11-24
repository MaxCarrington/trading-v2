// The page: listens to the server's event stream and redraws the part that changed.

const $ = (id) => document.getElementById(id);
const LABEL = { red: "Flashing", amber: "Early", green: "Calm", grey: "Waiting" };
let state = null;
let snapshot = { signals: [], events: [] };

const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const pill = (s) => `<span class="pill ${s}">${LABEL[s] || s}</span>`;
const fmtDate = (d) => (d ? new Date(d.length === 10 ? d + "T00:00:00" : d).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" }) : "–");
const daysUntil = (d) => Math.round((new Date(d + "T00:00:00") - new Date(new Date().toDateString())) / 864e5);

// ---- Drawing ----
const signed = (v, d = 1) => (v == null ? "–" : `${v >= 0 ? "+" : ""}${v.toFixed(d)}%`);
const tone = (v) => (v == null ? "" : v >= 0 ? "up" : "down");
const money = (v, cur) => {
  if (v == null) return "–";
  if (cur === "GBp") return v.toFixed(0) + "p";
  return (cur === "GBP" ? "£" : cur === "EUR" ? "€" : "$") + v.toFixed(2);
};

// Six months of closes as a small line, coloured by the stock's trend.
function spark(values, color) {
  if (!values || values.length < 2) return "";
  const w = 120, h = 28, min = Math.min(...values), max = Math.max(...values), span = max - min || 1;
  const pts = values.map((v, i) => `${((i / (values.length - 1)) * w).toFixed(1)},${(h - 2 - ((v - min) / span) * (h - 4)).toFixed(1)}`).join(" ");
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" aria-hidden="true"><polyline points="${pts}" fill="none" stroke="var(--${color === "grey" ? "muted" : color})" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/></svg>`;
}

function stockRow(sym, s) {
  const vs50 = s.sma50 ? ((s.price - s.sma50) / s.sma50) * 100 : null;
  const vs200 = s.sma200 ? ((s.price - s.sma200) / s.sma200) * 100 : null;
  return `<tr data-sym="${esc(sym)}">`
    + `<td><span class="num">${esc(sym)}</span> <span class="muted small">${esc(s.name)}</span></td>`
    + `<td class="num">${money(s.price, s.currency)}</td>`
    + `<td class="num ${tone(s.changePct)}">${signed(s.changePct, 2)}</td>`
    + `<td><span class="pill ${s.trendColor}">${esc(s.trend)}</span></td>`
    + `<td class="num ${tone(vs50)}">${signed(vs50)}</td>`
    + `<td class="num ${tone(vs200)}">${signed(vs200)}</td>`
    + `<td class="num ${s.fromHighPct != null && s.fromHighPct <= -20 ? "down" : ""}">${s.fromHighPct == null ? "–" : s.fromHighPct.toFixed(1) + "%"}</td>`
    + `<td class="num ${tone(s.ret1m)}">${signed(s.ret1m)}</td>`
    + `<td class="num ${tone(s.ret3m)}">${signed(s.ret3m)}</td>`
    + `<td>${spark(s.spark, s.trendColor)}</td>`
    + `<td class="num small muted">${s.at ? new Date(s.at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "–"}</td></tr>`;
}

function drawStocks(changed) {
  if (changed) {
    // Only redraw the rows that moved, then flash them.
    for (const sym of changed) {
      const row = document.querySelector(`tr[data-sym="${sym}"]`);
      if (!row) continue;
      row.outerHTML = stockRow(sym, state.stocks[sym]);
      document.querySelector(`tr[data-sym="${sym}"]`)?.classList.add("flash");
    }
    return drawTrendSummary();
  }
  let group = null;
  $("stocks").innerHTML = Object.entries(state.stocks).map(([sym, s]) => {
    const head = s.group !== group ? `<tr class="group"><td colspan="11">${esc((group = s.group))}</td></tr>` : "";
    return head + stockRow(sym, s);
  }).join("");
  drawTrendSummary();
}

function drawTrendSummary() {
  const all = Object.values(state.stocks).filter((s) => s.trendColor !== "grey");
  const broken = all.filter((s) => s.trendColor === "red").length;
  $("trend-summary").textContent = all.length ? `${broken} of ${all.length} are below their 200-day line or in a death cross.` : "Loading price history…";
}

function drawIndicators() {
  // Labels and rules come with the state so rules.js stays the only place they live.
  $("indicators").innerHTML = (state.indicatorInfo || []).map((r) => {
    const ind = state.indicators[r.id];
    return `<tr><td>${esc(r.label)}</td><td class="num">${ind.value == null ? "–" : ind.value + " " + esc(r.unit)}</td>`
      + `<td class="small">${esc(r.explain)}</td><td>${pill(ind.status)}</td><td class="num small">${fmtDate(ind.date)}</td></tr>`;
  }).join("");
}

function drawSnapshot() {
  $("snap-date").textContent = fmtDate(snapshot.updated);
  $("snapshot").innerHTML = snapshot.signals.map((s) =>
    `<tr><td>${esc(s.label)}</td><td class="num">${esc(s.value)}</td><td class="small">${esc(s.compare)}</td><td>${pill(s.status)}</td><td class="num small">${fmtDate(s.asOf)}</td></tr>`).join("");
  $("events").innerHTML = snapshot.events.map((e) => {
    const k = daysUntil(e.date);
    return `<tr><td class="num small">${fmtDate(e.date)}</td><td class="num small">${k < 0 ? "past" : k === 0 ? "today" : k + "d"}</td><td>${esc(e.event)}</td><td class="small">${esc(e.watch)}</td></tr>`;
  }).join("");
}

function drawFilings() {
  $("filings").innerHTML = state.filings.length
    ? state.filings.map((f) => `<tr><td class="num small">${fmtDate(f.date)}</td><td class="num">${esc(f.ticker)}</td><td><a href="${esc(f.url)}" target="_blank" rel="noopener">${esc(f.form)}</a></td></tr>`).join("")
    : `<tr><td colspan="3" class="muted small">Waiting for the first check.</td></tr>`;
}

function drawAlerts() {
  if (!state.alerts.length) return;
  $("alerts").innerHTML = state.alerts.map((a) =>
    `<li><time>${new Date(a.at).toLocaleTimeString()}</time>${pill(a.level)}<span>${esc(a.text)}</span></li>`).join("");
}

function drawSummary() {
  const all = [...snapshot.signals.map((s) => s.status), ...Object.values(state.indicators).map((i) => i.status)];
  const n = (s) => all.filter((x) => x === s).length;
  $("n-red").textContent = n("red");
  $("n-amber").textContent = n("amber");
  $("n-green").textContent = n("green");
  $("takeaway").textContent = `${n("red")} flashing, ${n("amber")} early, ${n("green")} calm. `
    + (n("red") >= 3 ? "Crash conditions are building; watch the triggers for a turn." : "Most signals are calm.");
  $("feeds").innerHTML = Object.entries(state.sources).map(([k, v]) => `<span>${k}: ${esc(v)}</span>`).join("");
  $("demo-banner").hidden = state.mode !== "demo";
}

function drawAll() {
  drawStocks(); drawIndicators(); drawFilings(); drawAlerts(); drawSummary();
}

// ---- Desktop notifications ----
$("notify").addEventListener("click", async () => {
  if (!("Notification" in window)) return ($("notify").textContent = "Not supported in this browser");
  const p = await Notification.requestPermission();
  $("notify").textContent = p === "granted" ? "Desktop alerts on" : "Alerts blocked in browser settings";
});
if ("Notification" in window && Notification.permission === "granted") $("notify").textContent = "Desktop alerts on";

// ---- The event stream ----
function connect() {
  const es = new EventSource("/events");
  es.onopen = () => { $("conn").textContent = "Live"; $("conn").className = "conn on"; };
  es.onerror = () => { $("conn").textContent = "Reconnecting…"; $("conn").className = "conn off"; }; // EventSource retries by itself

  es.addEventListener("state", (e) => { state = JSON.parse(e.data); drawAll(); });
  es.addEventListener("ticks", (e) => {
    const ticks = JSON.parse(e.data);
    Object.assign(state.stocks, ticks);
    drawStocks(Object.keys(ticks));
  });
  es.addEventListener("indicator", (e) => {
    const { id, ...ind } = JSON.parse(e.data);
    state.indicators[id] = ind;
    drawIndicators(); drawSummary();
  });
  es.addEventListener("filings", (e) => { state.filings = JSON.parse(e.data); drawFilings(); });
  es.addEventListener("sources", (e) => { state.sources = JSON.parse(e.data); drawSummary(); });
  es.addEventListener("alert", (e) => {
    const a = JSON.parse(e.data);
    state.alerts.unshift(a);
    drawAlerts();
    if ("Notification" in window && Notification.permission === "granted") new Notification("AI Crash Watch", { body: a.text });
  });
}

fetch("/snapshot.json").then((r) => r.json()).then((s) => { snapshot = s; drawSnapshot(); if (state) drawSummary(); }).catch(() => {});
connect();
