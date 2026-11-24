# AI Crash Watch (live)

A small program that runs on your computer and keeps a dashboard page updated the moment
something changes: stock trades stream in live, economic data and SEC filings are checked on
a timer, and your crash rules raise alerts (on the page and, if you allow it, as desktop
notifications).

Educational only, not financial advice.

## How it works

```
Finnhub (live trades) ───┐
Yahoo (history, London) ─┤
FRED (economic data) ────┼──► server.js ──► checks rules.js ──► pushes events ──► your browser
SEC EDGAR (filings) ───┘                                                        (localhost:3000)
```

| File | What it is | Edit it? |
|---|---|---|
| `server.js` | Connects to the data feeds, runs the rules, pushes updates to the page | Only if you want new data sources |
| `rules.js` | Your watchlist, trend rules, alert thresholds and filing types | **Yes, this is the one to tweak** |
| `snapshot.json` | Warning signs that have no free feed (CAPE, CDS prices, upcoming events) | Yes, by hand when news changes |
| `public/` | The page: `index.html`, `app.js`, `style.css` | If you want to change the look |
| `.env` | Your private keys | Yes, once |

## Setup (about 10 minutes)

### 1. Install Node.js
Download the **LTS** version (22 or newer) from https://nodejs.org and install it with the default options.
Check it worked: open a terminal (Windows: "Terminal" or "Command Prompt"; Mac: "Terminal") and run:

```
node --version
```

It should print `v22.something` or higher.

### 2. Try the demo first (no keys needed)
In the terminal, go to this folder and start demo mode:

```
cd path/to/ai-crash-watch-live
npm run demo
```

Open http://localhost:3000 in your browser. Prices tick every second, and within about 20 seconds
a credit-spread alert fires so you can see how alerts look. Press `Ctrl+C` in the terminal to stop.

### 3. Get three free things
- **Finnhub key** (streaming stock prices; without it, prices update every 2 minutes instead): sign up at https://finnhub.io/register and copy the API key from your dashboard.
- **FRED key** (yields, unemployment, credit spreads): https://fred.stlouisfed.org/docs/api/api_key.html
- **Your email** for the SEC. They ask every program reading EDGAR to identify itself; no sign-up needed.

### 4. Add them to `.env`
Copy `.env.example` to a new file called `.env` in the same folder, then fill it in:

```
FINNHUB_KEY=your_finnhub_key
FRED_KEY=your_fred_key
SEC_CONTACT_EMAIL=you@youremail.com
```

### 5. Run it for real

```
npm start
```

Open http://localhost:3000, then click **Turn on desktop alerts** if you want pop-ups.
The terminal prints a line for every alert and any feed problem.

## What updates when

| Data | Source | How often |
|---|---|---|
| US stock and ETF prices on the watchlist | Finnhub WebSocket | Every trade, while US markets are open |
| London funds (IHYU, IDTL, SGLN) | Yahoo Finance | Every 2 minutes, about 15 minutes delayed |
| 50/200-day lines, trend, distance from 1-yr high, 1 and 3-month returns, 6-month chart | Yahoo Finance daily history | At start-up, then every 6 hours |
| Yield curve, 10-yr yield, Fed funds, unemployment, Sahm rule, high-yield spread | FRED | Checked every 15 minutes (the data itself updates daily or monthly) |
| New 8-K, 10-Q, 10-K, S-1 filings from the watched companies | SEC EDGAR | Checked every 10 minutes |
| CAPE, concentration, margin debt, CDS prices, upcoming events | `snapshot.json` | When you edit it |

## Adding or removing stocks
Open `rules.js` and edit the `WATCHLIST`. Each line is one stock:

```js
{ group: "Chips", symbol: "INTC", name: "Intel", yahoo: "INTC", stream: true },
```

For a London-listed fund, `yahoo` ends in `.L` (for example `"VUSA.L"`) and `stream` is `false`.
Restart the server afterwards.

## Changing the rules
Open `rules.js`. For example, to be warned when Oracle falls 3% instead of 5%:

```js
export function stockAlert(symbol, dayChangePct) {
  const limit = symbol === "QQQ" ? -3 : symbol === "ORCL" ? -3 : -5;
  ...
```

Restart the server (`Ctrl+C`, then `npm start`) after any change.

## Keeping it running all the time
It is only live while this program runs. Options, easiest first:
- Leave the terminal window open while your PC is on.
- Use `pm2` to start it automatically when your computer starts: `npm install -g pm2`, then
  `pm2 start npm --name crash-watch -- start`, `pm2 save` and `pm2 startup`.
- For 24/7, run it on a Raspberry Pi or a small cloud server (around $5 a month). The page is only
  served to `localhost` for safety; to view it from other devices, ask Claude how to add a password first.

## Troubleshooting
- **"Feeds: yahoo: error"**: Yahoo's chart data is free but unofficial and occasionally changes or rate-limits. The terminal shows the reason; send it to Claude.
- **"Feeds: finnhub: reconnecting"**: check `FINNHUB_KEY` in `.env`. Outside market hours there are few or no trades, so prices sit still.
- **FRED or EDGAR shows "error"**: the terminal prints the reason. A wrong key or a missing `SEC_CONTACT_EMAIL` are the usual causes.
- **Port already in use**: change `PORT=3000` in `.env` to another number such as `3001`.
