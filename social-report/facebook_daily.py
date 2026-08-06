from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import gspread
from playwright.sync_api import Page, sync_playwright

from discord_test import load_env


PLATFORM = "Facebook"
REGION = "LATAM"
METRICOOL_URL = (
    "https://app.metricool.com/evolution/facebookPage"
    "?blogId=6680040&userId=5139837"
)
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


def parse_number(value: str) -> int | None:
    cleaned = value.strip().replace(",", "")
    if not cleaned or cleaned == "-":
        return None

    match = re.fullmatch(r"(-?\d+(?:\.\d+)?)\s*([KMB]?)", cleaned, re.I)
    if not match:
        raise ValueError(f"Unexpected Metricool number: {value!r}")

    number = float(match.group(1))
    multiplier = {"": 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000}[
        match.group(2).upper()
    ]
    return int(round(number * multiplier))


def split_metric_box(text: str) -> tuple[str, str]:
    labels = (
        "Average daily new followers",
        "Avg. reach per post",
        "Total content",
        "Page visits",
        "Interactions",
        "Engagement",
        "Followers",
        "Acquired",
        "Reactions",
        "Comments",
        "Shared",
        "Clicks",
        "Views",
        "Posts",
        "Lost",
    )
    normalized = " ".join(text.split())
    for label in labels:
        if normalized.endswith(label):
            return label, normalized[: -len(label)].strip()
    raise ValueError(f"Unknown Metricool metric box: {text!r}")


def first_metric(metrics: list[tuple[str, str]], label: str) -> str:
    for metric_label, value in metrics:
        if metric_label == label:
            return value
    raise RuntimeError(f"Metricool did not return the {label} metric")


def choose_yesterday(page: Page) -> None:
    picker = page.locator('[aria-label="Evolution date range picker"]')
    picker.locator("button").first.click()
    page.get_by_role("button", name="Yesterday", exact=True).click()
    page.wait_for_timeout(2_500)


def choose_current_month(page: Page) -> None:
    picker = page.locator('[aria-label="Evolution date range picker"]')
    picker.locator("button").first.click()
    page.get_by_role("button", name="Current month", exact=True).click()
    page.wait_for_timeout(2_500)


def read_metric_boxes(page: Page) -> list[tuple[str, str]]:
    page.locator('[aria-label="Analysis Metric Box"]').first.wait_for(
        state="visible", timeout=30_000
    )
    return [
        split_metric_box(text)
        for text in page.locator(
            '[aria-label="Analysis Metric Box"]'
        ).all_text_contents()
    ]


def collect_metricool(profile_dir: Path) -> tuple[int, int, int, int, int, int]:
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            channel="msedge",
            headless=True,
            viewport={"width": 1400, "height": 900},
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(METRICOOL_URL, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(2_000)
            if "/login" in page.url:
                raise RuntimeError(
                    "Metricool login expired; run: py -3.12 facebook_login.py"
                )

            choose_yesterday(page)
            metrics = read_metric_boxes(page)

            followers = parse_number(first_metric(metrics, "Followers"))
            views = parse_number(first_metric(metrics, "Views"))
            acquired = parse_number(first_metric(metrics, "Acquired"))
            lost = parse_number(first_metric(metrics, "Lost"))
            interaction_raw = first_metric(metrics, "Interactions")
            interactions = parse_number(interaction_raw)

            if followers is None or views is None or acquired is None or lost is None:
                raise RuntimeError("Metricool returned a blank required Facebook metric")

            if interactions is None:
                total_content = parse_number(first_metric(metrics, "Total content"))
                interactions = 0 if total_content is None else None
            if interactions is None:
                raise RuntimeError("Metricool returned an unavailable interaction metric")

            choose_current_month(page)
            month_metrics = read_metric_boxes(page)
            month_views = parse_number(first_metric(month_metrics, "Views"))
            month_interactions = parse_number(
                first_metric(month_metrics, "Interactions")
            )
            if month_views is None:
                raise RuntimeError("Metricool returned a blank monthly view metric")
            if month_interactions is None:
                month_total_content = parse_number(
                    first_metric(month_metrics, "Total content")
                )
                month_interactions = 0 if month_total_content is None else None
            if month_interactions is None:
                raise RuntimeError("Metricool returned a blank monthly interaction metric")

            return (
                followers,
                acquired - lost,
                views,
                interactions,
                month_views,
                month_interactions,
            )
        finally:
            context.close()


def find_existing_row(values: list[list[str]], report_date: str) -> int | None:
    for row_number, row in enumerate(values[1:], start=2):
        if len(row) >= 2 and row[0] == report_date and row[1] == PLATFORM:
            return row_number
    return None


def main() -> None:
    base_dir = Path(__file__).resolve().parent
    env = load_env(base_dir / ".env")
    sheet_id = env.get("GOOGLE_SHEET_ID", "")
    credentials_path = (base_dir / env.get("GOOGLE_CREDENTIALS_FILE", "")).resolve()
    profile_dir = base_dir / ".metricool-browser-profile"

    if not sheet_id:
        raise RuntimeError("Google Sheets configuration is missing")

    today_utc = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    report_date = (today_utc - timedelta(days=1)).date().isoformat()
    (
        followers,
        net_growth,
        views,
        interactions,
        month_views,
        month_interactions,
    ) = collect_metricool(profile_dir)

    sheets = gspread.service_account(filename=str(credentials_path))
    workbook = sheets.open_by_key(sheet_id)
    daily_sheet = workbook.worksheet("daily_metrics")
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

    row = [
        report_date,
        PLATFORM,
        REGION,
        followers,
        "",
        "",
        net_growth,
        "",
        views,
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

    log_sheet.append_row(
        [
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            PLATFORM,
            "success",
            f"{action}; source=Metricool; range=yesterday",
        ],
        value_input_option="RAW",
    )

    print(f"REPORT_DATE={report_date}")
    print(f"FOLLOWERS={followers}")
    print(f"NET_GROWTH={net_growth}")
    print(f"VIEWS={views}")
    print(f"INTERACTIONS={interactions}")
    print(f"MONTH_VIEWS={month_views}")
    print(f"MONTH_INTERACTIONS={month_interactions}")
    print(f"SHEET_ACTION={action}")


if __name__ == "__main__":
    main()
