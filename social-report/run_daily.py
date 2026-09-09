from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


COLLECTORS = [
    ("Discord", "discord_daily.py"),
    ("X", "x_daily.py"),
    ("Facebook", "facebook_daily.py"),
    ("YouTube", "youtube_daily.py"),
    ("Dashboard data", "export_dashboard_data.py"),
    ("Dashboard publish", "publish_dashboard.py"),
]


def run_collector(base_dir: Path, platform: str, script_name: str) -> bool:
    print(f"\n===== {platform} START =====", flush=True)
    result = subprocess.run(
        [sys.executable, str(base_dir / script_name)],
        cwd=base_dir,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )

    if result.stdout:
        print(result.stdout.rstrip(), flush=True)
    if result.stderr:
        print(result.stderr.rstrip(), flush=True)

    if result.returncode == 0:
        print(f"===== {platform} SUCCESS =====", flush=True)
        return True

    print(
        f"===== {platform} FAILED (exit={result.returncode}) =====",
        flush=True,
    )
    return False


def main() -> int:
    base_dir = Path(__file__).resolve().parent
    started_at = datetime.now().astimezone()
    print(f"DAILY_REPORT_STARTED={started_at.isoformat(timespec='seconds')}")

    results = {
        platform: run_collector(base_dir, platform, script_name)
        for platform, script_name in COLLECTORS
    }
    succeeded = [platform for platform, ok in results.items() if ok]
    failed = [platform for platform, ok in results.items() if not ok]
    finished_at = datetime.now().astimezone()

    print("\n===== DAILY REPORT SUMMARY =====")
    print(f"SUCCEEDED={','.join(succeeded) if succeeded else 'none'}")
    print(f"FAILED={','.join(failed) if failed else 'none'}")
    print(f"DAILY_REPORT_FINISHED={finished_at.isoformat(timespec='seconds')}")

    if failed:
        message = "社媒日报异常：" + "、".join(failed) + " 采集失败，请检查账号封禁、授权或接口状态。"
        try:
            subprocess.run(["msg.exe", "*", message], check=False, capture_output=True)
        except OSError:
            pass

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
