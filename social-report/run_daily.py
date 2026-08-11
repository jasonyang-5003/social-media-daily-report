from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path


COLLECTORS = [
    ("Discord", "discord_daily.py"),
    ("X", "x_daily.py"),
    ("Facebook", "facebook_daily.py"),
    ("YouTube", "youtube_daily.py"),
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
        print(result.stderr.rstrip(), file=sys.stderr, flush=True)

    if result.returncode == 0:
        print(f"===== {platform} SUCCESS =====", flush=True)
        return True

    print(
        f"===== {platform} FAILED (exit={result.returncode}) =====",
        file=sys.stderr,
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
    results["PNG"] = run_collector(base_dir, "PNG", "generate_pdf.py")

    succeeded = [platform for platform, ok in results.items() if ok]
    failed = [platform for platform, ok in results.items() if not ok]
    finished_at = datetime.now().astimezone()

    print("\n===== DAILY REPORT SUMMARY =====")
    print(f"SUCCEEDED={','.join(succeeded) if succeeded else 'none'}")
    print(f"FAILED={','.join(failed) if failed else 'none'}")
    print(f"DAILY_REPORT_FINISHED={finished_at.isoformat(timespec='seconds')}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
