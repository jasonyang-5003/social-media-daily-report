from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import gspread

from discord_test import load_env


ENTITY_CONFIG = {
    ("Facebook", "LATAM"): {
        "id": "facebook",
        "label": "Facebook LATAM",
        "group": "社媒主页",
        "color": "#1877F2",
        "audience_label": "关注者",
    },
    ("X", "North America"): {
        "id": "x",
        "label": "X US",
        "group": "社媒主页",
        "color": "#111827",
        "audience_label": "关注者",
    },
    ("Discord", "LATAM"): {
        "id": "discord-latam",
        "label": "Discord LATAM",
        "group": "Discord 社区",
        "color": "#5865F2",
        "audience_label": "成员",
    },
    ("Discord", "Global"): {
        "id": "discord-global",
        "label": "Discord Global",
        "group": "Discord 社区",
        "color": "#7C3AED",
        "audience_label": "成员",
    },
    ("YouTube", "Mary"): {
        "id": "youtube-mary",
        "label": "YouTube · Mary",
        "group": "YouTube 频道",
        "color": "#FF0033",
        "audience_label": "订阅者",
    },
    ("YouTube", "UgScript"): {
        "id": "youtube-ugscript",
        "label": "YouTube · UgScript",
        "group": "YouTube 频道",
        "color": "#F97316",
        "audience_label": "订阅者",
    },
}


def number(value) -> int | float | None:
    if value in (None, ""):
        return None
    try:
        parsed = float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return int(parsed) if parsed.is_integer() else parsed


def main() -> None:
    base_dir = Path(__file__).resolve().parent
    root_dir = base_dir.parent
    env = load_env(base_dir / ".env")
    credentials_path = (base_dir / env["GOOGLE_CREDENTIALS_FILE"]).resolve()
    workbook = gspread.service_account(filename=str(credentials_path)).open_by_key(
        env["GOOGLE_SHEET_ID"]
    )
    rows = workbook.worksheet("daily_metrics").get_all_records()

    entities = []
    for (platform, region), config in ENTITY_CONFIG.items():
        points = []
        for row in rows:
            if str(row.get("platform", "")) != platform or str(
                row.get("region", "")
            ) != region:
                continue
            date = str(row.get("date", ""))
            if not date:
                continue
            points.append(
                {
                    "date": date,
                    "audience": number(row.get("followers_total")),
                    "netGrowth": number(row.get("net_growth")),
                    "views": number(row.get("impressions")),
                    "interactions": number(row.get("interactions")),
                    "monthViews": number(row.get("month_views")),
                    "monthInteractions": number(row.get("month_interactions")),
                    "activeMembers": number(row.get("active_members")),
                    "activeRate": number(row.get("active_rate")),
                    "publishedCount": number(row.get("published_count")),
                    "monthPublished": number(row.get("month_published_count")),
                    "status": str(row.get("status", "")),
                }
            )
        points.sort(key=lambda item: item["date"])
        entities.append({**config, "points": points})

    output = {
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "timezone": "Asia/Shanghai",
        "entities": entities,
    }
    output_dir = root_dir / "dashboard" / "data"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "metrics.json"
    output_path.write_text(
        json.dumps(output, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(f"DASHBOARD_DATA={output_path}")
    print(f"ENTITIES={len(entities)}")
    print(f"POINTS={sum(len(entity['points']) for entity in entities)}")


if __name__ == "__main__":
    main()
