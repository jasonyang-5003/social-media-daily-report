from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import gspread

from discord_test import DiscordClient, collect_active_users, load_env


PLATFORM = "Discord"
REGION = "LATAM"
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


def find_existing_row(values: list[list[str]], report_date: str) -> int | None:
    for row_number, row in enumerate(values[1:], start=2):
        if len(row) >= 2 and row[0] == report_date and row[1] == PLATFORM:
            return row_number
    return None


def previous_member_count(values: list[list[str]], report_date: str) -> int | None:
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


def main() -> None:
    base_dir = Path(__file__).resolve().parent
    env = load_env(base_dir / ".env")
    token = env.get("DISCORD_BOT_TOKEN", "")
    guild_id = env.get("DISCORD_GUILD_ID", "")
    sheet_id = env.get("GOOGLE_SHEET_ID", "")
    credentials_path = (base_dir / env.get("GOOGLE_CREDENTIALS_FILE", "")).resolve()

    if not token or not guild_id or not sheet_id:
        raise RuntimeError("Discord or Google Sheets configuration is missing")

    today_utc = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    start = today_utc - timedelta(days=1)
    end = today_utc
    report_date = start.date().isoformat()

    discord = DiscordClient(token)
    guild = discord.get(f"/guilds/{guild_id}", params={"with_counts": "true"})
    channels = discord.get(f"/guilds/{guild_id}/channels")
    channel_ids = sorted(
        {
            channel["id"]
            for channel in channels
            if channel.get("type") in {0, 5}
        }
    )

    active_users, readable_channels, skipped_channels = collect_active_users(
        discord, channel_ids, start, end
    )
    member_count = int(guild.get("approximate_member_count") or 0)
    active_rate = len(active_users) / member_count if member_count else 0

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

    previous_count = previous_member_count(values, report_date)
    net_growth = member_count - previous_count if previous_count is not None else ""
    row = [
        report_date,
        PLATFORM,
        REGION,
        member_count,
        "",
        "",
        net_growth,
        "",
        "",
        len(active_users),
        active_rate,
        "",
        "success",
        "",
        "",
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
            f"{action}; readable_channels={readable_channels}; skipped_channels={skipped_channels}",
        ],
        value_input_option="RAW",
    )

    print(f"REPORT_DATE={report_date}")
    print(f"MEMBER_COUNT={member_count}")
    print(f"NET_GROWTH={net_growth}")
    print(f"ACTIVE_MEMBERS={len(active_users)}")
    print(f"ACTIVE_RATE={active_rate:.4%}")
    print(f"SHEET_ACTION={action}")


if __name__ == "__main__":
    main()
