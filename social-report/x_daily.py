from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import gspread
import requests
from gspread.exceptions import WorksheetNotFound

from discord_test import load_env


PLATFORM = "X"
REGION = "North America"
ACTOR_ID = "kaitoeasyapi~twitter-x-data-tweet-scraper-pay-per-result-cheapest"
ACTOR_BUILD = "latest0225"
MONTH_QUERY_SAFETY_LIMIT = 1000
DAILY_HEADERS = [
    "date",
    "platform",
    "region",
    "followers_total",
    "joined",
    "left",
    "net_growth",
    "reach",
    "impressions",
    "active_members",
    "active_rate",
    "interactions",
    "status",
    "month_views",
    "month_interactions",
]


def parse_created_at(value: str) -> datetime:
    if not value:
        raise ValueError("Missing post creation time")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        parsed = datetime.strptime(value, "%a %b %d %H:%M:%S %z %Y")
    return parsed.astimezone(timezone.utc)


def find_existing_row(values: list[list[str]], report_date: str) -> int | None:
    for row_number, row in enumerate(values[1:], start=2):
        if len(row) >= 2 and row[0] == report_date and row[1] == PLATFORM:
            return row_number
    return None


def previous_follower_count(values: list[list[str]], report_date: str) -> int | None:
    candidates: list[tuple[str, int]] = []
    for row in values[1:]:
        if len(row) < 4 or row[1] != PLATFORM or row[0] >= report_date:
            continue
        try:
            candidates.append((row[0], int(float(row[3].replace(",", "")))))
        except (ValueError, AttributeError):
            continue
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def previous_month_totals(
    values: list[list[str]], report_date: str
) -> tuple[int, int] | None:
    candidates: list[tuple[str, int, int]] = []
    month_prefix = report_date[:7]
    for row in values[1:]:
        if (
            len(row) < 15
            or row[1] != PLATFORM
            or row[2] != REGION
            or row[0] >= report_date
            or not row[0].startswith(month_prefix)
            or row[13] == ""
            or row[14] == ""
        ):
            continue
        try:
            candidates.append(
                (
                    row[0],
                    int(float(str(row[13]).replace(",", ""))),
                    int(float(str(row[14]).replace(",", ""))),
                )
            )
        except (TypeError, ValueError):
            continue
    if not candidates:
        return None
    _, views, interactions = max(candidates, key=lambda item: item[0])
    return views, interactions


def upsert_post_snapshots(sheet, items: list[dict]) -> None:
    headers = ["post_id", "created_at", "views", "interactions", "last_seen_at"]
    values = sheet.get_all_values()
    if not values:
        sheet.append_row(headers, value_input_option="RAW")
        values = [headers]
    elif values[0] != headers:
        sheet.update(values=[headers], range_name="A1:E1", value_input_option="RAW")

    existing_rows = {
        row[0]: row_number
        for row_number, row in enumerate(values[1:], start=2)
        if row
    }
    seen_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    updates = []
    new_rows = []
    for item in items:
        post_id = str(item.get("id") or "")
        if not post_id:
            continue
        interactions = sum(
            int(item.get(field) or 0)
            for field in ("likeCount", "replyCount", "retweetCount", "quoteCount")
        )
        snapshot = [
            post_id,
            parse_created_at(str(item.get("createdAt", ""))).isoformat(),
            int(item.get("viewCount") or 0),
            interactions,
            seen_at,
        ]
        if post_id in existing_rows:
            row_number = existing_rows[post_id]
            updates.append(
                {"range": f"A{row_number}:E{row_number}", "values": [snapshot]}
            )
        else:
            new_rows.append(snapshot)

    if updates:
        sheet.batch_update(updates, value_input_option="USER_ENTERED")
    if new_rows:
        sheet.append_rows(new_rows, value_input_option="USER_ENTERED")


def upsert_snapshot(sheet, report_date: str, followers: int) -> None:
    values = sheet.get_all_values()
    for row_number, row in enumerate(values[1:], start=2):
        if row and row[0] == report_date:
            sheet.update(
                values=[[report_date, followers]],
                range_name=f"A{row_number}:B{row_number}",
                value_input_option="USER_ENTERED",
            )
            return
    sheet.append_row([report_date, followers], value_input_option="USER_ENTERED")


def run_actor(token: str, query: str, max_charge: float):
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "twitterContent": query,
        "queryType": "Latest",
        "maxItems": MONTH_QUERY_SAFETY_LIMIT,
    }
    url = (
        f"https://api.apify.com/v2/acts/{ACTOR_ID}/runs"
        f"?build={ACTOR_BUILD}&waitForFinish=120"
        f"&maxTotalChargeUsd={max_charge:.6f}"
    )
    response = requests.post(url, headers=headers, json=payload, timeout=150)
    response.raise_for_status()
    run = response.json()["data"]
    if run["status"] != "SUCCEEDED":
        raise RuntimeError(
            f"Apify run did not succeed: {run['status']}; "
            f"usage={run.get('usageTotalUsd', '')}"
        )

    usage_usd = float(run.get("usageTotalUsd") or 0)
    if usage_usd >= max_charge * 0.98:
        raise RuntimeError(
            "Apify reached the configured charge cap; monthly X data may be incomplete"
        )

    dataset_response = requests.get(
        f"https://api.apify.com/v2/datasets/{run['defaultDatasetId']}/items",
        headers={"Authorization": f"Bearer {token}"},
        params={"clean": "true", "format": "json"},
        timeout=60,
    )
    dataset_response.raise_for_status()
    items = [
        item
        for item in dataset_response.json()
        if item.get("id") and not item.get("noResults")
    ]
    if len(items) >= MONTH_QUERY_SAFETY_LIMIT:
        raise RuntimeError("X monthly query reached the 1000-post safety boundary")
    return items, usage_usd


def main() -> None:
    base_dir = Path(__file__).resolve().parent
    env = load_env(base_dir / ".env")
    token = env.get("APIFY_API_TOKEN", "")
    username = env.get("X_USERNAME", "").lstrip("@")
    sheet_id = env.get("GOOGLE_SHEET_ID", "")
    max_charge = min(float(env.get("APIFY_MAX_CHARGE_USD", "0.005")), 0.005)
    credentials_path = (base_dir / env.get("GOOGLE_CREDENTIALS_FILE", "")).resolve()

    if not token or not username or not sheet_id:
        raise RuntimeError("Apify, X, or Google Sheets configuration is missing")

    today_utc = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    start = today_utc - timedelta(days=1)
    end = today_utc
    report_date = start.date().isoformat()
    month_start = start.replace(day=1)
    query = (
        f"from:{username} since:{month_start.date().isoformat()} "
        f"until:{end.date().isoformat()}"
    )

    items, usage_usd = run_actor(token, query, max_charge)
    items = list({str(item["id"]): item for item in items}.values())
    items = sorted(items, key=lambda item: int(item["id"]), reverse=True)
    month_items = [
        item
        for item in items
        if item.get("createdAt")
        and month_start <= parse_created_at(str(item["createdAt"])) < end
    ]
    if not month_items:
        raise RuntimeError("The X collector returned no posts for the current month")

    author = month_items[0].get("author") or {}
    followers = int(author.get("followers") or 0)
    if followers <= 0:
        raise RuntimeError("The X collector did not return a valid follower count")

    sheets = gspread.service_account(filename=str(credentials_path))
    workbook = sheets.open_by_key(sheet_id)
    daily_sheet = workbook.worksheet("daily_metrics")
    snapshot_sheet = workbook.worksheet("x_follower_snapshots")
    try:
        post_snapshot_sheet = workbook.worksheet("x_post_snapshots")
    except WorksheetNotFound:
        post_snapshot_sheet = workbook.add_worksheet(
            title="x_post_snapshots", rows=1000, cols=5
        )
    log_sheet = workbook.worksheet("run_logs")
    values = daily_sheet.get_all_values()

    if not values:
        daily_sheet.append_row(DAILY_HEADERS, value_input_option="RAW")
        values = [DAILY_HEADERS]
    elif values[0] != DAILY_HEADERS:
        daily_sheet.update(
            values=[DAILY_HEADERS],
            range_name="A1:O1",
            value_input_option="RAW",
        )

    previous_count = previous_follower_count(values, report_date)
    net_growth = followers - previous_count if previous_count is not None else ""
    upsert_post_snapshots(post_snapshot_sheet, month_items)
    month_views = sum(int(item.get("viewCount") or 0) for item in month_items)
    month_interactions = sum(
        int(item.get(field) or 0)
        for item in month_items
        for field in ("likeCount", "replyCount", "retweetCount", "quoteCount")
    )
    previous_totals = previous_month_totals(values, report_date)
    if previous_totals is None:
        impressions = ""
        interactions = ""
    else:
        impressions = month_views - previous_totals[0]
        interactions = month_interactions - previous_totals[1]
    row = [
        report_date,
        PLATFORM,
        REGION,
        followers,
        "",
        "",
        net_growth,
        "",
        impressions,
        "",
        "",
        interactions,
        "success",
        month_views,
        month_interactions,
    ]

    existing_row = find_existing_row(values, report_date)
    if existing_row:
        daily_sheet.update(
            values=[row],
            range_name=f"A{existing_row}:O{existing_row}",
            value_input_option="USER_ENTERED",
        )
        action = "updated"
    else:
        daily_sheet.append_row(row, value_input_option="USER_ENTERED")
        action = "inserted"

    upsert_snapshot(snapshot_sheet, report_date, followers)
    log_sheet.append_row(
        [
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            PLATFORM,
            "success",
            (
                f"{action}; returned={len(items)}; processed={len(month_items)}; "
                f"daily_metrics=month_snapshot_delta; usage_usd={usage_usd:.6f}"
            ),
        ],
        value_input_option="RAW",
    )

    print(f"REPORT_DATE={report_date}")
    print(f"FOLLOWERS={followers}")
    print(f"NET_GROWTH={net_growth}")
    print(f"IMPRESSIONS={impressions}")
    print(f"INTERACTIONS={interactions}")
    print(f"MONTH_VIEWS={month_views}")
    print(f"MONTH_INTERACTIONS={month_interactions}")
    print(f"RETURNED_ITEMS={len(items)}")
    print(f"PROCESSED_ITEMS={len(month_items)}")
    print(f"QUERY_SINCE={month_start.date().isoformat()}")
    print(f"QUERY_UNTIL={end.date().isoformat()}")
    print(f"USAGE_USD={usage_usd:.6f}")
    print(f"SHEET_ACTION={action}")


if __name__ == "__main__":
    main()
