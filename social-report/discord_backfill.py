"""Recover Discord message counts and active members from message history."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

import gspread

from discord_servers import DISCORD_SERVERS
from discord_test import DiscordClient, datetime_to_snowflake, snowflake_to_datetime, load_env
import requests
from discord_daily import DAILY_HEADERS, PLATFORM, find_existing_row


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--auto", action="store_true"); parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not args.auto: parser.error("Use --auto")
    base = Path(__file__).resolve().parent; env = load_env(base / ".env")
    token, sheet_id = env.get("DISCORD_BOT_TOKEN", ""), env.get("GOOGLE_SHEET_ID", "")
    if not token or not sheet_id: raise RuntimeError("Discord or Google Sheets configuration is missing")
    beijing = timezone(timedelta(hours=8)); today = datetime.now(beijing).date()
    start_day, end_day = today - timedelta(days=29), today - timedelta(days=2)
    sheets = gspread.service_account(filename=str((base / env["GOOGLE_CREDENTIALS_FILE"]).resolve()))
    book = sheets.open_by_key(sheet_id); sheet, log = book.worksheet("daily_metrics"), book.worksheet("run_logs")
    values = sheet.get_all_values()
    if not values or values[0] != DAILY_HEADERS: raise RuntimeError("Unexpected daily_metrics schema")
    client = DiscordClient(token); proposals = 0
    for server in DISCORD_SERVERS:
        region = server["region"]; guild_id = server.get("guild_id") or env.get(server.get("guild_id_env", ""), "")
        if not guild_id: continue
        targets=[]
        for offset in range((end_day-start_day).days+1):
            date_key=(start_day+timedelta(days=offset)).isoformat(); idx=find_existing_row(values,date_key,region); row=values[idx-1] if idx else []
            if not idx or len(row)<=16 or row[9]=="" or row[15]=="" or row[16]=="": targets.append(date_key)
        if not targets:
            print(f"REGION={region} TARGETS=0")
            continue
        channels = client.get(f"/guilds/{guild_id}/channels")
        channel_ids = sorted({c["id"] for c in channels if c.get("type") in {0, 5}})
        month_start = start_day.replace(day=1)
        daily_users = {}; daily_counts = {}
        range_start = datetime.combine(month_start, datetime.min.time(), beijing).astimezone(timezone.utc)
        range_end = datetime.combine(end_day + timedelta(days=1), datetime.min.time(), beijing).astimezone(timezone.utc)
        for channel_id in channel_ids:
            cursor = datetime_to_snowflake(range_start)
            try:
                while True:
                    messages = client.get(f"/channels/{channel_id}/messages", params={"limit": 100, "after": str(cursor)})
                    if not messages: break
                    messages = sorted(messages, key=lambda item: int(item["id"]))
                    stop = False
                    for message in messages:
                        created = snowflake_to_datetime(message["id"])
                        if created >= range_end: stop = True; break
                        author = message.get("author", {})
                        if author.get("bot") or not author.get("id"): continue
                        day = created.astimezone(beijing).date().isoformat()
                        daily_counts[day] = daily_counts.get(day, 0) + 1
                        daily_users.setdefault(day, set()).add(author["id"])
                    next_cursor = int(messages[-1]["id"])
                    if stop or len(messages) < 100 or next_cursor <= cursor: break
                    cursor = next_cursor
            except requests.HTTPError as exc:
                if exc.response is not None and exc.response.status_code in {403, 404}:
                    continue
                raise
        for offset in range((end_day - start_day).days + 1):
            day = start_day + timedelta(days=offset); key_date = day.isoformat()
            published = daily_counts.get(key_date, 0); users = daily_users.get(key_date, set())
            cumulative = sum(count for date_key, count in daily_counts.items() if date_key[:7] == key_date[:7] and date_key <= key_date)
            idx = find_existing_row(values, day.isoformat(), region)
            old = values[idx - 1] if idx else []
            row = (list(old) + [""] * len(DAILY_HEADERS))[: len(DAILY_HEADERS)]
            if not old: row[:3] = [day.isoformat(), PLATFORM, region]; row[12] = "partial_historical_no_snapshot"
            if row[9] == "": row[9] = len(users)
            row[15] = published
            row[16] = cumulative
            if row[3] not in ("", None) and row[10] == "":
                try: row[10] = len(users) / int(float(str(row[3]).replace(",", "")))
                except (ValueError, ZeroDivisionError): pass
            if args.apply:
                current = sheet.get_all_values(); current_idx = find_existing_row(current, day.isoformat(), region)
                if current_idx:
                    old_now = current[current_idx - 1]; updates=[]
                    for col, letter in ((9,"J"),(10,"K"),(15,"P"),(16,"Q")):
                        if row[col] != "" and (len(old_now) <= col or old_now[col] != str(row[col])): updates.append({"range": f"{letter}{current_idx}", "values": [[row[col]]]})
                    if updates: sheet.batch_update(updates, value_input_option="RAW")
                else: sheet.append_row(row, value_input_option="RAW")
            proposals += 1
        if args.apply: log.append_row([datetime.now(timezone.utc).isoformat(timespec="seconds"), f"{PLATFORM}/{region}", "partial_historical_no_snapshot", f"discord_backfill days={end_day-start_day+timedelta(days=1)}"], value_input_option="RAW")
    print(f"BACKFILL_CHECK={start_day}..{end_day} PROPOSALS={proposals} MODE={'APPLY' if args.apply else 'DRY_RUN'}")


if __name__ == "__main__": main()
