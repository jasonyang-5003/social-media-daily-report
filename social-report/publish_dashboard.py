from __future__ import annotations

import subprocess
import time
from pathlib import Path


def run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )


def require_success(result: subprocess.CompletedProcess[str], label: str) -> None:
    if result.returncode == 0:
        return
    detail = (result.stderr or result.stdout).strip()
    raise RuntimeError(f"{label} failed: {detail or f'exit={result.returncode}'}")


def run_with_retry(
    command: list[str],
    cwd: Path,
    label: str,
    attempts: int = 3,
) -> subprocess.CompletedProcess[str]:
    for attempt in range(1, attempts + 1):
        result = run(command, cwd)
        if result.returncode == 0:
            return result
        detail = (result.stderr or result.stdout).strip() or f"exit={result.returncode}"
        print(f"{label.upper()}_ATTEMPT_{attempt}=FAILED: {detail}", flush=True)
        if attempt < attempts:
            time.sleep(5)
    require_success(result, label)
    return result


def main() -> None:
    root_dir = Path(__file__).resolve().parent.parent
    data_file = "dashboard/data/metrics.json"

    run_with_retry(["git", "add", "--", data_file], root_dir, "Git stage")
    changed = run(["git", "diff", "--cached", "--quiet", "--", data_file], root_dir)
    if changed.returncode == 0:
        print("DASHBOARD_PUBLISH=SKIPPED_NO_DATA_CHANGE")
        return
    if changed.returncode != 1:
        require_success(changed, "Git diff")

    require_success(
        run(["git", "commit", "-m", "Update dashboard metrics"], root_dir),
        "Git commit",
    )
    run_with_retry(["git", "push", "origin", "main"], root_dir, "Git push")
    print("DASHBOARD_PUBLISH=SUCCESS")


if __name__ == "__main__":
    main()
