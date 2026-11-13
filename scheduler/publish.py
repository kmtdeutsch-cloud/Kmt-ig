#!/usr/bin/env python3
"""Publish due posts from scheduler/queue.json to Instagram (Graph API).

Env: IG_USER_ID, IG_TOKEN. Optional: IG_API_BASE (default graph.instagram.com/v21.0).
Usage: publish.py [--dry-run]
queue.json item: {id, type: IMAGE|CAROUSEL|REELS, publish_at (UTC ISO, e.g. 2026-11-16T09:30:00Z),
                  media_urls: [...], caption, status: pending|published|failed, media_id?, error?}
"""
import json, os, sys, time, datetime as dt, urllib.request, urllib.parse, urllib.error

BASE = os.environ.get("IG_API_BASE", "https://graph.instagram.com/v21.0")
UID, TOKEN = os.environ.get("IG_USER_ID"), os.environ.get("IG_TOKEN")
QUEUE = os.path.join(os.path.dirname(__file__), "queue.json")
DRY = "--dry-run" in sys.argv
MAX_PER_RUN = 3          # stay far below Instagram's ~50 posts/24h limit

def api(path, params=None, method="POST"):
    p = dict(params or {}); p["access_token"] = TOKEN
    data = urllib.parse.urlencode(p).encode()
    url = f"{BASE}/{path}"
    req = urllib.request.Request(url + ("" if method == "POST" else "?" + data.decode()),
                                 data=data if method == "POST" else None, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{e.code} {e.read().decode()[:400]}")

def wait_ready(cid):
    for _ in range(40):                      # up to ~6 min (reels need processing)
        s = api(cid, {"fields": "status_code"}, "GET").get("status_code")
        if s == "FINISHED": return
        if s in ("ERROR", "EXPIRED"): raise RuntimeError(f"container {s}")
        time.sleep(9)
    raise RuntimeError("container timeout")

def publish(item):
    t, urls, cap = item["type"], item["media_urls"], item.get("caption", "")
    if t == "IMAGE":
        c = api(f"{UID}/media", {"image_url": urls[0], "caption": cap})["id"]
    elif t == "REELS":
        c = api(f"{UID}/media", {"media_type": "REELS", "video_url": urls[0], "caption": cap, "share_to_feed": "true"})["id"]
    elif t == "CAROUSEL":
        kids = []
        for u in urls:
            k = api(f"{UID}/media", {"image_url": u, "is_carousel_item": "true"})["id"]
            kids.append(k)
        c = api(f"{UID}/media", {"media_type": "CAROUSEL", "children": ",".join(kids), "caption": cap})["id"]
    else:
        raise RuntimeError(f"unknown type {t}")
    wait_ready(c)
    return api(f"{UID}/media_publish", {"creation_id": c})["id"]

def main():
    q = json.load(open(QUEUE, encoding="utf-8"))
    now = dt.datetime.now(dt.timezone.utc)
    due = [i for i in q if i.get("status") == "pending"
           and dt.datetime.fromisoformat(i["publish_at"].replace("Z", "+00:00")) <= now]
    due.sort(key=lambda i: i["publish_at"])
    print(f"{len(due)} due, now={now:%Y-%m-%d %H:%M}Z, dry_run={DRY}")
    for item in due[:MAX_PER_RUN]:
        print("->", item["id"], item["type"])
        if DRY: continue
        try:
            item["media_id"] = publish(item); item["status"] = "published"
            item["published_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        except Exception as e:
            item["status"] = "failed"; item["error"] = str(e)
            print("FAILED", item["id"], e)
        json.dump(q, open(QUEUE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    if not DRY:
        json.dump(q, open(QUEUE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

if __name__ == "__main__":
    if not DRY and not (UID and TOKEN): sys.exit("IG_USER_ID / IG_TOKEN missing")
    main()
