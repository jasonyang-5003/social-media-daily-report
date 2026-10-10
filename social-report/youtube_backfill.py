"""Backfill YouTube publication counts from the uploads playlist."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

import gspread

from discord_test import load_env
from youtube_channels import CHANNELS
from youtube_daily import DAILY_HEADERS, PLATFORM, YouTubeClient


def find_row(values, date, region):
    for n, row in enumerate(values[1:], 2):
        if len(row) >= 3 and row[0] == date and row[1] == PLATFORM and row[2] == region: return n
    return None


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--auto", action="store_true"); parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not args.auto: parser.error("Use --auto")
    base = Path(__file__).resolve().parent; env = load_env(base / ".env")
    api_key, sheet_id = env.get("YOUTUBE_API_KEY", ""), env.get("GOOGLE_SHEET_ID", "")
    if not api_key or not sheet_id: raise RuntimeError("YouTube or Google Sheets configuration is missing")
    beijing = timezone(timedelta(hours=8)); today = datetime.now(beijing).date(); start_day, end_day = today-timedelta(days=29), today-timedelta(days=2); query_start=start_day.replace(day=1)
    sheets=gspread.service_account(filename=str((base/env["GOOGLE_CREDENTIALS_FILE"]).resolve())); book=sheets.open_by_key(sheet_id); sheet,log=book.worksheet("daily_metrics"),book.worksheet("run_logs"); values=sheet.get_all_values()
    if not values or values[0] != DAILY_HEADERS: raise RuntimeError("Unexpected daily_metrics schema")
    client=YouTubeClient(api_key); total=0
    for key, config in CHANNELS.items():
        channel=client.channel(config["channel_id"]); uploads=channel.get("contentDetails",{}).get("relatedPlaylists",{}).get("uploads","")
        videos=client.video_metrics(client.upload_video_ids(uploads)); counts={}
        for video in videos:
            if not video.get("published_at"): continue
            day=datetime.fromisoformat(video["published_at"].replace("Z","+00:00"))
            # normalize publishedAt to Beijing calendar day
            day=day.astimezone(beijing).date()
            if query_start <= day <= end_day: counts[day.isoformat()]=counts.get(day.isoformat(),0)+1
        for offset in range((end_day-start_day).days+1):
            day=start_day+timedelta(days=offset); key_date=day.isoformat(); cumulative=sum(count for date_key,count in counts.items() if date_key[:7] == key_date[:7] and date_key <= key_date); idx=find_row(values,key_date,config["region"]); old=values[idx-1] if idx else []; row=(list(old)+[""]*len(DAILY_HEADERS))[:len(DAILY_HEADERS)]
            if not old: row[:3]=[key_date,PLATFORM,config["region"]]; row[12]="partial_historical_no_snapshot"
            row[15]=counts.get(key_date,0)
            row[16]=cumulative
            if args.apply:
                current=sheet.get_all_values(); current_idx=find_row(current,key_date,config["region"])
                if current_idx:
                    old_now=current[current_idx-1]; updates=[]
                    for col,letter in ((15,"P"),(16,"Q")):
                        if row[col] != "" and (len(old_now)<=col or old_now[col] != str(row[col])): updates.append({"range":f"{letter}{current_idx}","values":[[row[col]]]})
                    if updates: sheet.batch_update(updates,value_input_option="RAW")
                else: sheet.append_row(row,value_input_option="RAW")
            total += 1
        if args.apply: log.append_row([datetime.now(timezone.utc).isoformat(timespec="seconds"),f"{PLATFORM}:{config['region']}","partial_historical_no_snapshot",f"youtube_backfill channel={key}"],value_input_option="RAW")
    print(f"BACKFILL_CHECK={start_day}..{end_day} PROPOSALS={total} MODE={'APPLY' if args.apply else 'DRY_RUN'}")


if __name__ == "__main__": main()
