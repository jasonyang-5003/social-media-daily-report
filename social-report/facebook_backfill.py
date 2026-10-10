"""Backfill verified audience/count metrics; never reconstruct old snapshots."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import gspread
from playwright.sync_api import sync_playwright

from discord_test import load_env
from facebook_daily import (
    METRICOOL_URL, PLATFORM, REGION, DAILY_HEADERS, choose_current_month,
    choose_day, first_metric, parse_number, read_metric_boxes, find_existing_row,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    start, end = (datetime.fromisoformat(v).date() for v in (args.start, args.end))
    today = datetime.now(timezone(timedelta(hours=8))).date()
    if start > end or end >= today or start < today - timedelta(days=29):
        parser.error("Require a completed date range within the last 30 days")
    base = Path(__file__).resolve().parent
    env = load_env(base / ".env")
    workbook = gspread.service_account(
        filename=str((base / env["GOOGLE_CREDENTIALS_FILE"]).resolve())
    ).open_by_key(env["GOOGLE_SHEET_ID"])
    sheet = workbook.worksheet("daily_metrics")
    values = sheet.get_all_values()
    if values[0] != DAILY_HEADERS:
        raise RuntimeError("Unexpected daily_metrics schema")
    changes = []
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            str(base / ".metricool-browser-profile"), channel="msedge",
            headless=True, viewport={"width": 1400, "height": 900},
        )
        try:
            page = context.new_page()
            page.goto(METRICOOL_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(4000)
            if "/login" in page.url:
                raise RuntimeError("Metricool login expired")
            choose_current_month(page)
            day = start
            while day <= end:
                key = day.isoformat()
                existing = find_existing_row(values, key)
                if existing:
                    print(f"SKIP_EXISTING={key}", flush=True)
                    day += timedelta(days=1)
                    continue
                choose_day(page, key)
                metrics = read_metric_boxes(page)
                followers, acquired, lost, published = [parse_number(first_metric(metrics, label))
                    for label in ("Followers", "Acquired", "Lost", "Total content")]
                if any(v is None for v in (followers, acquired, lost)):
                    raise RuntimeError(f"Missing audience metrics: {key}")
                row = [key, PLATFORM, REGION, followers, "", "", acquired-lost,
                       "", "", "", "", "", "partial_historical_no_snapshot",
                       "", "", published if published is not None else "", ""]
                changes.append(row)
                print(f"VERIFIED={key} followers={followers} net={acquired-lost} published={published}", flush=True)
                day += timedelta(days=1)
        finally:
            context.close()
    folder = base / "logs"
    folder.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    (folder / f"facebook-backfill-{stamp}.json").write_text(
        json.dumps({"before": values, "proposed": changes}, ensure_ascii=False), encoding="utf-8")
    print(f"ROWS={len(changes)} MODE={'APPLY' if args.apply else 'DRY_RUN'}", flush=True)
    if args.apply and changes:
        # Recheck keys so a concurrent daily run cannot create duplicate rows.
        current = sheet.get_all_values()
        changes = [r for r in changes if find_existing_row(current, r[0]) is None]
        if changes:
            sheet.append_rows(changes, value_input_option="RAW")
            workbook.worksheet("run_logs").append_row([
                datetime.now(timezone.utc).isoformat(timespec="seconds"), PLATFORM,
                "partial_historical_no_snapshot",
                f"backfill={args.start}..{args.end}; rows={len(changes)}; source=Metricool; historical snapshot deltas unavailable",
            ], value_input_option="RAW")
            refreshed = sheet.get_all_values()
            for row in changes:
                index = find_existing_row(refreshed, row[0])
                if index is None or refreshed[index-1][:7] != [str(v) for v in row[:7]]:
                    raise RuntimeError(f"Backfill verification failed: {row[0]}")
            print("WRITE_VERIFIED=YES", flush=True)


if __name__ == "__main__":
    main()
