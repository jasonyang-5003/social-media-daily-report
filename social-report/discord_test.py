from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests


BASE_URL = "https://discord.com/api/v10"
DISCORD_EPOCH_MS = 1420070400000


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def datetime_to_snowflake(value: datetime) -> int:
    timestamp_ms = int(value.timestamp() * 1000)
    return (timestamp_ms - DISCORD_EPOCH_MS) << 22


def snowflake_to_datetime(snowflake: str | int) -> datetime:
    timestamp_ms = (int(snowflake) >> 22) + DISCORD_EPOCH_MS
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)


class DiscordClient:
    def __init__(self, token: str) -> None:
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bot {token}",
                "User-Agent": "SocialMediaDailyReport/1.0",
            }
        )

    def get(self, path: str, params: dict | None = None):
        url = f"{BASE_URL}{path}"
        for _ in range(4):
            response = self.session.get(url, params=params, timeout=30)
            if response.status_code != 429:
                response.raise_for_status()
                return response.json()
            retry_after = min(float(response.json().get("retry_after", 1)), 10)
            time.sleep(retry_after)
        raise RuntimeError("Discord API rate limit retry exhausted")


def collect_active_users(
    client: DiscordClient,
    channel_ids: list[str],
    start: datetime,
    end: datetime,
) -> tuple[set[str], int, int]:
    active_users: set[str] = set()
    readable_channels = 0
    skipped_channels = 0
    start_snowflake = datetime_to_snowflake(start)

    for channel_id in channel_ids:
        cursor = start_snowflake
        channel_readable = False
        try:
            while True:
                messages = client.get(
                    f"/channels/{channel_id}/messages",
                    params={"limit": 100, "after": str(cursor)},
                )
                channel_readable = True
                if not messages:
                    break

                messages = sorted(messages, key=lambda item: int(item["id"]))
                reached_end = False

                for message in messages:
                    created_at = snowflake_to_datetime(message["id"])
                    if created_at >= end:
                        reached_end = True
                        break
                    author = message.get("author", {})
                    if not author.get("bot") and author.get("id"):
                        active_users.add(author["id"])

                next_cursor = int(messages[-1]["id"])
                if reached_end or next_cursor <= cursor or len(messages) < 100:
                    break
                cursor = next_cursor
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code in {403, 404}:
                skipped_channels += 1
                continue
            raise

        if channel_readable:
            readable_channels += 1

    return active_users, readable_channels, skipped_channels


def main() -> None:
    env = load_env(Path(__file__).with_name(".env"))
    token = env.get("DISCORD_BOT_TOKEN", "")
    guild_id = env.get("DISCORD_GUILD_ID", "")
    if not token or not guild_id:
        raise RuntimeError("DISCORD_BOT_TOKEN or DISCORD_GUILD_ID is missing")

    client = DiscordClient(token)
    guild = client.get(f"/guilds/{guild_id}", params={"with_counts": "true"})
    channels = client.get(f"/guilds/{guild_id}/channels")

    text_channel_types = {0, 5}
    channel_ids = [
        channel["id"]
        for channel in channels
        if channel.get("type") in text_channel_types
    ]
    channel_ids = sorted(set(channel_ids))

    today_utc = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    start = today_utc - timedelta(days=1)
    end = today_utc

    active_users, readable_channels, skipped_channels = collect_active_users(
        client, channel_ids, start, end
    )
    member_count = guild.get("approximate_member_count") or 0
    active_rate = len(active_users) / member_count if member_count else 0

    print(f"GUILD_NAME={guild.get('name', '')}")
    print(f"REPORT_DATE_UTC={start.date().isoformat()}")
    print(f"MEMBER_COUNT={member_count}")
    print(f"ACTIVE_MEMBERS={len(active_users)}")
    print(f"ACTIVE_RATE={active_rate:.4%}")
    print(f"READABLE_CHANNELS={readable_channels}")
    print(f"SKIPPED_CHANNELS={skipped_channels}")


if __name__ == "__main__":
    main()
