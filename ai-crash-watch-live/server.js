// AI Crash Watch: a small event-driven server.
//
//   Data sources ──► server (this file) ──► your browser page (public/index.html)
//
// 1. Finnhub WebSocket streams stock trades the moment they happen.
// 2. FRED (economic data) and SEC EDGAR (company filings) are checked on a timer,
//    because they only change when something is published.
// 3. Every new value is run through rules.js. A rule that changes colour, or a
//    big stock drop, or a new filing, becomes an "alert".
// 4. The page keeps one Server-Sent Events connection open to /events and
//    updates itself whenever the server sends something.
//
// Run:  npm start        (real data, needs keys in .env)
//       npm run demo     (made-up data, no keys needed)

import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { INDICATORS, WATCHLIST, STOCKS, stockAlert, trend, FILERS, FILING_FORMS } from "./rules.js";

const DIR = path.dirname(fileURLToPath(import.meta.url));
const DEMO = process.argv.includes("--demo");
const PORT = Number(process.env.PORT) || 3000;
const FINNHUB_KEY = process.env.FINNHUB_KEY || "";
const FRED_KEY = process.env.FRED_KEY || "";
const SEC_EMAIL = process.env.SEC_CONTACT_EMAIL || "";

const FRED_EVERY_MIN = 15;
const EDGAR_EVERY_MIN = 10;
const HISTORY_EVERY_HOURS = 6; // daily price history for the 50/200-day lines, highs and returns
const POLL_EVERY_MIN = 2;      // London funds (and everything, if there is no Finnhub key)

// ---------------------------------------------------------------------------
// State: everything the page shows. Sent in full when a page connects.
// ---------------------------------------------------------------------------
const state = {
  mode: DEMO ? "demo" : "live",
  startedAt: new Date().toISOString(),
  stocks: Object.fromEntries(WATCHLIST.map((w) => [w.symbol, {
    name: w.name, group: w.group, currency: null, price: null, prevClose: null, changePct: null, at: null,
    sma50: null, sma200: null, high52: null, fromHighPct: null, ret1m: null, ret3m: null,
    trend: "Waiting", trendColor: "grey", spark: [],
  }])),
  indicators: Object.fromEntries(INDICATORS.map((i) => [i.id, { value: null, date: null, status: "grey" }])),
  indicatorInfo: INDICATORS.map(({ id, label, unit, explain }) => ({ id, label, unit, explain })),
  filings: [],
  alerts: [],
  sources: { finnhub: "off", yahoo: "off", fred: "off", edgar: "off" },
};
const alertedToday = new Set(); // stops the same stock alert repeating all day

function log(...args) {
  console.log(new Date().toLocaleTimeString(), ...args);
}

// ---------------------------------------------------------------------------
// Pushing events to every open page (Server-Sent Events)
// ---------------------------------------------------------------------------
const clients = new Set();

function send(event, data) {
  const msg = `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
  for (const res of clients) res.write(msg);
}

function setSource(name, status) {
  if (state.sources[name] === status) return;
  state.sources[name] = status;
  send("sources", state.sources);
}

function raise(level, text, source) {
  const alert = { id: Date.now() + Math.random(), at: new Date().toISOString(), level, text, source };
  state.alerts.unshift(alert);
  state.alerts = state.alerts.slice(0, 50);
  log(`ALERT [${level}] ${text}`);
  send("alert", alert);
}

// ---------------------------------------------------------------------------
// Stocks: live price from Finnhub, daily history and London funds from Yahoo Finance
// ---------------------------------------------------------------------------
const pendingTicks = new Map();
const RANK = { grey: 0, green: 1, amber: 2, red: 3 };
const pct = (a, b) => (a && b ? ((a - b) / b) * 100 : null);

// Work out everything that depends on the latest price.
function recompute(symbol) {
  const s = state.stocks[symbol];
  s.changePct = pct(s.price, s.prevClose);
  s.fromHighPct = s.high52 ? pct(s.price, Math.max(s.high52, s.price)) : null;
  const [label, color] = trend(s.price, s.sma50, s.sma200);
  const before = s.trendColor;
  s.trend = label;
  s.trendColor = color;

  const day = new Date().toDateString();
  if (before !== "grey" && RANK[color] > RANK[before] && !alertedToday.has(symbol + label + day)) {
    alertedToday.add(symbol + label + day);
    raise(color, `${symbol} (${s.name}) trend changed to ${label}`, "stocks");
  }
  if (s.changePct != null) {
    const msg = stockAlert(symbol, s.changePct);
    if (msg && !alertedToday.has(symbol + "drop" + day)) {
      alertedToday.add(symbol + "drop" + day);
      raise("red", msg, "stocks");
    }
  }
}

function updatePrice(symbol, price, at = Date.now()) {
  const s = state.stocks[symbol];
  if (!s || !price) return;
  s.price = price;
  s.at = at;
  recompute(symbol);
  pendingTicks.set(symbol, s);
}

// Trades can arrive hundreds of times a second; send the page one batch a second.
setInterval(() => {
  if (!pendingTicks.size) return;
  send("ticks", Object.fromEntries(pendingTicks));
  pendingTicks.clear();
}, 1000);

// Fill in the slow-moving numbers from a list of daily closes (oldest first).
function applyHistory(symbol, closes, currency) {
  const s = state.stocks[symbol];
  const avg = (n) => (closes.length >= n ? closes.slice(-n).reduce((a, b) => a + b, 0) / n : null);
  const ago = (n) => (closes.length > n ? closes[closes.length - 1 - n] : null);
  s.currency = currency || s.currency;
  s.sma50 = avg(50);
  s.sma200 = avg(200);
  s.high52 = Math.max(...closes.slice(-252));
  s.ret1m = pct(closes[closes.length - 1], ago(21));
  s.ret3m = pct(closes[closes.length - 1], ago(63));
  s.spark = closes.slice(-126).filter((_, i, arr) => i % 2 === 0 || i === arr.length - 1).map((v) => +v.toFixed(2));
  recompute(symbol);
  pendingTicks.set(symbol, s);
}

// Yahoo Finance's chart data. Free and keyless, but unofficial: if Yahoo changes it, this is the bit to fix.
async function yahooChart(ticker) {
  const r = await fetch(`https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(ticker)}?range=1y&interval=1d`, {
    headers: { "User-Agent": "Mozilla/5.0 (AI Crash Watch)" },
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  const res = (await r.json()).chart?.result?.[0];
  if (!res) throw new Error("no data returned");
  const days = res.timestamp.map((t, i) => ({ day: new Date(t * 1000).toISOString().slice(0, 10), close: res.indicators.quote[0].close[i] }))
    .filter((d) => d.close != null);
  const today = new Date(res.meta.regularMarketTime * 1000).toISOString().slice(0, 10);
  const done = days.filter((d) => d.day < today); // completed trading days only
  return {
    closes: done.map((d) => d.close),
    prevClose: done.at(-1)?.close,
    price: res.meta.regularMarketPrice,
    at: res.meta.regularMarketTime * 1000,
    currency: res.meta.currency,
  };
}

async function loadHistory() {
  let ok = 0;
  for (const w of WATCHLIST) {
    try {
      const h = await yahooChart(w.yahoo);
      state.stocks[w.symbol].prevClose = h.prevClose;
      applyHistory(w.symbol, h.closes, h.currency);
      if (!state.stocks[w.symbol].price || !w.stream || !FINNHUB_KEY) updatePrice(w.symbol, h.price, h.at);
      ok++;
    } catch (e) {
      log(`History ${w.symbol} failed: ${e.message}`);
    }
    await new Promise((res) => setTimeout(res, 300));
  }
  setSource("yahoo", ok ? "live" : "error");
}

// Funds Finnhub can't stream (and everything, without a Finnhub key) are checked every few minutes.
async function pollYahoo() {
  for (const w of WATCHLIST) {
    if (w.stream && FINNHUB_KEY) continue;
    try {
      const h = await yahooChart(w.yahoo);
      state.stocks[w.symbol].prevClose = h.prevClose;
      updatePrice(w.symbol, h.price, h.at);
    } catch (e) {
      log(`Price ${w.symbol} failed: ${e.message}`);
    }
    await new Promise((res) => setTimeout(res, 300));
  }
}

function connectFinnhub() {
  const ws = new WebSocket(`wss://ws.finnhub.io?token=${FINNHUB_KEY}`);
  ws.addEventListener("open", () => {
    log("Finnhub stream connected");
    setSource("finnhub", "live");
    for (const w of WATCHLIST) if (w.stream) ws.send(JSON.stringify({ type: "subscribe", symbol: w.symbol }));
  });
  ws.addEventListener("message", (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === "trade") for (const t of msg.data) updatePrice(t.s, t.p, t.t);
    if (msg.type === "error") log("Finnhub says:", msg.msg);
  });
  ws.addEventListener("close", () => {
    setSource("finnhub", "reconnecting");
    log("Finnhub stream closed, reconnecting in 10s");
    setTimeout(connectFinnhub, 10_000);
  });
  ws.addEventListener("error", () => {}); // "close" follows and handles it
}

// ---------------------------------------------------------------------------
// FRED economic data
// ---------------------------------------------------------------------------
function setIndicator(rule, value, date) {
  const ind = state.indicators[rule.id];
  const before = ind.status;
  ind.value = value;
  ind.date = date;
  ind.status = rule.status(value);
  const rank = { grey: 0, green: 1, amber: 2, red: 3 };
  if (before !== "grey" && rank[ind.status] > rank[before]) {
    raise(ind.status, `${rule.label} moved to ${ind.status.toUpperCase()}: ${value} ${rule.unit}`, "fred");
  }
  send("indicator", { id: rule.id, ...ind });
}

async function pollFred() {
  let ok = 0;
  for (const rule of INDICATORS) {
    try {
      const url = `https://api.stlouisfed.org/fred/series/observations?series_id=${rule.id}&api_key=${FRED_KEY}&file_type=json&sort_order=desc&limit=10`;
      const r = await fetch(url);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const obs = (await r.json()).observations.find((o) => o.value !== ".");
      if (!obs) throw new Error("no recent value");
      const ind = state.indicators[rule.id];
      if (ind.date !== obs.date || ind.value !== Number(obs.value)) setIndicator(rule, Number(obs.value), obs.date);
      ok++;
    } catch (e) {
      log(`FRED ${rule.id} failed: ${e.message}`);
    }
  }
  setSource("fred", ok ? "live" : "error");
}

// ---------------------------------------------------------------------------
// SEC EDGAR filings
// ---------------------------------------------------------------------------
const seenFilings = new Set();
let ciks = null;
const secHeaders = () => ({ "User-Agent": `AI Crash Watch ${SEC_EMAIL}` });

async function loadCiks() {
  const r = await fetch("https://www.sec.gov/files/company_tickers.json", { headers: secHeaders() });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  const all = Object.values(await r.json());
  ciks = {};
  for (const t of FILERS) {
    const hit = all.find((c) => c.ticker === t);
    if (hit) ciks[t] = String(hit.cik_str).padStart(10, "0");
    else log(`EDGAR: no company found for ticker ${t}`);
  }
}

async function pollEdgar() {
  try {
    if (!ciks) await loadCiks();
    const firstRun = seenFilings.size === 0;
    for (const [ticker, cik] of Object.entries(ciks)) {
      const r = await fetch(`https://data.sec.gov/submissions/CIK${cik}.json`, { headers: secHeaders() });
      if (!r.ok) throw new Error(`HTTP ${r.status} for ${ticker}`);
      const recent = (await r.json()).filings.recent;
      for (let i = 0; i < Math.min(recent.form.length, 20); i++) {
        const acc = recent.accessionNumber[i];
        if (seenFilings.has(acc) || !FILING_FORMS.includes(recent.form[i])) continue;
        seenFilings.add(acc);
        const filing = {
          ticker, form: recent.form[i], date: recent.filingDate[i],
          url: `https://www.sec.gov/Archives/edgar/data/${Number(cik)}/${acc.replace(/-/g, "")}/${recent.primaryDocument[i]}`,
        };
        state.filings.push(filing);
        if (!firstRun) raise("amber", `New ${filing.form} filing from ${ticker}`, "edgar");
      }
      await new Promise((res) => setTimeout(res, 200)); // SEC asks for no more than 10 requests a second
    }
    state.filings.sort((a, b) => b.date.localeCompare(a.date));
    state.filings = state.filings.slice(0, 25);
    send("filings", state.filings);
    setSource("edgar", "live");
  } catch (e) {
    log(`EDGAR failed: ${e.message}`);
    setSource("edgar", "error");
  }
}

// ---------------------------------------------------------------------------
// Demo mode: made-up data so you can see the page work before getting keys
// ---------------------------------------------------------------------------
function startDemo() {
  // A year of made-up daily prices per stock: a few trending down so every trend label shows up
  const slopes = { CRWV: -0.004, ORCL: -0.002, NBIS: -0.001, OWL: -0.0015, IHYU: -0.0004, IDTL: 0.0004, SGLN: 0.001 };
  for (const w of WATCHLIST) {
    const slope = slopes[w.symbol] ?? 0.0012;
    let p = 100 * (1 - slope * 250);
    const closes = [];
    for (let i = 0; i < 250; i++) { p *= 1 + slope + (Math.random() - 0.5) * 0.03; closes.push(+p.toFixed(2)); }
    state.stocks[w.symbol].prevClose = closes.at(-1);
    applyHistory(w.symbol, closes, w.stream ? "USD" : "GBp");
    updatePrice(w.symbol, closes.at(-1));
  }
  const demoValues = { T10Y2Y: 0.46, SAHMREALTIME: 0.27, BAMLH0A0HYM2: 3.24, DGS10: 5.24, DFF: 3.88, UNRATE: 4.2 };
  const today = new Date().toISOString().slice(0, 10);
  for (const rule of INDICATORS) setIndicator(rule, demoValues[rule.id] ?? 1, today);
  state.filings = [
    { ticker: "ORCL", form: "8-K", date: today, url: "https://www.sec.gov/" },
    { ticker: "CRWV", form: "10-Q", date: today, url: "https://www.sec.gov/" },
  ];
  for (const k of Object.keys(state.sources)) setSource(k, "demo");

  // Random price moves several times a second, with a slow drift down for CRWV
  setInterval(() => {
    const s = STOCKS[Math.floor(Math.random() * STOCKS.length)];
    const drift = s === "CRWV" ? -0.004 : 0;
    updatePrice(s, +(state.stocks[s].price * (1 + drift + (Math.random() - 0.5) * 0.004)).toFixed(2));
  }, 250);
  // Every 10 seconds, nudge the credit spread up so you can see a rule fire
  setInterval(() => {
    const rule = INDICATORS.find((r) => r.id === "BAMLH0A0HYM2");
    if (!rule) return;
    const next = state.indicators[rule.id].value + 0.5;
    setIndicator(rule, +(next > 6 ? 3.24 : next).toFixed(2), today);
  }, 10_000);
}

// ---------------------------------------------------------------------------
// Web server: serves the page, the snapshot and the event stream
// ---------------------------------------------------------------------------
const TYPES = { ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css", ".json": "application/json" };

const server = http.createServer((req, res) => {
  const url = new URL(req.url, "http://localhost");

  if (url.pathname === "/events") {
    res.writeHead(200, { "Content-Type": "text/event-stream", "Cache-Control": "no-cache", Connection: "keep-alive" });
    res.write(`event: state\ndata: ${JSON.stringify(state)}\n\n`);
    clients.add(res);
    const ping = setInterval(() => res.write(": ping\n\n"), 25_000);
    req.on("close", () => { clients.delete(res); clearInterval(ping); });
    return;
  }

  if (url.pathname === "/snapshot.json") {
    res.writeHead(200, { "Content-Type": TYPES[".json"] });
    return fs.createReadStream(path.join(DIR, "snapshot.json")).pipe(res);
  }

  const file = path.join(DIR, "public", url.pathname === "/" ? "index.html" : path.normalize(url.pathname));
  if (!file.startsWith(path.join(DIR, "public")) || !fs.existsSync(file)) {
    res.writeHead(404); return res.end("Not found");
  }
  res.writeHead(200, { "Content-Type": TYPES[path.extname(file)] || "application/octet-stream" });
  fs.createReadStream(file).pipe(res);
});

server.listen(PORT, "127.0.0.1", () => {
  log(`AI Crash Watch running: open http://localhost:${PORT}`);
  if (DEMO) {
    log("Demo mode: all data is made up.");
    return startDemo();
  }
  loadHistory().then(() => { if (FINNHUB_KEY) connectFinnhub(); });
  setInterval(loadHistory, HISTORY_EVERY_HOURS * 3_600_000);
  setInterval(pollYahoo, POLL_EVERY_MIN * 60_000);
  if (!FINNHUB_KEY) log("No FINNHUB_KEY in .env: prices update every 2 minutes from Yahoo instead of streaming.");
  if (FRED_KEY) {
    pollFred();
    setInterval(pollFred, FRED_EVERY_MIN * 60_000);
  } else log("No FRED_KEY in .env, so economic data is off.");
  if (SEC_EMAIL && !SEC_EMAIL.includes("example.com")) {
    pollEdgar();
    setInterval(pollEdgar, EDGAR_EVERY_MIN * 60_000);
  } else log("Set SEC_CONTACT_EMAIL in .env to watch SEC filings.");
});
