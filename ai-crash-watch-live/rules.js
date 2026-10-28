// ---------------------------------------------------------------------------
// Your crash rules. Edit freely: the server re-reads this file when it restarts.
//
// Each indicator rule gets the latest value and returns "red", "amber" or "green".
// Each stock rule gets the day's % change and returns an alert message or null.
// ---------------------------------------------------------------------------

export const INDICATORS = [
  {
    id: "T10Y2Y", label: "Yield curve (10y − 2y)", unit: "pts",
    explain: "Negative (inverted) has preceded past recessions",
    status: (v) => (v < 0 ? "red" : v < 0.25 ? "amber" : "green"),
  },
  {
    id: "SAHMREALTIME", label: "Sahm rule recession gap", unit: "pts",
    explain: "0.50 or more has signalled every US recession since 1970",
    status: (v) => (v >= 0.5 ? "red" : v >= 0.3 ? "amber" : "green"),
  },
  {
    id: "BAMLH0A0HYM2", label: "High-yield credit spread", unit: "%",
    explain: "Above 5% means credit markets are under stress",
    status: (v) => (v >= 5 ? "red" : v >= 4 ? "amber" : "green"),
  },
  {
    id: "DGS10", label: "10-yr Treasury yield", unit: "%",
    explain: "Above 5% makes the debt-funded AI buildout costlier",
    status: (v) => (v >= 5.5 ? "red" : v >= 5 ? "amber" : "green"),
  },
  {
    id: "DFF", label: "Fed funds rate", unit: "%",
    explain: "Shown for context; a rise means the Fed hiked",
    status: () => "green",
  },
  {
    id: "UNRATE", label: "Unemployment rate", unit: "%",
    explain: "Shown for context; the Sahm gap above is the signal",
    status: () => "green",
  },
];

// Your watchlist, matching the Trading 212 "Crash" list.
//   symbol: the US ticker (streamed live from Finnhub when stream is true)
//   yahoo:  the ticker Yahoo Finance uses, for history and London-listed funds
//   stream: false for London (LSE) funds, which Finnhub's free plan doesn't cover;
//           those update every 2 minutes instead, with a 15-minute delay
export const WATCHLIST = [
  { group: "Weak links", symbol: "ORCL", name: "Oracle", yahoo: "ORCL", stream: true },
  { group: "Weak links", symbol: "CRWV", name: "CoreWeave", yahoo: "CRWV", stream: true },
  { group: "Weak links", symbol: "NBIS", name: "Nebius", yahoo: "NBIS", stream: true },
  { group: "Weak links", symbol: "OWL", name: "Blue Owl", yahoo: "OWL", stream: true },
  { group: "Chips", symbol: "NVDA", name: "Nvidia", yahoo: "NVDA", stream: true },
  { group: "Chips", symbol: "AVGO", name: "Broadcom", yahoo: "AVGO", stream: true },
  { group: "Chips", symbol: "TSM", name: "TSMC", yahoo: "TSM", stream: true },
  { group: "Chips", symbol: "AMD", name: "AMD", yahoo: "AMD", stream: true },
  { group: "Big spenders", symbol: "MSFT", name: "Microsoft", yahoo: "MSFT", stream: true },
  { group: "Big spenders", symbol: "GOOGL", name: "Alphabet", yahoo: "GOOGL", stream: true },
  { group: "Big spenders", symbol: "AMZN", name: "Amazon", yahoo: "AMZN", stream: true },
  { group: "Big spenders", symbol: "META", name: "Meta", yahoo: "META", stream: true },
  { group: "Power buildout", symbol: "VRT", name: "Vertiv", yahoo: "VRT", stream: true },
  { group: "Power buildout", symbol: "GEV", name: "GE Vernova", yahoo: "GEV", stream: true },
  { group: "Power buildout", symbol: "CEG", name: "Constellation Energy", yahoo: "CEG", stream: true },
  { group: "Power buildout", symbol: "VST", name: "Vistra", yahoo: "VST", stream: true },
  { group: "Indices", symbol: "QQQ", name: "Nasdaq 100", yahoo: "QQQ", stream: true },
  { group: "Indices", symbol: "SPY", name: "S&P 500", yahoo: "SPY", stream: true },
  { group: "Indices", symbol: "RSP", name: "S&P 500 Equal Weight", yahoo: "RSP", stream: true },
  { group: "Indices", symbol: "SMH", name: "Semiconductors", yahoo: "SMH", stream: true },
  { group: "Stress gauges", symbol: "IHYU", name: "USD High Yield Corp Bond", yahoo: "IHYU.L", stream: false },
  { group: "Stress gauges", symbol: "IDTL", name: "USD Treasury Bond 20+yr", yahoo: "IDTL.L", stream: false },
  { group: "Stress gauges", symbol: "SGLN", name: "Physical Gold", yahoo: "SGLN.L", stream: false },
];
export const STOCKS = WATCHLIST.map((w) => w.symbol);

// Trend from the price and its 50/200-day simple moving averages.
// Returns [label, colour]. Alerts fire when a stock moves to a worse colour.
export function trend(price, sma50, sma200) {
  if (!price || !sma50 || !sma200) return ["Waiting", "grey"];
  if (sma50 < sma200) return price > sma200 ? ["Recovering", "amber"] : ["Death cross", "red"];
  if (price >= sma50) return ["Uptrend", "green"];
  if (price >= sma200) return ["Wobbling", "amber"];
  return ["Below 200-day", "red"];
}

// Alert when something falls this much in a day. Indices and bond funds move less, so their line is smaller.
export function stockAlert(symbol, dayChangePct) {
  const limit = ["QQQ", "SPY", "RSP", "IHYU", "IDTL"].includes(symbol) ? -2 : -5;
  if (dayChangePct <= limit) return `${symbol} is down ${dayChangePct.toFixed(1)}% today`;
  return null;
}

// Companies whose SEC filings are watched. Filing types worth an alert:
export const FILERS = ["ORCL", "CRWV", "NBIS", "OWL", "NVDA", "MSFT", "GOOGL", "AMZN", "META"];
export const FILING_FORMS = ["8-K", "10-Q", "10-K", "S-1", "424B4", "NT 10-Q", "NT 10-K"];
