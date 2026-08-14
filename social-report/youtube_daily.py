from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import gspread
import requests
from gspread.exceptions import WorksheetNotFound

from discord_test import load_env
from youtube_channels import CHANNELS


PLATFORM = "YouTube"
API_BASE = "https://www.googleapis.com/youtube/v3"
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
SNAPSHOT_HEADERS = [
    "date",
    "channel_key",
    "channel_id",
    "subscribers_total",
    "views_total",
    "interactions_total",
    "video_count",
    "collected_at",
    "month_key",
    "month_views",
    "month_interactions",
    "month_video_count",
]


class YouTubeClient:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "SocialMediaDailyReport/1.0"})

    def get(self, resource: str, params: dict) -> dict:
        response = self.session.get(
            f"{API_BASE}/{resource}",
            params={**params, "key": self.api_key},
            timeout=60,
        )
        if not response.ok:
            try:
                message = response.json()["error"]["message"]
            except (ValueError, KeyError, TypeError):
                message = f"HTTP {response.status_code}"
            raise RuntimeError(f"YouTube API request failed: {message}")
        return response.json()

    def channel(self, channel_id: str) -> dict:
        payload = self.get(
            "channels",
            {
                "part": "snippet,statistics,contentDetails",
                "id": channel_id,
                "maxResults": 1,
            },
        )
        items = payload.get("items", [])
        if not items:
            raise RuntimeError(f"YouTube channel not found: {channel_id}")
        return items[0]

    def upload_video_ids(self, uploads_playlist_id: str) -> list[str]:
        video_ids: list[str] = []
        page_token = ""
        while True:
            params = {
                "part": "contentDetails",
                "playlistId": uploads_playlist_id,
                "maxResults": 50,
            }
            if page_token:
                params["pageToken"] = page_token
            payload = self.get("playlistItems", params)
            video_ids.extend(
                item.get("contentDetails", {}).get("videoId", "")
                for item in payload.get("items", [])
                if item.get("contentDetails", {}).get("videoId")
            )
            page_token = payload.get("nextPageToken", "")
            if not page_token:
                break
        return list(dict.fromkeys(video_ids))

    def video_metrics(self, video_ids: list[str]) -> list[dict]:
        videos = []
        for index in range(0, len(video_ids), 50):
            payload = self.get(
                "videos",
                {
                    "part": "snippet,statistics",
                    "id": ",".join(video_ids[index : index + 50]),
                    "maxResults": 50,
                },
            )
            for item in payload.get("items", []):
                statistics = item.get("statistics", {})
                videos.append(
                    {
                        "id": item.get("id", ""),
                        "published_at": item.get("snippet", {}).get(
                            "publishedAt", ""
                        ),
                        "views": int(statistics.get("viewCount") or 0),
                        "interactions": (
                            int(statistics.get("likeCount") or 0)
                            + int(statistics.get("commentCount") or 0)
                        ),
                    }
                )
        return videos


def ensure_headers(sheet, headers: list[str]) -> list[list[str]]:
    if sheet.col_count < len(headers):
        sheet.add_cols(len(headers) - sheet.col_count)
    values = sheet.get_all_values()
    if not values:
        sheet.append_row(headers, value_input_option="RAW")
        return [headers]
    if values[0] != headers:
        end_column = chr(ord("A") + len(headers) - 1)
        sheet.update(
            values=[headers],
            range_name=f"A1:{end_column}1",
            value_input_option="RAW",
        )
        values[0] = headers
    return values


def parse_int(value: str) -> int | None:
    if value == "":
        return None
    try:
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return None


def snapshot_rows(values: list[list[str]], channel_key: str) -> list[dict]:
    rows = []
    for row in values[1:]:
        if len(row) < 4 or row[1] != channel_key:
            continue
        subscribers = parse_int(row[3])
        month_views = parse_int(row[9]) if len(row) > 9 else None
        month_interactions = parse_int(row[10]) if len(row) > 10 else None
        if subscribers is None:
            continue
        rows.append(
            {
                "date": row[0],
                "subscribers": subscribers,
                "month_key": row[8] if len(row) > 8 else "",
                "month_views": month_views,
                "month_interactions": month_interactions,
            }
        )
    return sorted(rows, key=lambda item: item["date"])


def upsert_snapshot(sheet, values: list[list[str]], row: list) -> None:
    for row_number, existing in enumerate(values[1:], start=2):
        if len(existing) >= 2 and existing[0] == row[0] and existing[1] == row[1]:
            sheet.update(
                values=[row],
                range_name=f"A{row_number}:L{row_number}",
                value_input_option="USER_ENTERED",
            )
            return
    sheet.append_row(row, value_input_option="USER_ENTERED")


def upsert_daily(sheet, values: list[list[str]], row: list) -> str:
    for row_number, existing in enumerate(values[1:], start=2):
        if (
            len(existing) >= 3
            and existing[0] == row[0]
            and existing[1] == PLATFORM
            and existing[2] == row[2]
        ):
            sheet.update(
                values=[row],
                range_name=f"A{row_number}:Q{row_number}",
                value_input_option="USER_ENTERED",
            )
            return "updated"
    sheet.append_row(row, value_input_option="USER_ENTERED")
    return "inserted"


def calculate_deltas(
    history: list[dict],
    report_date: str,
    month_key: str,
    subscribers: int,
    month_views: int,
    month_interactions: int,
) -> tuple[int | str, int | str, int | str, str]:
    previous_date = (
        datetime.fromisoformat(report_date).date() - timedelta(days=1)
    ).isoformat()
    previous = next(
        (item for item in reversed(history) if item["date"] == previous_date), None
    )
    if previous is None:
        net_growth: int | str = ""
        daily_views: int | str = ""
        daily_interactions: int | str = ""
    else:
        net_growth = subscribers - previous["subscribers"]
        if (
            previous.get("month_key") == month_key
            and previous.get("month_views") is not None
            and previous.get("month_interactions") is not None
        ):
            daily_views = month_views - previous["month_views"]
            daily_interactions = (
                month_interactions - previous["month_interactions"]
            )
        elif report_date.endswith("-01"):
            daily_views = month_views
            daily_interactions = month_interactions
        else:
            daily_views = ""
            daily_interactions = ""

    status = "success" if previous is not None else "success_no_daily_baseline"
    return net_growth, daily_views, daily_interactions, status


def main() -> None:
    base_dir = Path(__file__).resolve().parent
    env = load_env(base_dir / ".env")
    api_key = env.get("YOUTUBE_API_KEY", "")
    sheet_id = env.get("GOOGLE_SHEET_ID", "")
    credentials_path = (base_dir / env.get("GOOGLE_CREDENTIALS_FILE", "")).resolve()
    if not api_key or not sheet_id:
        raise RuntimeError("YOUTUBE_API_KEY or GOOGLE_SHEET_ID is missing")

    beijing = timezone(timedelta(hours=8))
    report_day = datetime.now(beijing).date() - timedelta(days=1)
    report_date = report_day.isoformat()
    month_key = report_date[:7]
    month_start = report_day.replace(day=1)
    collected_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    youtube = YouTubeClient(api_key)

    sheets = gspread.service_account(filename=str(credentials_path))
    workbook = sheets.open_by_key(sheet_id)
    daily_sheet = workbook.worksheet("daily_metrics")
    log_sheet = workbook.worksheet("run_logs")
    try:
        snapshot_sheet = workbook.worksheet("youtube_snapshots")
    except WorksheetNotFound:
        snapshot_sheet = workbook.add_worksheet(
            title="youtube_snapshots", rows=2000, cols=len(SNAPSHOT_HEADERS)
        )

    daily_values = ensure_headers(daily_sheet, DAILY_HEADERS)
    snapshot_values = ensure_headers(snapshot_sheet, SNAPSHOT_HEADERS)

    for channel_key, config in CHANNELS.items():
        channel = youtube.channel(config["channel_id"])
        title = channel.get("snippet", {}).get("title", "")
        if title != config["name"]:
            raise RuntimeError(
                f"YouTube channel identity mismatch for {channel_key}: {title}"
            )
        statistics = channel.get("statistics", {})
        subscribers = int(statistics.get("subscriberCount") or 0)
        views = int(statistics.get("viewCount") or 0)
        video_count = int(statistics.get("videoCount") or 0)
        uploads_id = (
            channel.get("contentDetails", {})
            .get("relatedPlaylists", {})
            .get("uploads", "")
        )
        if not uploads_id:
            raise RuntimeError(f"Uploads playlist unavailable for {title}")

        video_ids = youtube.upload_video_ids(uploads_id)
        videos = youtube.video_metrics(video_ids)
        interactions_total = sum(video["interactions"] for video in videos)
        month_videos = []
        for video in videos:
            published_at = video.get("published_at", "")
            if not published_at:
                continue
            published_day = datetime.fromisoformat(
                published_at.replace("Z", "+00:00")
            ).astimezone(beijing).date()
            if month_start <= published_day <= report_day:
                month_videos.append(video)
        month_views = sum(video["views"] for video in month_videos)
        month_interactions = sum(
            video["interactions"] for video in month_videos
        )
        published_count = sum(
            1
            for video in month_videos
            if datetime.fromisoformat(
                video["published_at"].replace("Z", "+00:00")
            ).astimezone(beijing).date()
            == report_day
        )
        history = snapshot_rows(snapshot_values, channel_key)
        (
            net_growth,
            daily_views,
            daily_interactions,
            status,
        ) = calculate_deltas(
            history,
            report_date,
            month_key,
            subscribers,
            month_views,
            month_interactions,
        )

        daily_row = [
            report_date,
            PLATFORM,
            config["region"],
            subscribers,
            "",
            "",
            net_growth,
            "",
            daily_views,
            "",
            "",
            daily_interactions,
            status,
            month_views,
            month_interactions,
            published_count,
            len(month_videos),
        ]
        action = upsert_daily(daily_sheet, daily_values, daily_row)
        daily_values = daily_sheet.get_all_values()

        snapshot_row = [
            report_date,
            channel_key,
            config["channel_id"],
            subscribers,
            views,
            interactions_total,
            video_count,
            collected_at,
            month_key,
            month_views,
            month_interactions,
            len(month_videos),
        ]
        upsert_snapshot(snapshot_sheet, snapshot_values, snapshot_row)
        snapshot_values = snapshot_sheet.get_all_values()

        log_sheet.append_row(
            [
                collected_at,
                f"YouTube:{config['region']}",
                "success",
                (
                    f"{action}; videos={len(video_ids)}; "
                    f"month_videos={len(month_videos)}; "
                    f"month_scope=videos_published_in_beijing_month; "
                    f"public_interactions=likes_plus_comments; "
                    f"published_count={published_count}; "
                    f"month_published_count={len(month_videos)}; status={status}"
                ),
            ],
            value_input_option="RAW",
        )

        print(f"CHANNEL={title}")
        print(f"REPORT_DATE={report_date}")
        print(f"SUBSCRIBERS={subscribers}")
        print(f"NET_GROWTH={net_growth}")
        print(f"DAILY_VIEWS={daily_views}")
        print(f"DAILY_INTERACTIONS={daily_interactions}")
        print(f"MONTH_VIEWS={month_views}")
        print(f"MONTH_INTERACTIONS={month_interactions}")
        print(f"PUBLISHED_COUNT={published_count}")
        print(f"MONTH_PUBLISHED_COUNT={len(month_videos)}")
        print(f"VIDEOS_SCANNED={len(video_ids)}")
        print(f"MONTH_VIDEOS={len(month_videos)}")
        print(f"SHEET_ACTION={action}")


if __name__ == "__main__":
    main()
