"""Reuse retained Apify snapshots without launching new paid runs.

--retry-zero-cost-today retries only today's definitively failed zero-cost run.
Existing paid runs and valid snapshots are never replaced.
"""
import argparse
import json
import os
import tomllib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from deploy import BASE, ROOT, api, load_env


def query(sql):
    auth = tomllib.loads((Path(os.environ["APPDATA"]) / "xdg.config/.wrangler/config/default.toml").read_text(encoding="utf-8"))
    response = requests.post("https://api.cloudflare.com/client/v4/accounts/7b5cebe6684ca0c4dac448600b6dcd9e/d1/database/f9564ea6-2a2c-4e31-b087-d4b3bbdc55a3/query", headers={"Authorization": "Bearer " + auth["oauth_token"]}, json={"sql": sql}, timeout=60)
    response.raise_for_status()
    body = response.json()
    if not body.get("success"):
        raise RuntimeError("D1 recovery query failed")
    result = body["result"]
    return result[0].get("results", [])


def literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--retry-zero-cost-today", action="store_true")
    parser.add_argument("--start", help="Process saved jobs on or after YYYY-MM-DD")
    args = parser.parse_args()
    state = json.loads((BASE / "local-state.json").read_text(encoding="utf-8"))
    env = load_env(ROOT / "social-report/.env")
    headers = {"Authorization": "Bearer " + env["APIFY_API_TOKEN"]}
    start = datetime.fromisoformat(args.start).date().isoformat() if args.start else None
    jobs = query("SELECT * FROM jobs WHERE entity='x' AND state='failed'" +
                 (" AND date>=" + literal(start) if start else "") + " ORDER BY date")
    backup = ROOT / "social-report/logs" / ("x-recovery-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".json")
    backup.write_text(json.dumps({"jobs": jobs, "metrics": query("SELECT * FROM metrics WHERE entity='x'")}), encoding="utf-8")
    today = (datetime.now(timezone(timedelta(hours=8))).date() - timedelta(days=1)).isoformat()
    recovered = []
    for job in jobs:
        existing = query("SELECT data FROM metrics WHERE entity='x' AND date=" + literal(job["date"]))
        if existing and json.loads(existing[0]["data"]).get("status") == "success":
            print(f"SKIP={job['date']} valid_snapshot_preserved", flush=True)
            continue
        payload = json.loads(job["payload"])
        run_id = payload.get("runId")
        if not run_id:
            continue
        response = requests.get(f"https://api.apify.com/v2/actor-runs/{run_id}", headers=headers, timeout=30)
        if not response.ok:
            print(f"SKIP={job['date']} saved_run_unavailable HTTP={response.status_code}", flush=True)
            continue
        run = response.json()["data"]
        retry_marker = ROOT / "social-report/logs" / ("x-manual-retry-" + job["date"] + ".json")
        retry = args.retry_zero_cost_today and job["date"] == today and run["status"] == "FAILED" and float(run.get("usageTotalUsd") or 0) == 0 and not retry_marker.exists()
        if run["status"] != "SUCCEEDED" and not retry:
            print(f"SKIP={job['date']} status={run['status']}", flush=True)
            continue
        if retry:
            # Record before dispatch; never create duplicate paid work on a
            # network timeout or a repeated invocation of this repair utility.
            retry_marker.write_text(json.dumps({"previousRun": run_id, "date": job["date"]}), encoding="utf-8")
            new_payload = {}
        else:
            # Re-run only validation/dataset stages; xStart is never called.
            new_payload = {"stage": "poll", "runId": run_id, "started": payload.get("started", 0)}
        query("UPDATE jobs SET state='pending',attempts=0,ready_at=0,lease_until=0,error=NULL,payload=" + literal(json.dumps(new_payload)) + " WHERE id=" + literal(job["id"]) + " AND state='failed'")
        api(state["url"], state["admin_token"], "/internal/job", {"id": job["id"]})
        if not retry:
            api(state["url"], state["admin_token"], "/internal/job", {"id": job["id"]})
        updated = query("SELECT state,error FROM jobs WHERE id=" + literal(job["id"]))[0]
        print(f"RECOVERY={job['date']} state={updated['state']} error={updated.get('error') or '-'} new_run={retry}", flush=True)
        if updated["state"] == "done":
            recovered.append(job["date"])
    print("RECOVERED=" + ",".join(recovered), flush=True)


if __name__ == "__main__":
    main()
