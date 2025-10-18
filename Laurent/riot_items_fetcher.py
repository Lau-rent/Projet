import os, time, argparse, requests, json, csv
from collections import defaultdict

HEADERS = lambda key: {"X-Riot-Token": key}

def get_puuid_from_riot_id(api_key, region, game_name, tag_line):

    headers = {"X-Riot-Token": api_key}
    
    encoded_name = requests.utils.quote(game_name)
    encoded_tag = requests.utils.quote(tag_line)
    url = f"https://{region}.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{encoded_name}/{encoded_tag}"
    print(f"Requesting URL: {url}")
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()
        
        print(f"Game Name: {data['gameName']}#{data['tagLine']}")
        print(f"PUUID: {data['puuid']}")
        return data['puuid']
    
    except requests.exceptions.HTTPError as e:
        if response.status_code == 404:
            print(f"Error: Riot ID '{game_name}#{tag_line}' not found in {region}")
        elif response.status_code == 403:
            print("Error: Invalid or expired API key")
        else:
            print(f"HTTP error: {e}")
        return None
    except Exception as e:
        print(f"Error: {e}")
        return None

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
    print(r)
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


import requests
import matplotlib.pyplot as plt

def get_gold_graph(api_key, region, match_id):
    headers = {"X-Riot-Token": api_key}
    url = f"https://{region}.api.riotgames.com/lol/match/v5/matches/{match_id}/timeline"
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    data = response.json()
    
    frames = data["info"]["frames"]
    gold_blue = []
    gold_red = []
    timestamps = []

    for frame in frames:
        total_blue = 0
        total_red = 0

        for pid, pframe in frame["participantFrames"].items():
            pid = int(pid)
            gold = pframe["totalGold"]

            # Players 1–5 are blue team, 6–10 are red team
            if pid <= 5:
                total_blue += gold
            else:
                total_red += gold

        timestamps.append(frame["timestamp"] / 60000)  # convert ms → minutes
        gold_blue.append(total_blue)
        gold_red.append(total_red)

    # 🧮 Plot
    plt.figure(figsize=(10, 6))
    plt.plot(timestamps, gold_blue, label="Blue Team", linewidth=2)
    plt.plot(timestamps, gold_red, label="Red Team", linewidth=2)
    plt.title("Gold Difference Over Time")
    plt.xlabel("Minutes")
    plt.ylabel("Total Team Gold")
    plt.legend()
    plt.grid(True)
    plt.show()

    return timestamps, gold_blue, gold_red

import json
import os

def save_gold_data(match_id, timestamps, player_gold, folder="gold_data"):
    os.makedirs(folder, exist_ok=True)
    filepath = os.path.join(folder, f"{match_id}.json")

    data = {
        "matchId": match_id,
        "timestamps": timestamps,
        "gold": player_gold
    }

    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)
    print(f"✅ Gold data saved to {filepath}")


def load_gold_data(match_id, folder="gold_data"):
    filepath = os.path.join(folder, f"{match_id}.json")
    with open(filepath, "r") as f:
        data = json.load(f)
    return data

def get_gold_per_player(api_key, region, match_id):
    """
    Fetch and plot gold evolution per player from Riot Match Timeline API
    """
    headers = {"X-Riot-Token": api_key}
    url = f"https://{region}.api.riotgames.com/lol/match/v5/matches/{match_id}/timeline"
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    data = response.json()
    
    frames = data["info"]["frames"]
    timestamps = [frame["timestamp"] / 60000 for frame in frames]  # minutes
    
    # Initialize gold tracking for each player
    player_gold = {str(i): [] for i in range(1, 11)}

    for frame in frames:
        for pid, pframe in frame["participantFrames"].items():
            player_gold[pid].append(pframe["totalGold"])

    # 🎨 Plot each player's gold curve
    plt.figure(figsize=(12, 7))
    for pid, gold_list in player_gold.items():
        team_color = "blue" if int(pid) <= 5 else "red"
        plt.plot(timestamps, gold_list, color=team_color, alpha=0.7, label=f"Player {pid}")

    plt.title("Gold per Player Over Time")
    plt.xlabel("Minutes")
    plt.ylabel("Total Gold")
    plt.grid(True)
    plt.legend(ncol=2)
    plt.show()

    return timestamps, player_gold



def main():
    os.makedirs("matches", exist_ok=True)
    os.makedirs("matches_purchases", exist_ok=True)
    api_key = "RGAPI-6bb3f659-7a2b-459b-8d53-3ed8e4d4cd0a"


    region = "europe"
    game_name = "gogopotato"
    tag_line = "777"
    number_of_games = 1
    sleep_timer = 1
    queue_type = None
    
    puuid = get_puuid_from_riot_id(api_key, region, game_name, tag_line)

    match_ids = get_match_ids_by_puuid(api_key, region, puuid, start=0, count=number_of_games, queue=queue_type)
    print(match_ids)
    get_gold_graph(api_key, region, match_ids[0])
    get_gold_per_player(api_key, region, match_ids[0])
    results = []
    for mid in match_ids:
        try:
            match = get_match(api_key, region, mid)
        except requests.HTTPError as e:
            print("Failed to fetch match", mid, e)
            continue

        timeline = None
        try:
            print("Fetching timeline for match", mid)
            timeline = get_timeline(api_key, region, mid)
        except requests.HTTPError:
            # timeline might be missing/older than retention
            timeline = None

        parsed = parse_items_from_match(match, timeline)
        results.append({"matchId": mid, "parsed": parsed, "match_meta": match.get("metadata", {}), "info": match.get("info", {})})

        # small sleep to respect rate limits — tune as needed
        time.sleep(sleep_timer)

        # save
        out_json = "matches/" + mid + ".json"
        with open(out_json, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)

        save_gold_data(mid, *get_gold_per_player(api_key, region, mid))
        # optionally write a flat CSV with purchases

        csv_out = "matches_purchases/" + mid + ".csv"
        with open(csv_out, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["matchId","puuid","summonerName","championName","participantId","timestamp_ms","event_type","itemId"])
            for res in results:
                mid = res["matchId"]
                for p in res["parsed"]:
                    for ev in p["purchases"]:
                        writer.writerow([mid, p["puuid"], p["summonerName"], p["championName"], p["participantId"], ev.get("timestamp"), ev.get("type"), ev.get("itemId")])
        print(f"Wrote JSON to {out_json} and CSV to {csv_out}")
        results = []

if __name__ == "__main__":
    main()
