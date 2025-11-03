import requests
import matplotlib.pyplot as plt
from collections import defaultdict
import os
import time
import json
import csv
import numpy as np

# --- Configuration & Helpers ---

def get_api_key():
    """Fetches the Riot API key from environment variables."""
    api_key = os.environ.get("RIOT_API_KEY")
    if not api_key:
        raise ValueError("Error: RIOT_API_KEY environment variable not set. \n"
                         "Set it in your terminal, e.g.: \n"
                         "export RIOT_API_KEY=\"your-key-here\" (Linux/macOS) \n"
                         "set RIOT_API_KEY=\"your-key-here\" (Windows)")
    return api_key

HEADERS = lambda key: {"X-Riot-Token": key}

# --- Data Dragon (Static Data) Functions ---

def get_latest_ddragon_version():
    """Fetches the latest patch version from Data Dragon."""
    print("Fetching latest Data Dragon version...")
    url = "https://ddragon.leagueoflegends.com/api/versions.json"
    try:
        response = requests.get(url)
        response.raise_for_status()
        version = response.json()[0]  # The first item is the latest version
        print(f"Latest DDragon version is: {version}")
        return version
    except requests.HTTPError as e:
        print(f"Error fetching DDragon versions: {e}")
        raise
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        raise

def fetch_item_data():
    """
    Fetches the latest item.json from Data Dragon and returns a simple
    {itemId: itemName} map.
    """
    try:
        version = get_latest_ddragon_version()
        print(f"Fetching item data for patch {version}...")
        url = f"https://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/item.json"
        
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        
        item_map = {}
        for item_id, item_details in data.get('data', {}).items():
            item_map[item_id] = item_details.get('name', f'Item {item_id}')
        
        print(f"Successfully loaded {len(item_map)} items.")
        return item_map
    except requests.HTTPError as e:
        print(f"Error fetching item.json: {e}")
        print("Warning: Proceeding without item names. Item IDs will be used instead.")
        return {} # Return an empty map on failure
    except Exception as e:
        print(f"An unexpected error occurred fetching item data: {e}")
        return {}


# --- Riot API Fetching Functions ---

def get_puuid_from_riot_id(api_key, region, game_name, tag_line):
    """Gets a PUUID from a gameName#tagLine."""
    headers = {"X-Riot-Token": api_key}
    
    encoded_name = requests.utils.quote(game_name)
    encoded_tag = requests.utils.quote(tag_line)
    url = f"https://{region}.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{encoded_name}/{encoded_tag}"
    print(f"Requesting URL: {url}")
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()
        
        print(f"Game Name: {data.get('gameName', 'N/A')}#{data.get('tagLine', 'N/A')}")
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
    """Gets a list of match IDs for a given PUUID."""
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
    """Gets the data for a single match."""
    url = f"https://{region}.api.riotgames.com/lol/match/v5/matches/{match_id}"
    r = requests.get(url, headers=HEADERS(api_key))
    r.raise_for_status()
    return r.json()

def get_timeline(api_key, region, match_id):
    """Gets the timeline data for a single match."""
    url = f"https://{region}.api.riotgames.com/lol/match/v5/matches/{match_id}/timeline"
    r = requests.get(url, headers=HEADERS(api_key))
    if r.status_code == 404:
        print(f"Warning: No timeline data found for match {match_id}. (404)")
        return None
    r.raise_for_status()
    return r.json()

# --- Data Processing Functions ---

def parse_items_from_match(match_json, timeline_json):
    """
    Parses participant info and item purchase events from match/timeline data.
    
    Returns a list of participant data dictionaries.
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
                # We only care about purchase events for this task
                if ttype in ("ITEM_PURCHASED", "ITEM_SOLD", "ITEM_DESTROYED"):
                    pid = ev.get("participantId")
                    if pid is not None:
                        events_by_pid[pid].append({
                            "type": ttype,
                            "timestamp": ev.get("timestamp"),
                            "itemId": ev.get("itemId") or ev.get("afterId") or ev.get("beforeId"),
                        })

    out_participants = []
    for pid, p in pid_map.items():
        evs = sorted(events_by_pid.get(pid, []), key=lambda e: e.get("timestamp", 0))
        
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
            "purchases": evs, # Store all sorted item events
        })
    return out_participants


def get_gold_per_player(timeline_data):
    """
    Extracts gold-per-minute for each player from timeline data.
    Does NOT plot, just returns the data.
    """
    if not timeline_data or "info" not in timeline_data:
        print("Warning: Cannot get gold data, timeline data is missing or invalid.")
        return [], {}
        
    frames = timeline_data["info"]["frames"]
    timestamps = [frame["timestamp"] / 60000 for frame in frames]  # minutes
    
    # Initialize gold tracking for each player
    player_gold = {str(i): [] for i in range(1, 11)}

    for frame in frames:
        for pid, pframe in frame["participantFrames"].items():
            if pid in player_gold:
                player_gold[pid].append(pframe["totalGold"])

    return timestamps, player_gold

# --- Data Saving and Plotting ---

def save_gold_data(match_data, timestamps, player_gold, folder="gold_data", prefix=""):
    """Saves timestamps and gold-by-champion to a JSON file."""
    os.makedirs(folder, exist_ok=True)

    match_id = match_data["match_meta"]["matchId"]
    # Use the prefix passed from main(), don't recalculate it
    filepath = os.path.join(folder, f"{prefix}{match_id}.json")

    # Build mapping from participantId -> championName
    id_to_champ = {
        p["participantId"]: p["championName"]
        for p in match_data["info"]["participants"]
    }

    # Replace player IDs with champion names
    gold_by_champion = {}
    for pid_str, gold_list in player_gold.items():
        pid_int = int(pid_str)
        champ = id_to_champ.get(pid_int, f"Player{pid_int}")
        gold_by_champion[champ] = gold_list

    data = {
        "matchId": match_id,
        "gameMode": match_data["info"]["gameMode"],
        "timestamps": timestamps,
        "gold": gold_by_champion
    }

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    print(f"✅ Gold data saved to {filepath}")


def plot_individual_champion_graphs(timestamps, player_gold, parsed_data, match_id, item_map, folder="champion_graphs"):
    """
    Plots a separate gold graph for each champion, showing item purchases.
    Saves graphs to PNG files.
    """
    os.makedirs(folder, exist_ok=True)
    
    # Create a quick lookup map for participantId -> champion and purchases
    participant_lookup = {
        p["participantId"]: {
            "championName": p["championName"],
            "purchases": p["purchases"]
        }
        for p in parsed_data
    }

    timestamps_np = np.array(timestamps)

    print(f"Generating {len(participant_lookup)} champion graphs for match {match_id}...")

    # Loop through all 10 participants
    for pid_int, p_data in participant_lookup.items():
        pid_str = str(pid_int)
        if pid_str not in player_gold or not player_gold[pid_str]:
            print(f"  Skipping plot for participant {pid_int} (no gold data).")
            continue
            
        champion_name = p_data["championName"]
        gold_data = player_gold[pid_str]
        purchases = p_data["purchases"]
        
        # Ensure timestamps and gold data are aligned
        if len(timestamps_np) != len(gold_data):
            print(f"  Skipping plot for {champion_name} (data length mismatch).")
            continue
            
        plt.figure(figsize=(12, 7))
        
        # 1. Plot the gold curve
        plt.plot(timestamps_np, gold_data, label=f"{champion_name} Total Gold", color="gold", linewidth=2)
        
        # 2. Plot item purchases
        item_purchase_events = [ev for ev in purchases if ev.get("type") == "ITEM_PURCHASED"]
        
        if item_purchase_events:
            last_annotation_time = -np.inf # Keep track of the last annotation's time
            last_y_offset = 5              # Default starting Y-offset (5 points)
            
            # Plot all purchases as vertical lines
            for i, ev in enumerate(item_purchase_events):
                ts_minutes = ev["timestamp"] / 60000.0
                item_id = str(ev["itemId"]) # Use string for map lookup
                
                # --- THIS IS THE KEY CHANGE ---
                # Look up the item name, fall back to ID if not found
                item_name = item_map.get(item_id, f"Item {item_id}")
                # --- END OF KEY CHANGE ---

                # Add a vertical line
                label = "Item Purchase" if i == 0 else None
                plt.axvline(x=ts_minutes, color='red', linestyle='--', linewidth=0.7, alpha=0.8, label=label)
                
                # Find the gold value at the time of purchase for annotation
                idx = np.searchsorted(timestamps_np, ts_minutes, side='right') - 1
                if idx >= 0 and idx < len(gold_data):
                    gold_at_purchase = gold_data[idx]
                    
                    # --- Annotation Collision Avoidance ---
                    # Check if this purchase is too close to the last one
                    # We define "too close" as within 0.5 minutes (30 seconds)
                    time_difference = ts_minutes - last_annotation_time
                    
                    if time_difference < 0.5:
                        # Too close: Increase the y_offset to stack them
                        current_y_offset = last_y_offset + 12 # Stack 12 points higher
                    else:
                        # Far enough: Reset to default offset
                        current_y_offset = 5 
                    
                    # Annotate with the item NAME
                    plt.annotate(item_name, 
                                 (ts_minutes, gold_at_purchase), 
                                 textcoords="offset points", 
                                 xytext=(0, current_y_offset), # Use the calculated offset
                                 ha='center', 
                                 fontsize=7,
                                 alpha=0.9,
                                 # Add a background for readability
                                 bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="none", alpha=0.6),
                                 # Add an arrow to point back to the line, crucial for stacked annotations
                                 arrowprops=dict(arrowstyle="->",
                                                 connectionstyle="arc3,rad=0.2",
                                                 color="black",
                                                 lw=0.5,
                                                 alpha=0.6)
                                 )
                    
                    # Update last annotation info
                    last_annotation_time = ts_minutes
                    last_y_offset = current_y_offset
                    # --- End of Collision Avoidance ---

        plt.title(f"{champion_name} (Match: {match_id})\nGold Over Time with Item Purchases")
        plt.xlabel("Game Time (Minutes)")
        plt.ylabel("Total Gold")
        plt.legend()
        plt.grid(True, linestyle=':', alpha=0.6)
        plt.tight_layout()
        
        # Save the figure
        safe_champ_name = "".join(c for c in champion_name if c.isalnum()) # Clean name for filename
        filename = os.path.join(folder, f"{match_id}_{pid_int}_{safe_champ_name}.png")
        plt.savefig(filename)
        plt.close() # IMPORTANT: Close the plot to free memory

    print(f"✅ All champion graphs saved to '{folder}' directory.")


# --- Main Execution ---

def main():
    # --- Configuration ---
    try:
        api_key = "RGAPI-4836d26e-cbaf-40a7-836d-b35313ed9348"
        # Fetch item map ONCE at the start
        item_map = fetch_item_data()
    except (ValueError, requests.HTTPError) as e:
        print(e)
        return

    region = "europe"       # e.g., "americas", "europe", "asia"
    game_name = "POOP FACTORY"
    tag_line = "POOF"
    number_of_games = 1     # How many recent games to fetch
    sleep_timer = 1         # 1s delay between API calls to respect rate limits
    queue_type = None       # e.g., 420 for "Ranked Solo/Duo", 440 for "Ranked Flex"
    # ---------------------

    # Create directories
    os.makedirs("matches", exist_ok=True)
    os.makedirs("matches_purchases", exist_ok=True)
    os.makedirs("gold_data", exist_ok=True)
    os.makedirs("champion_graphs", exist_ok=True)
    
    puuid = get_puuid_from_riot_id(api_key, region, game_name, tag_line)
    if not puuid:
        print("Could not retrieve PUUID. Exiting.")
        return

    print(f"Fetching {number_of_games} match(es) for PUUID: {puuid}")
    try:
        match_ids = get_match_ids_by_puuid(api_key, region, puuid, start=0, count=number_of_games, queue=queue_type)
    except requests.HTTPError as e:
        print(f"Error fetching match list: {e}")
        return
        
    print(f"Found {len(match_ids)} match IDs: {match_ids}")

    for mid in match_ids:
        print(f"\n--- Processing Match: {mid} ---")
        
        try:
            match_data = get_match(api_key, region, mid)
            print(f"Successfully fetched match data for {mid}")

            # Fetch timeline ONCE
            timeline_data = get_timeline(api_key, region, mid)
            if not timeline_data:
                print(f"Skipping match {mid} as it has no timeline data.")
                continue
            
            print(f"Successfully fetched timeline data for {mid}")

            # Process data
            parsed_data = parse_items_from_match(match_data, timeline_data)
            timestamps, player_gold = get_gold_per_player(timeline_data)

            game_mode = match_data["info"]["gameMode"]
            prefix = game_mode[:3].upper() + "_"
            
            # --- Save Data Files ---
            
            # 1. Save individual champion graphs
            # Pass the item_map to the plotting function
            plot_individual_champion_graphs(
                timestamps, player_gold, parsed_data, mid, item_map, folder="champion_graphs"
            )

            # 2. Save raw match data (for archival)
            match_result_for_json = {
                "matchId": mid, 
                "parsed": parsed_data, 
                "match_meta": match_data.get("metadata", {}), 
                "info": match_data.get("info", {})
            }
            out_json = os.path.join("matches", f"{prefix}{mid}.json")
            with open(out_json, "w", encoding="utf-8") as f:
                json.dump(match_result_for_json, f, indent=2)
            print(f"✅ Raw match data saved to {out_json}")

            # 3. Save gold-per-minute data
            save_gold_data(match_result_for_json, timestamps, player_gold, prefix=prefix)

            # 4. Save flat CSV of all purchases
            csv_out = os.path.join("matches_purchases", f"{prefix}{mid}.csv")
            with open(csv_out, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["matchId", "puuid", "summonerName", "championName", "participantId", "timestamp_ms", "event_type", "itemId"])
                for p in parsed_data:
                    for ev in p["purchases"]:
                        writer.writerow([mid, p["puuid"], p["summonerName"], p["championName"], p["participantId"], ev.get("timestamp"), ev.get("type"), ev.get("itemId")])
            print(f"✅ Purchase CSV saved to {csv_out}")

        except requests.HTTPError as e:
            print(f"Error processing match {mid}: {e}")
            if e.response.status_code == 429:
                print("Rate limit exceeded. Waiting 60 seconds...")
                time.sleep(60)
        except Exception as e:
            print(f"An unexpected error occurred for match {mid}: {e}")

        # small sleep to respect rate limits
        print(f"Sleeping for {sleep_timer} second(s)...")
        time.sleep(sleep_timer)

    print("\n--- All matches processed. ---")

if __name__ == "__main__":
    main()

