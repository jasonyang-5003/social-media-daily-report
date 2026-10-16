from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import gspread
from playwright.sync_api import Page, sync_playwright

from discord_test import load_env


PLATFORM = "Facebook"
REGION = "LATAM"
POST_VIEW_SCOPE_START = "2026-08-06"
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
    "published_count",
    "month_published_count",
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


def metric_occurrence(
    metrics: list[tuple[str, str]], label: str, occurrence: int
) -> str:
    values = [value for metric_label, value in metrics if metric_label == label]
    if len(values) <= occurrence:
        raise RuntimeError(
            f"Metricool did not return occurrence {occurrence + 1} of {label}"
        )
    return values[occurrence]


def choose_yesterday(page: Page) -> None:
    picker = page.locator('[aria-label="Evolution date range picker"]')
    picker.locator("button").first.click()
    page.get_by_role("button", name="Yesterday", exact=True).click()
    page.wait_for_timeout(8_000)


def choose_current_month(page: Page) -> None:
    picker = page.locator('[aria-label="Evolution date range picker"]')
    picker.locator("button").first.click()
    page.get_by_role("button", name="Current month", exact=True).click()
    page.wait_for_timeout(8_000)


def choose_day(page: Page, report_date: str) -> None:
    picker = page.locator('[aria-label="Evolution date range picker"]')
    picker.locator("button").first.click()
    selector = f".vc-day.in-month.id-{report_date} .vc-day-content:visible"
    day = page.locator(selector).first
    if day.count() == 0:
        page.locator(".vc-arrow.vc-prev:visible").last.click()
        page.wait_for_timeout(800)
        day = page.locator(selector).first
    if day.count() == 0 or day.get_attribute("aria-disabled") == "true":
        raise RuntimeError(f"Metricool date is unavailable: {report_date}")
    day.click()
    page.locator(selector).first.click()
    page.wait_for_timeout(8_000)
    date = datetime.fromisoformat(report_date)
    expected = f"{date.strftime('%b')} {date.day}, {date.year}"
    if picker.inner_text().count(expected) != 2:
        raise RuntimeError(f"Metricool did not select the requested day: {report_date}")


def read_metric_boxes(page: Page) -> list[tuple[str, str]]:
    page.locator('[aria-label="Analysis Metric Box"]').first.wait_for(
        state="visible", timeout=30_000
    )
    boxes = page.locator('[aria-label="Analysis Metric Box"]')
    previous = boxes.all_text_contents()
    for _ in range(10):
        page.wait_for_timeout(1000)
        current = boxes.all_text_contents()
        if current == previous:
            break
        previous = current
    else:
        raise RuntimeError("Metricool metrics did not stabilize")
    metrics = []
    for text in current:
        try:
            metrics.append(split_metric_box(text))
        except ValueError:
            continue
    return metrics


def collect_metricool(
    profile_dir: Path,
    report_date: str | None = None,
) -> tuple[int, int, int | None, int | None, int | None, int | None, int | None, int | None]:
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

            if report_date:
                choose_day(page, report_date)
            else:
                choose_yesterday(page)
            metrics = read_metric_boxes(page)

            followers = parse_number(first_metric(metrics, "Followers"))
            views = parse_number(first_metric(metrics, "Views"))
            acquired = parse_number(first_metric(metrics, "Acquired"))
            lost = parse_number(first_metric(metrics, "Lost"))
            interaction_raw = first_metric(metrics, "Interactions")
            interactions = parse_number(interaction_raw)
            # Metricool uses "-" when no content was published that day;
            # for this daily count that is a valid zero.
            published_count = parse_number(first_metric(metrics, "Total content"))
            if published_count is None:
                published_count = 0

            if followers is None or acquired is None or lost is None:
                raise RuntimeError("Metricool returned a blank required Facebook metric")

            # Historical date filters do not recreate historical post-view snapshots.
            if report_date:
                return (followers, acquired - lost, views, interactions,
                        None, None, published_count, None)

            choose_current_month(page)
            month_metrics = read_metric_boxes(page)
            month_views = parse_number(
                metric_occurrence(month_metrics, "Views", occurrence=1)
            )
            month_interactions = parse_number(
                first_metric(month_metrics, "Interactions")
            )
            month_published_count = (
                parse_number(first_metric(month_metrics, "Total content"))
            )

            return (
                followers,
                acquired - lost,
                views,
                interactions,
                month_views,
                month_interactions,
                published_count,
                month_published_count,
            )
        finally:
            context.close()


def find_existing_row(values: list[list[str]], report_date: str) -> int | None:
    for row_number, row in enumerate(values[1:], start=2):
        if len(row) >= 3 and row[0] == report_date and row[1:3] == [PLATFORM, REGION]:
            return row_number
    return None


def previous_month_totals(
    values: list[list[str]], report_date: str
) -> tuple[str, int, int] | None:
    candidates: list[tuple[str, int, int]] = []
    month_prefix = report_date[:7]
    previous_date = (datetime.fromisoformat(report_date) - timedelta(days=1)).date().isoformat()
    for row in values[1:]:
        if (
            len(row) < 15
            or row[1] != PLATFORM
            or row[2] != REGION
            or row[0] != previous_date
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
    return max(candidates, key=lambda item: item[0])


def main() -> None:
    base_dir = Path(__file__).resolve().parent
    env = load_env(base_dir / ".env")
    sheet_id = env.get("GOOGLE_SHEET_ID", "")
    credentials_path = (base_dir / env.get("GOOGLE_CREDENTIALS_FILE", "")).resolve()
    profile_dir = base_dir / ".metricool-browser-profile"

    if not sheet_id:
        raise RuntimeError("Google Sheets configuration is missing")

    today_beijing = datetime.now(timezone(timedelta(hours=8))).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    report_date = (today_beijing - timedelta(days=1)).date().isoformat()
    (
        followers,
        net_growth,
        _period_views,
        _period_interactions,
        month_views,
        month_interactions,
        published_count,
        month_published_count,
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
            range_name="A1:Q1",
            value_input_option="RAW",
        )

    previous_totals = previous_month_totals(values, report_date)
    if previous_totals is None or month_views is None or month_interactions is None:
        views = ""
        interactions = ""
    else:
        previous_date, previous_views, previous_interactions = previous_totals
        views = (
            month_views - previous_views
            if previous_date >= POST_VIEW_SCOPE_START
            else ""
        )
        interactions = month_interactions - previous_interactions

    status = "success" if all(v is not None for v in (
        month_views, month_interactions, published_count, month_published_count
    )) else "partial_metricool_posts_unavailable"
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
        status,
        month_views if month_views is not None else "",
        month_interactions if month_interactions is not None else "",
        published_count if published_count is not None else "",
        month_published_count if month_published_count is not None else "",
    ]

    existing_row = find_existing_row(values, report_date)
    if existing_row:
        daily_sheet.update(
            values=[row],
            range_name=f"A{existing_row}:Q{existing_row}",
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
            status,
            (
                f"{action}; source=Metricool; "
                f"month_views_scope=posts_published_in_month; "
                f"daily_metrics=month_snapshot_delta; "
                f"published_count={published_count}; "
                f"month_published_count={month_published_count}"
            ),
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
    print(f"PUBLISHED_COUNT={published_count}")
    print(f"MONTH_PUBLISHED_COUNT={month_published_count}")
    print(f"SHEET_ACTION={action}")
    print(f"STATUS={status}")
    if status != "success":
        print("WARNING=Audience saved; Metricool post metrics unavailable (not zero).")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
