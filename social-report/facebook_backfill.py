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


RECOVERABLE_COLUMNS = (3, 6, 15)


def missing_dates(values, start, end):
    dates = []
    day = start
    while day <= end:
        key = day.isoformat()
        index = find_existing_row(values, key)
        row = values[index - 1] if index else []
        if not index or any(len(row) <= col or row[col] == "" for col in RECOVERABLE_COLUMNS):
            dates.append(key)
        day += timedelta(days=1)
    return dates


def merge_missing(existing, source):
    row = (list(existing) + [""] * len(DAILY_HEADERS))[:len(DAILY_HEADERS)]
    if not existing:
        row[:3] = source[:3]
        row[12] = "partial_historical_no_snapshot"
    for col in RECOVERABLE_COLUMNS:
        if row[col] == "" and source[col] != "":
            row[col] = source[col]
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--auto", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    today = datetime.now(timezone(timedelta(hours=8))).date()
    if args.auto:
        start, end = today - timedelta(days=29), today - timedelta(days=2)
    elif args.start and args.end:
        start, end = (datetime.fromisoformat(v).date() for v in (args.start, args.end))
    else:
        parser.error("Use --auto or both --start and --end")
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
    targets = missing_dates(values, start, end)
    print(f"BACKFILL_CHECK={start}..{end} TARGETS={len(targets)}", flush=True)
    if not targets:
        return
    changes = []
    failures = []
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
            for key in targets:
                try:
                    choose_current_month(page)
                    choose_day(page, key)
                    metrics = read_metric_boxes(page)
                    followers, acquired, lost, published = [parse_number(first_metric(metrics, label))
                        for label in ("Followers", "Acquired", "Lost", "Total content")]
                except Exception as exc:
                    failures.append(key)
                    print(f"BACKFILL_FAILED={key}: {type(exc).__name__}", flush=True)
                    page.goto(METRICOOL_URL, wait_until="domcontentloaded", timeout=60000)
                    page.wait_for_timeout(4000)
                    choose_current_month(page)
                    continue
                net = acquired-lost if acquired is not None and lost is not None else ""
                row = [key, PLATFORM, REGION, followers, "", "", net,
                       "", "", "", "", "", "partial_historical_no_snapshot",
                       "", "", published if published is not None else "", ""]
                row[3], row[6] = followers if followers is not None else "", net
                existing = find_existing_row(values, key)
                old = values[existing-1] if existing else []
                merged = merge_missing(old, row)
                if merged != (old + [""] * 17)[:17] and any(merged[c] != "" for c in RECOVERABLE_COLUMNS):
                    changes.append(row)
                print(f"VERIFIED={key} followers={followers} net={net} published={published}", flush=True)
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
        updates, additions, expected = [], [], []
        for source in changes:
            index = find_existing_row(current, source[0])
            old = current[index-1] if index else []
            merged = merge_missing(old, source)
            if index:
                for col in RECOVERABLE_COLUMNS:
                    if (len(old) <= col or old[col] == "") and merged[col] != "":
                        updates.append({"range": f"{chr(65+col)}{index}", "values": [[merged[col]]]})
            else:
                additions.append(merged)
            expected.append(merged)
        if updates:
            sheet.batch_update(updates, value_input_option="RAW")
        if additions:
            sheet.append_rows(additions, value_input_option="RAW")
        if updates or additions:
            workbook.worksheet("run_logs").append_row([
                datetime.now(timezone.utc).isoformat(timespec="seconds"), PLATFORM,
                "partial_historical_no_snapshot",
                f"backfill={start}..{end}; rows={len(changes)}; source=Metricool; historical snapshot deltas unavailable",
            ], value_input_option="RAW")
            refreshed = sheet.get_all_values()
            for row in expected:
                index = find_existing_row(refreshed, row[0])
                actual = (refreshed[index-1] + [""] * 17)[:17] if index else []
                if index is None or any(str(actual[c]) != str(row[c]) for c in RECOVERABLE_COLUMNS):
                    raise RuntimeError(f"Backfill verification failed: {row[0]}")
            print("WRITE_VERIFIED=YES", flush=True)
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
