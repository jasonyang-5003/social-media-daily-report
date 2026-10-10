"""Backfill X publication counts from the current month's posts.

X does not expose historical follower or daily impression snapshots, so this
script only fills published_count and month_published_count when blank.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

import gspread

from discord_test import load_env
from x_daily import DAILY_HEADERS, REGION, PLATFORM, parse_created_at, run_actor


RECOVERABLE = (15, 16)


def row_index(values, date):
    for n, row in enumerate(values[1:], 2):
        if len(row) >= 3 and row[0] == date and row[1] == PLATFORM and row[2] == REGION:
            return n
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--auto", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not args.auto:
        parser.error("Use --auto")
    base = Path(__file__).resolve().parent
    env = load_env(base / ".env")
    token, username, sheet_id = env.get("APIFY_API_TOKEN", ""), env.get("X_USERNAME", "").lstrip("@"), env.get("GOOGLE_SHEET_ID", "")
    if not token or not username or not sheet_id:
        raise RuntimeError("X or Google Sheets configuration is missing")
    today = datetime.now(timezone.utc).date()
    start, end = today - timedelta(days=29), today - timedelta(days=2)
    query_start = start.replace(day=1)
    query = f"from:{username} since:{query_start.isoformat()} until:{(today + timedelta(days=1)).isoformat()}"
    items, usage = run_actor(token, query, min(float(env.get("APIFY_MAX_CHARGE_USD", "0.005")), 0.005))
    items = {str(x["id"]): x for x in items}.values()
    dated = {}
    for item in items:
        if not item.get("createdAt"):
            continue
        day = parse_created_at(str(item["createdAt"])).date()
        if query_start <= day <= today - timedelta(days=1):
            dated[day.isoformat()] = dated.get(day.isoformat(), 0) + 1
    sheets = gspread.service_account(filename=str((base / env["GOOGLE_CREDENTIALS_FILE"]).resolve()))
    book = sheets.open_by_key(sheet_id)
    sheet, log = book.worksheet("daily_metrics"), book.worksheet("run_logs")
    values = sheet.get_all_values()
    if not values or values[0] != DAILY_HEADERS:
        raise RuntimeError("Unexpected daily_metrics schema")
    proposals = []
    for day_obj in (start + timedelta(days=i) for i in range((end - start).days + 1)):
        day = day_obj.isoformat()
        cumulative = sum(count for date_key, count in dated.items() if date_key[:7] == day[:7] and date_key <= day)
        if not (start.isoformat() <= day <= end.isoformat()):
            continue
        idx = row_index(values, day)
        old = values[idx - 1] if idx else []
        row = (list(old) + [""] * len(DAILY_HEADERS))[: len(DAILY_HEADERS)]
        if not old:
            row[:3] = [day, PLATFORM, REGION]
            row[12] = "partial_historical_no_snapshot"
        row[15] = dated.get(day, 0)
        row[16] = cumulative
        if row[15] != "" or row[16] != "": proposals.append((idx, row))
    if args.apply:
        current = sheet.get_all_values()
        for _, proposed in proposals:
            idx = row_index(current, proposed[0])
            if idx:
                old = current[idx - 1]
                updates = []
                if len(old) <= 15 or old[15] == "" or old[15] != str(proposed[15]): updates.append({"range": f"P{idx}", "values": [[proposed[15]]]})
                if len(old) <= 16 or old[16] == "" or old[16] != str(proposed[16]): updates.append({"range": f"Q{idx}", "values": [[proposed[16]]]})
                if updates: sheet.batch_update(updates, value_input_option="RAW")
            else:
                sheet.append_row(proposed, value_input_option="RAW")
        if proposals:
            log.append_row([datetime.now(timezone.utc).isoformat(timespec="seconds"), PLATFORM, "partial_historical_no_snapshot", f"x_backfill rows={len(proposals)} usage_usd={usage:.6f}"], value_input_option="RAW")
    print(f"BACKFILL_CHECK={start}..{end} PROPOSALS={len(proposals)} MODE={'APPLY' if args.apply else 'DRY_RUN'}")


if __name__ == "__main__":
    main()
