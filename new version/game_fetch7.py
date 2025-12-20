import requests
import matplotlib.pyplot as plt
from collections import defaultdict
import os
import time
import json
import numpy as np
import random 
import datetime # <--- AJOUT POUR LA DATE

# --- Configuration & Helpers ---

PLATFORM_TO_REGIONAL = {
    "euw1": "europe", "eun1": "europe", "tr1": "europe", "ru": "europe",
    "na1": "americas", "br1": "americas", "la1": "americas", "la2": "americas",
    "oc1": "sea", "ph2": "sea", "sg2": "sea", "th2": "sea", "tw2": "sea", "vn2": "sea",
    "jp1": "asia", "kr": "asia",
}

def get_api_key():
    api_key = os.environ.get("RIOT_API_KEY") 
    if not api_key:
        return "RGAPI-da23eb7d-0d1c-44e8-8aa2-1ad002794508" 
    return api_key

HEADERS = lambda key: {"X-Riot-Token": key}

# --- Data Dragon ---

def get_latest_ddragon_version():
    print("Fetching latest Data Dragon version...")
    try:
        url = "https://ddragon.leagueoflegends.com/api/versions.json"
        response = requests.get(url)
        response.raise_for_status()
        return response.json()[0]
    except Exception:
        return "14.23.1"

def fetch_item_data(version):
    try:
        url = f"https://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/item.json"
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        item_map = {}
        for item_id, item_details in data.get('data', {}).items():
            item_map[item_id] = item_details.get('name', f'Item {item_id}')
        return item_map
    except Exception:
        return {}

# --- Riot API Fetching ---

def get_puuid_by_tier(api_key, platform_region, queue, tier, division, page=1):
    print(f"Fetching players from: {platform_region} - {queue} - {tier} {division} (Page {page})")
    url = f"https://{platform_region}.api.riotgames.com/lol/league/v4/entries/{queue}/{tier}/{division}"
    params = {"page": page}
    try:
        r = requests.get(url, headers=HEADERS(api_key), params=params)
        r.raise_for_status()
        entries = r.json()
        return [entry.get('puuid', entry.get('summonerId')) for entry in entries]
    except Exception as e:
        print(f"Error fetching league entries: {e}")
        return []

def get_puuid_from_summoner_id(api_key, platform_region, summoner_id):
    url = f"https://{platform_region}.api.riotgames.com/lol/summoner/v4/summoners/{summoner_id}"
    try:
        r = requests.get(url, headers=HEADERS(api_key))
        r.raise_for_status()
        return r.json()['puuid']
    except Exception:
        return None

def get_match_ids_by_puuid(api_key, region, puuid, start=0, count=20, queue=None):
    # Récupère les matchs les plus récents par défaut
    url = f"https://{region}.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids"
    params = {"start": start, "count": count}
    if queue is not None: params["queue"] = queue
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
    if r.status_code == 404: return None
    r.raise_for_status()
    return r.json()

# --- Parsing ---

def parse_items_from_match(match_json, timeline_json):
    info = match_json["info"]
    participants = info["participants"]
    
    pid_map = {p["participantId"]: p for p in participants}

    events_by_pid = defaultdict(list)
    if timeline_json and "info" in timeline_json and "frames" in timeline_json["info"]:
        for frame in timeline_json["info"]["frames"]:
            for ev in frame.get("events", []):
                ttype = ev.get("type", "")
                if ttype in ("ITEM_PURCHASED", "ITEM_SOLD", "ITEM_DESTROYED"):
                    pid = ev.get("participantId")
                    if pid:
                        events_by_pid[pid].append({
                            "type": ttype,
                            "timestamp": ev.get("timestamp"),
                            "itemId": ev.get("itemId") or ev.get("afterId") or ev.get("beforeId"),
                        })

    out_participants = []
    for pid, p in pid_map.items():
        evs = sorted(events_by_pid.get(pid, []), key=lambda e: e.get("timestamp", 0))
        final_items = [p.get(f"item{i}", 0) for i in range(7)]
        
        # Correction Lane/Role via teamPosition
        real_position = p.get("teamPosition")
        if not real_position or real_position == "Invalid":
            real_position = p.get("lane")

        out_participants.append({
            "participantId": pid,
            "puuid": p.get("puuid"),
            "summonerName": f"Player {pid}", 
            "championName": p.get("championName"),
            "teamId": p.get("teamId"),
            "win": p.get("win"),
            "lane": real_position,
            "role": p.get("role"),
            "final_items": final_items,
            "purchases": evs,
        })
    return out_participants

def get_gold_per_player(timeline_data):
    if not timeline_data or "info" not in timeline_data:
        return [], {}
    frames = timeline_data["info"]["frames"]
    timestamps = [frame["timestamp"] / 60000 for frame in frames]
    player_gold = {str(i): [] for i in range(1, 11)}
    for frame in frames:
        for pid, pframe in frame["participantFrames"].items():
            if pid in player_gold:
                player_gold[pid].append(pframe["totalGold"])
    return timestamps, player_gold

# --- Sauvegarde ---

def save_consolidated_match(match_data, parsed_participants, timestamps, player_gold, rank_info, folder="parsed_matches", prefix=""):
    os.makedirs(folder, exist_ok=True)
    match_id = match_data["match_meta"]["matchId"]
    filepath = os.path.join(folder, f"{prefix}{match_id}.json")
    
    # --- CALCUL DE LA DATE LISIBLE ---
    creation_ms = match_data["info"].get("gameCreation", 0)
    # On divise par 1000 car gameCreation est en millisecondes
    game_date_str = datetime.datetime.fromtimestamp(creation_ms / 1000).strftime('%Y-%m-%d %H:%M:%S')

    consolidated_participants = []
    
    for p in parsed_participants:
        pid = p["participantId"]
        pid_str = str(pid)
        gold_curve = player_gold.get(pid_str, [])
        
        participant_obj = {
            "participantId": pid,
            "championName": p["championName"],
            "teamId": p["teamId"],
            "win": p["win"],
            "lane": p["lane"],
            "gold_curve": gold_curve,
            "item_purchases": p["purchases"],
            "final_items": p["final_items"]
        }
        consolidated_participants.append(participant_obj)

    full_json = {
        "matchId": match_id,
        "gameDate": game_date_str, # <--- AJOUT : Date lisible
        "rank": rank_info,
        "gameMode": match_data["info"].get("gameMode"),
        "gameDuration": match_data["info"].get("gameDuration"),
        "timestamps_minutes": timestamps,
        "participants": consolidated_participants
    }

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(full_json, f, indent=2)
    
    print(f"    ✅ Données ({game_date_str}) sauvegardées dans {filepath}")

# --- Main ---

def main():
    api_key = get_api_key()
    
    try:
        version = get_latest_ddragon_version()
        fetch_item_data(version)
    except Exception:
        pass

    # --- CONFIG ---
    PLATFORM_REGION = "euw1" 
    MATCH_REGION = PLATFORM_TO_REGIONAL.get(PLATFORM_REGION, "europe") 
    TARGET_QUEUE = "RANKED_SOLO_5x5"
    TARGET_TIER = "PLATINUM"
    TARGET_DIVISION = "IV"
    
    PLAYERS_TO_PROCESS = 1000
    MATCHES_PER_PLAYER = 3
    SLEEP_TIMER = 1
    
    OUTPUT_FOLDER = "parsed_matches"
    
    # Fetch Players
    print(f"--- Recherche joueurs: {TARGET_TIER} {TARGET_DIVISION} ({PLATFORM_REGION}) ---")
    rank_str = f"{TARGET_TIER} {TARGET_DIVISION}"
    
    player_ids = get_puuid_by_tier(api_key, PLATFORM_REGION, TARGET_QUEUE, TARGET_TIER, TARGET_DIVISION)
    
    if not player_ids:
        print("Aucun joueur trouvé.")
        return
        
    random.shuffle(player_ids)
    targets = player_ids[:PLAYERS_TO_PROCESS]
    
    processed_matches = set() 

    for p_id in targets:
        puuid = p_id
        if len(str(p_id)) < 70: 
            puuid = get_puuid_from_summoner_id(api_key, PLATFORM_REGION, p_id)
            if not puuid: 
                time.sleep(SLEEP_TIMER)
                continue
        
        print(f"\n--- Player PUUID: {puuid} ---")
        try:
            match_ids = get_match_ids_by_puuid(api_key, MATCH_REGION, puuid, count=MATCHES_PER_PLAYER, queue=420)
            time.sleep(SLEEP_TIMER)
        except Exception:
            continue

        for mid in match_ids:
            if mid in processed_matches: continue
            
            print(f"  > Traitement du match: {mid}")
            try:
                match_data = get_match(api_key, MATCH_REGION, mid)
                time.sleep(SLEEP_TIMER)
                timeline_data = get_timeline(api_key, MATCH_REGION, mid)
                time.sleep(SLEEP_TIMER)
                
                if not timeline_data or "info" not in match_data: continue

                parsed_data = parse_items_from_match(match_data, timeline_data)
                timestamps, player_gold = get_gold_per_player(timeline_data)
                
                game_mode = match_data["info"].get("gameMode", "UNK")
                prefix = game_mode[:3].upper() + "_"
                
                save_data_input = {"match_meta": match_data["metadata"], "info": match_data["info"]}
                
                save_consolidated_match(
                    save_data_input, 
                    parsed_data, 
                    timestamps, 
                    player_gold, 
                    rank_info=rank_str, 
                    folder=OUTPUT_FOLDER, 
                    prefix=prefix
                )
                
                processed_matches.add(mid)

            except Exception as e:
                print(f"    Erreur: {e}")
                time.sleep(5) 

    print("\n--- Terminé ---")

if __name__ == "__main__":
    main()