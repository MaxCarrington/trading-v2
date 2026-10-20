# Deletes the daily MM-DD download folders under data/raw/oanda/forex, keeping only "merged".
# Layout: <pair>/<year>/<timeframe>/<MM-DD or merged>
# Safe by default: it only prints what it WOULD delete. Add --delete to actually delete.
#   python scripts/clean_daily_folders.py            (dry run)
#   python scripts/clean_daily_folders.py --delete   (delete)
import shutil
import sys
from pathlib import Path

FOREX_DIR = Path(__file__).resolve().parent.parent / "data" / "raw" / "oanda" / "forex"
delete = "--delete" in sys.argv

removed, skipped = 0, []
for tf_dir in sorted(FOREX_DIR.glob("*/*/*")):          # every pair/year/timeframe folder
    if not tf_dir.is_dir():
        continue
    merged = tf_dir / "merged"
    if not merged.is_dir() or not any(merged.glob("*.csv")):
        skipped.append(tf_dir)                          # no merged CSV: keep the daily folders
        continue
    for day_dir in sorted(tf_dir.iterdir()):
        if day_dir.is_dir() and day_dir.name != "merged":
            n_files = sum(1 for f in day_dir.rglob("*") if f.is_file())
            print(f"{'DELETED' if delete else 'would delete'}: {day_dir.relative_to(FOREX_DIR)} ({n_files} files)")
            if delete:
                shutil.rmtree(day_dir)
            removed += 1

print(f"\n{'Deleted' if delete else 'Would delete'} {removed} folders.")
if skipped:
    print(f"Skipped {len(skipped)} folders with no merged CSV (daily folders kept):")
    for s in skipped:
        print(f"  {s.relative_to(FOREX_DIR)}")
if not delete:
    print("Dry run only. Run again with --delete to delete.")
