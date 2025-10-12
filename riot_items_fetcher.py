#!/usr/bin/env python3
"""
riot_items_fetcher.py
Fetch matches + timelines from Riot Match-v5 and extract item purchase histories.

Usage:
  # using summoner name & platform (platform examples: na1, euw1, kr, jp1, oc1, br1, la1, la2, tr1, ru, eun1)
  export RIOT_API_KEY="YOUR_KEY"
  python riot_items_fetcher.py --platform euw1 --summoner Faker --count 10

  # or using puuid directly
  python riot_items_fetcher.py --platform euw1 --puuid <PUUID> --count 20

Notes:
- Put API key in env var RIOT_API_KEY or pass --api-key (not recommended to paste keys on shared systems).
- The script obeys simple rate-limit sleep; for bulk crawling you should implement a token-bucket limiter.
"""
import os, time, argparse, requests, json
from collections import defaultdict
# Mon puuid = iRn-CQgKkBDr-dvtXjINoKCH8KwEZNw-7nI3UM1bYvWYZ9h0FETDXtrmN2sHY74_a0spTPkuG76Mkw

# === adjust / extend as you like ===
PLATFORM_TO_REGION = {
    "na1": "americas", "br1": "americas", "la1": "americas", "la2": "americas",
    "oc1": "sea",  # OCE uses 'sea' routing value in many docs
    "jp1": "asia", "kr": "asia", "kr1": "asia",
    "eun1": "europe", "euw1": "europe", "ru": "europe", "tr1": "europe",
    # add others if needed
}

HEADERS = lambda key: {"X-Riot-Token": key}

def get_summoner_by_name(api_key, platform, summoner_name):
    print(api_key)
    url = f"https://{platform}.api.riotgames.com/lol/summoner/v4/summoners/by-name/{requests.utils.quote(summoner_name)}"
    r = requests.get(url, headers=HEADERS(api_key))
    r.raise_for_status()
    return r.json()

def get_match_ids_by_puuid(api_key, region, puuid, start=0, count=20, queue=None, match_type=None, start_time=None, end_time=None):
    url = f"https://{region}.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids"
    params = {"start": start, "count": count}
    if queue is not None: params["queue"] = queue
    if match_type is not None: params["type"] = match_type
    if start_time is not None: params["startTime"] = start_time
    if end_time is not None: params["endTime"] = end_time
    r = requests.get(url, headers=HEADERS(api_key), params=params)
    r.raise_for_status()
    return r.json()

def get_match(api_key, region, match_id):
    url = f"https://{region}.api.riotgames.com/lol/match/v5/matches/{match_id}"
    r = requests.get(url, headers=HEADERS(api_key))
    r.raise_for_status()
    return r.json()

def get_timeline(api_key, region, match_id):
    url = f"https://{region}.api.riotgames.com/lol/match/v5/matches/{match_id}/timeline"
    r = requests.get(url, headers=HEADERS(api_key))
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()

def parse_items_from_match(match_json, timeline_json):
    """
    Returns a dict with:
      'participants': [ {puuid, summonerName, championName, participantId, teamId, final_items, goldEarned, goldSpent, purchases:[{timestamp, type, itemId}] } ]
    """
    info = match_json["info"]
    participants = info["participants"]
    # Build map participantId -> participant
    pid_map = {}
    for idx, p in enumerate(participants):
        pid = p.get("participantId", idx + 1)
        pid_map[pid] = p

    # collect events from timeline (if present)
    events_by_pid = defaultdict(list)
    if timeline_json and "info" in timeline_json and "frames" in timeline_json["info"]:
        for frame in timeline_json["info"]["frames"]:
            for ev in frame.get("events", []):
                ttype = ev.get("type", "")
                if ttype in ("ITEM_PURCHASED", "ITEM_SOLD", "ITEM_DESTROYED", "ITEM_UNDO"):
                    pid = ev.get("participantId")
                    if pid is not None:
                        events_by_pid[pid].append({
                            "type": ttype,
                            "timestamp": ev.get("timestamp"),
                            "itemId": ev.get("itemId") or ev.get("afterId") or ev.get("beforeId"),
                            **{k: ev.get(k) for k in ("goldGain","goldSpent","level")}
                        })

    out_participants = []
    for pid, p in pid_map.items():
        evs = sorted(events_by_pid.get(pid, []), key=lambda e: e.get("timestamp", 0))
        # simple inventory reconstruction
        inventory = []
        purchases = []
        for ev in evs:
            etype = ev["type"]
            iid = ev.get("itemId")
            ts = ev.get("timestamp")
            if etype == "ITEM_PURCHASED" and iid:
                inventory.append(iid)
            elif etype in ("ITEM_SOLD", "ITEM_DESTROYED") and iid:
                if iid in inventory: inventory.remove(iid)
            purchases.append({"timestamp": ts, "type": etype, "itemId": iid})
        final_items = [p.get(f"item{i}", 0) for i in range(7)]
        out_participants.append({
            "participantId": pid,
            "puuid": p.get("puuid"),
            "summonerName": p.get("summonerName"),
            "championName": p.get("championName"),
            "teamId": p.get("teamId"),
            "final_items": final_items,
            "goldEarned": p.get("goldEarned"),
            "goldSpent": p.get("goldSpent"),
            "purchases": purchases,
        })
    return out_participants

def main(args):
    # api_key = args.api_key or os.environ.get("RIOT_API_KEY")
    api_key = "RGAPI-5bff0b95-9db1-42b8-8dec-fd2105261042"
    if not api_key:
        raise RuntimeError("Set RIOT_API_KEY env var or pass --api-key")

    platform = args.platform
    if platform not in PLATFORM_TO_REGION:
        raise RuntimeError(f"Unknown platform '{platform}'. Add it to PLATFORM_TO_REGION mapping.")
    region = PLATFORM_TO_REGION[platform]

    # get puuid
    if args.puuid:
        puuid = args.puuid
    else:
        summ = get_summoner_by_name(api_key, platform, args.summoner)
        puuid = summ["puuid"]

    match_ids = get_match_ids_by_puuid(api_key, region, puuid, start=args.start, count=args.count, queue=args.queue)
    results = []
    for mid in match_ids:
        try:
            match = get_match(api_key, region, mid)
        except requests.HTTPError as e:
            print("Failed to fetch match", mid, e)
            continue

        timeline = None
        try:
            timeline = get_timeline(api_key, region, mid)
        except requests.HTTPError:
            # timeline might be missing/older than retention
            timeline = None

        parsed = parse_items_from_match(match, timeline)
        results.append({"matchId": mid, "parsed": parsed, "match_meta": match.get("metadata", {}), "info": match.get("info", {})})

        # small sleep to respect rate limits — tune as needed
        time.sleep(args.sleep)

    # save
    out_json = args.output_json or "matches_items.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    # optionally write a flat CSV with purchases
    import csv
    csv_out = args.output_csv or "matches_item_purchases.csv"
    with open(csv_out, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["matchId","puuid","summonerName","championName","participantId","timestamp_ms","event_type","itemId"])
        for res in results:
            mid = res["matchId"]
            for p in res["parsed"]:
                for ev in p["purchases"]:
                    writer.writerow([mid, p["puuid"], p["summonerName"], p["championName"], p["participantId"], ev.get("timestamp"), ev.get("type"), ev.get("itemId")])
    print(f"Wrote JSON to {out_json} and CSV to {csv_out}")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--platform", required=True, help="Platform (e.g. euw1, na1, kr, oc1, br1, la1, la2, tr1, ru, eun1)")
    ap.add_argument("--summoner", help="Summoner name (if not using --puuid)")
    ap.add_argument("--puuid", help="PUUID (skip summoner lookup)")
    ap.add_argument("--count", type=int, default=20)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--queue", type=int, default=None)
    ap.add_argument("--sleep", type=float, default=0.5, help="seconds between match requests (tune for rate-limits)")
    ap.add_argument("--api-key", default=None, help="Riot API key (prefer env var RIOT_API_KEY)")
    ap.add_argument("--output-json", default="matches_items.json")
    ap.add_argument("--output-csv", default="matches_item_purchases.csv")
    args = ap.parse_args()
    main(args)
