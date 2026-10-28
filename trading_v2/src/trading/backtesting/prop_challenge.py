# Prop-firm challenge simulator: would a strategy's daily returns pass a funded-account challenge?
# Rules come from the config (FTMO 2-Step by default, see configs/analysis/prop_challenge.yaml):
#   phase 1 reach +profit_target_%, phase 2 reach +phase2_target_%, each on a fresh account,
#   daily loss: equity must stay above (balance at midnight - max_daily_loss_% of the initial capital),
#     where "balance" is closed trades only (FTMO), so a position already losing overnight leaves less room,
#   max loss: equity must stay above initial capital - max_total_loss_% (static),
#   at least min_trading_days with a position, within time_limit_days (0 = none).
# Only daily closes are used, so a limit hit during the day and recovered by the close is missed (optimistic);
# daily_buffer_% tightens the daily limit to allow for that.
# Sizing: positions are leverage x the strategy's returns, cut to brake_factor x when equity is
# brake_at_% or more below the initial capital (0 = no brake).
import numpy as np
import pandas as pd


def _step(equity, balance, x, lev, rules):
    # one day: returns new equity, new balance, and whether a loss limit was broken
    new = equity * (1 + x * lev)
    daily_limit = balance - (rules["max_daily_loss_%"] - rules.get("daily_buffer_%", 0)) / 100
    broken = new < daily_limit or new < 1 - rules["max_total_loss_%"] / 100
    return new, broken


def _size(equity, lev, rules):
    brake = rules.get("brake_at_%", 0)
    return lev * rules.get("brake_factor", 0.5) if brake and equity <= 1 - brake / 100 else lev


def run_phase(r, target, rules, lev):
    # r: daily (1x) returns from the phase start. Returns ("pass" | "fail" | "timeout" | "unfinished", days used)
    equity = balance = 1.0
    traded = 0
    limit = rules["time_limit_days"] or len(r)
    for i, x in enumerate(r[:limit]):
        if x == 0:
            balance = equity                      # flat: every trade is closed, so balance = equity
        equity, broken = _step(equity, balance, x, _size(equity, lev, rules), rules)
        traded += x != 0
        if broken:
            return "fail", i + 1
        flat_next = i + 1 >= len(r) or r[i + 1] == 0
        if equity >= 1 + target / 100 and traded >= rules["min_trading_days"] and flat_next:
            return "pass", i + 1                  # target counts once positions are closed
    return ("timeout" if rules["time_limit_days"] and len(r) >= limit else "unfinished"), min(limit, len(r))


def run_funded(r, rules, lev):
    # funded account for funded_days: profit share paid at the end, nothing if a loss limit is broken first
    equity = balance = 1.0
    for x in r[:rules["funded_days"]]:
        if x == 0:
            balance = equity
        equity, broken = _step(equity, balance, x, _size(equity, lev, rules), rules)
        if broken:
            return 0.0, "breached"
    return max(equity - 1, 0) * rules["profit_split"], "kept"


def simulate(daily, rules, leverage=1.0):
    # starts a challenge on the first trading day of every month; returns one row per attempt
    r_all = daily.values
    starts = daily.index.to_series().groupby(daily.index.to_period("M")).min().values
    rows = []
    for s in starts:
        i = daily.index.get_loc(s)
        p1, d1 = run_phase(r_all[i:], rules["profit_target_%"], rules, leverage)
        p2, d2, payout, status = "-", 0, 0.0, "-"
        if p1 == "pass":
            p2, d2 = run_phase(r_all[i + d1:], rules["phase2_target_%"], rules, leverage)
            if p2 == "pass":
                payout, status = run_funded(r_all[i + d1 + d2:], rules, leverage)
        rows.append({"start": pd.Timestamp(s).date(), "phase1": p1, "phase1_days": d1, "phase2": p2, "phase2_days": d2,
                     "funded": status, "payout_%_of_account": 100 * payout})
    return pd.DataFrame(rows)


def summary(attempts, rules, leverage):
    done = attempts[(attempts.phase1 != "unfinished") & (attempts.phase2 != "unfinished")]
    passed = done[(done.phase1 == "pass") & (done.phase2 == "pass")]
    payout = done["payout_%_of_account"] / 100 * rules["account_size"]
    return {"leverage": leverage, "attempts": len(done),
            "pass %": round(100 * len(passed) / max(len(done), 1), 1),
            "fail %": round(100 * (done.phase1.eq("fail") | done.phase2.eq("fail")).mean(), 1),
            "timeout %": round(100 * (done.phase1.eq("timeout") | done.phase2.eq("timeout")).mean(), 1),
            "median days to pass": int((passed.phase1_days + passed.phase2_days).median()) if len(passed) else None,
            "funded kept %": round(100 * passed.funded.eq("kept").mean(), 1) if len(passed) else None,
            "avg payout per attempt": round(payout.mean()) if len(done) else None,
            "profit per attempt after fee": round(payout.mean() - rules["challenge_fee"]) if len(done) else None}
