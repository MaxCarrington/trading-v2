
# Check recent consecutive losses (true streak) and return boolean + streak length
def check_run_of_losses(trade_records, max_inspect=9, max_consecutive=6):
    # trade_records: list of dicts with keys: closed(bool), cancelled(bool), profit(float)
    # Returns: {"ok": bool, "consecutive_losses": int}
    # ok == True means streak is below or equal to max_consecutive

    consecutive = 0
    inspected = 0

    # iterate from most recent to older
    for tr in reversed(trade_records):
        # only consider valid, realized trades
        if not tr.get("closed") or tr.get("cancelled"):
            continue
        if tr.get("profit", 0) == 0:
            continue

        inspected += 1
        if tr["profit"] < 0:
            consecutive += 1
        else:
            # streak breaks on first non-loss
            break

        if inspected >= max_inspect:
            break

    ok = consecutive <= max_consecutive
    return {"ok": ok, "consecutive_losses": consecutive}
