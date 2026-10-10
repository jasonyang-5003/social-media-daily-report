"""Copy cloud metrics back to Sheets without requiring the PC for collection."""
from __future__ import annotations

import json
from pathlib import Path

import gspread
import requests

from discord_test import load_env
from youtube_daily import DAILY_HEADERS

FIELDS = {3:"audience",6:"netGrowth",8:"views",9:"activeMembers",10:"activeRate",11:"interactions",12:"status",13:"monthViews",14:"monthInteractions",15:"publishedCount",16:"monthPublished"}


def cloud_settings():
    path=Path(__file__).resolve().parent.parent / "cloud-collector" / "local-state.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def main():
    settings=cloud_settings()
    if not settings.get("enabled"):
        print("CLOUD_SYNC=NOT_ENABLED")
        return
    base=Path(__file__).resolve().parent; env=load_env(base/".env")
    response=requests.get(settings["url"]+"/metrics",timeout=60);response.raise_for_status();data=response.json()
    book=gspread.service_account(filename=str((base/env["GOOGLE_CREDENTIALS_FILE"]).resolve())).open_by_key(env["GOOGLE_SHEET_ID"])
    sheet=book.worksheet("daily_metrics");values=sheet.get_all_values()
    if not values or values[0]!=DAILY_HEADERS:raise RuntimeError("Unexpected daily_metrics schema")
    index={(row[0],row[1],row[2]):(n,row) for n,row in enumerate(values[1:],2) if len(row)>=3}
    updates=[];new=[]
    for entity in data["entities"]:
        for point in entity["points"]:
            key=(point["date"],entity["platform"],entity["region"]);found=index.get(key);old=found[1] if found else []
            row=(old+[""]*17)[:17];row[:3]=key
            for col,field in FIELDS.items():
                value=point.get(field)
                # Seeded history and missing source data must not erase valid cells.
                if value is not None:row[col]=value
            if found:
                if [str(v) for v in row]!=(old+[""]*17)[:17]:updates.append({"range":f"A{found[0]}:Q{found[0]}","values":[row]})
            else:new.append(row)
    if updates:sheet.batch_update(updates,value_input_option="RAW")
    if new:sheet.append_rows(new,value_input_option="RAW")
    failed=[job for job in data.get("health",[]) if job["state"]=="failed"]
    print(f"CLOUD_SYNC=SUCCESS UPDATED={len(updates)} INSERTED={len(new)} FAILURES={len(failed)}")
    if failed:raise RuntimeError("Cloud collector account/API errors; inspect dashboard")


if __name__=="__main__":main()
