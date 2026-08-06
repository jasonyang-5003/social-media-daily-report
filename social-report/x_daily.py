from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import gspread
import requests

from discord_test import load_env


PLATFORM = "X"
REGION = "North America"
ACTOR_ID = "kaitoeasyapi~twitter-x-data-tweet-scraper-pay-per-result-cheapest"
ACTOR_BUILD = "latest0225"
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


def run_actor(token: str, username: str, max_items: int, max_charge: float):
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "twitterContent": f"from:{username}",
        "queryType": "Latest",
        "maxItems": max_items,
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
    return items, float(run.get("usageTotalUsd") or 0)


def main() -> None:
    base_dir = Path(__file__).resolve().parent
    env = load_env(base_dir / ".env")
    token = env.get("APIFY_API_TOKEN", "")
    username = env.get("X_USERNAME", "").lstrip("@")
    sheet_id = env.get("GOOGLE_SHEET_ID", "")
    max_posts = min(max(int(env.get("X_MAX_POSTS", "10")), 1), 10)
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

    items, usage_usd = run_actor(token, username, max_posts, max_charge)
    items = sorted(items, key=lambda item: int(item["id"]), reverse=True)
    latest_items = items[:max_posts]
    if not latest_items:
        raise RuntimeError("The X collector returned no usable posts or profile data")

    author = latest_items[0].get("author") or {}
    followers = int(author.get("followers") or 0)
    if followers <= 0:
        raise RuntimeError("The X collector did not return a valid follower count")

    report_posts = []
    for item in latest_items:
        created_at = parse_created_at(str(item.get("createdAt", "")))
        if start <= created_at < end:
            report_posts.append(item)

    impressions = sum(int(item.get("viewCount") or 0) for item in report_posts)
    interactions = sum(
        int(item.get(field) or 0)
        for item in report_posts
        for field in ("likeCount", "replyCount", "retweetCount", "quoteCount")
    )

    sheets = gspread.service_account(filename=str(credentials_path))
    workbook = sheets.open_by_key(sheet_id)
    daily_sheet = workbook.worksheet("daily_metrics")
    snapshot_sheet = workbook.worksheet("x_follower_snapshots")
    log_sheet = workbook.worksheet("run_logs")
    values = daily_sheet.get_all_values()

    if not values:
        daily_sheet.append_row(DAILY_HEADERS, value_input_option="RAW")
        values = [DAILY_HEADERS]

    previous_count = previous_follower_count(values, report_date)
    net_growth = followers - previous_count if previous_count is not None else ""
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
    ]

    existing_row = find_existing_row(values, report_date)
    if existing_row:
        daily_sheet.update(
            values=[row],
            range_name=f"A{existing_row}:M{existing_row}",
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
                f"{action}; returned={len(items)}; processed={len(latest_items)}; "
                f"report_posts={len(report_posts)}; usage_usd={usage_usd:.6f}"
            ),
        ],
        value_input_option="RAW",
    )

    print(f"REPORT_DATE={report_date}")
    print(f"FOLLOWERS={followers}")
    print(f"NET_GROWTH={net_growth}")
    print(f"REPORT_POSTS={len(report_posts)}")
    print(f"IMPRESSIONS={impressions}")
    print(f"INTERACTIONS={interactions}")
    print(f"RETURNED_ITEMS={len(items)}")
    print(f"PROCESSED_ITEMS={len(latest_items)}")
    print(f"USAGE_USD={usage_usd:.6f}")
    print(f"SHEET_ACTION={action}")


if __name__ == "__main__":
    main()
