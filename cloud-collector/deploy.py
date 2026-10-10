"""Deploy using existing local credentials; never print or commit tokens.

Run setup first, then activate only after a live cloud collection succeeds.
"""
from __future__ import annotations

import argparse
import json
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import requests

BASE=Path(__file__).resolve().parent
ROOT=BASE.parent
sys.path.insert(0,str(ROOT/"social-report"))
from discord_test import load_env


def cli(*args, secret_input=None):
    npx=shutil.which("npx.cmd") or shutil.which("npx")
    result=subprocess.run([npx,"--yes","wrangler@4.149.0",*args],cwd=BASE,input=secret_input,capture_output=True,text=True,encoding="utf-8",errors="replace")
    if result.returncode:
        # Wrangler never receives secrets as command-line arguments.
        raise RuntimeError("Cloudflare command failed: "+result.stderr[-2000:])
    return result.stdout


def api(url,token,path,body):
    response=requests.post(url+path,headers={"Authorization":"Bearer "+token},json=body,timeout=60)
    response.raise_for_status();return response.json()


def setup():
    env=load_env(ROOT/"social-report/.env")
    required=("DISCORD_BOT_TOKEN","DISCORD_GUILD_ID","APIFY_API_TOKEN","YOUTUBE_API_KEY")
    if any(not env.get(key) for key in required):raise RuntimeError("A required source credential is missing")
    listing=json.loads(cli("d1","list","--json"))
    found=next((item for item in listing if item["name"]=="social-media-metrics"),None)
    if found:db_id=found["uuid"]
    else:
        output=cli("d1","create","social-media-metrics")
        match=re.search(r'"database_id"\s*:\s*"([0-9a-f-]+)"',output)
        if not match:raise RuntimeError("Database created; inspect wrangler output to configure its ID")
        db_id=match.group(1)
    config=json.loads((BASE/"wrangler.jsonc").read_text(encoding="utf-8"))
    config["d1_databases"][0]["database_id"]=db_id
    (BASE/"wrangler.jsonc").write_text(json.dumps(config,indent=2)+"\n",encoding="utf-8")
    cli("d1","execute","social-media-metrics","--remote","--file","schema.sql")
    state_path=BASE/"local-state.json"
    state=json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {"admin_token":secrets.token_urlsafe(36),"enabled":False}
    state_path.write_text(json.dumps(state,indent=2),encoding="utf-8")
    # Upload credentials before deploying Cron code, using an ephemeral file.
    secrets_payload={key:env[key] for key in required}
    secrets_payload["ADMIN_TOKEN"]=state["admin_token"]
    with tempfile.TemporaryDirectory(prefix="social-cloud-secrets-") as tmp:
        path=Path(tmp)/"secrets.json";path.write_text(json.dumps(secrets_payload),encoding="utf-8")
        cli("secret","bulk",str(path))
    output=cli("deploy")
    match=re.search(r'https://social-media-collector\.[a-zA-Z0-9-]+\.workers\.dev',output)
    if not match:raise RuntimeError("Worker deployed; its workers.dev URL was not found")
    url=match.group(0)
    config["vars"]["WORKER_URL"]=url
    (BASE/"wrangler.jsonc").write_text(json.dumps(config,indent=2)+"\n",encoding="utf-8")
    cli("deploy")
    state["url"]=url;state_path.write_text(json.dumps(state,indent=2),encoding="utf-8")
    snapshot=json.loads((ROOT/"dashboard/data/metrics.json").read_text(encoding="utf-8"))
    # Bound the seed request to 15 rows, below free-plan subrequest limits.
    for entity in snapshot["entities"]:
        if entity["id"]=="facebook":continue
        for offset in range(0,len(entity["points"]),15):
            api(url,state["admin_token"],"/admin/seed",{"generatedAt":snapshot["generatedAt"],"entities":[{**entity,"points":entity["points"][offset:offset+15]}]})
    api(url,state["admin_token"],"/admin/run",{})
    print("DEPLOYED="+url)
    print("HISTORY_SEEDED=YES; INITIAL_COLLECTION_STARTED=YES; LOCAL_SWITCH=NOT_YET")


def activate():
    state_path=BASE/"local-state.json";state=json.loads(state_path.read_text(encoding="utf-8"))
    response=requests.get(state["url"]+"/metrics",timeout=60);response.raise_for_status();data=response.json()
    if any(job["state"]=="failed" for job in data["health"]):raise RuntimeError("Cloud job failed; keep local collectors enabled")
    if data["health"]:raise RuntimeError("Cloud collection still pending; activation postponed")
    if len(data["entities"])!=4:raise RuntimeError("Unexpected cloud account count")
    # A seeded success row is insufficient proof. Require a real cloud timestamp.
    if any(not entity["points"] or not entity["points"][-1].get("collectedAt") for entity in data["entities"]):raise RuntimeError("Fresh cloud collection has not been verified for every account")
    state["enabled"]=True
    state_path.write_text(json.dumps(state,indent=2),encoding="utf-8")
    (ROOT/"dashboard/cloud-config.js").write_text('window.SOCIAL_CLOUD_URL = '+json.dumps(state["url"])+ ';\n',encoding="utf-8")
    print("LOCAL_SWITCH=ENABLED; DASHBOARD_CLOUD_URL="+state["url"])


def main():
    parser=argparse.ArgumentParser();parser.add_argument("mode",choices=["setup","activate","status","drain"]);args=parser.parse_args()
    if args.mode=="setup":setup()
    elif args.mode=="activate":activate()
    else:
        state=json.loads((BASE/"local-state.json").read_text(encoding="utf-8"))
        if args.mode=="drain":api(state["url"],state["admin_token"],"/admin/drain",{})
        result=requests.get(state["url"]+"/health",timeout=60);result.raise_for_status();print(json.dumps(result.json(),ensure_ascii=True))


if __name__=="__main__":main()
