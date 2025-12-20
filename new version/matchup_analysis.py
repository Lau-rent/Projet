import json
import os
import glob
import requests
import csv
import numpy as np
import pandas as pd
from collections import defaultdict

# --- Configuration ---
INPUT_FOLDER = "parsed_matches"
OUTPUT_ROOT = "matchup_analysis"

# --- Data Dragon ---
def get_item_data():
    """
    Récupère les items et leurs propriétés (Nom, Prix, Tags, 'Into')
    """
    print("Récupération des données items via DataDragon...")
    try:
        v_url = "https://ddragon.leagueoflegends.com/api/versions.json"
        version = requests.get(v_url).json()[0]
        i_url = f"https://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/item.json"
        data = requests.get(i_url).json()
        return data['data']
    except Exception as e:
        print(f"Erreur DDragon: {e}")
        return {}

def is_final_item(item_id, item_data_map):
    """
    Détermine si un item est un 'Item Final' digne d'analyse.
    """
    if item_id not in item_data_map:
        return False 

    info = item_data_map[item_id]
    
    # 1. Si l'item se transforme en autre chose, c'est un composant (ex: Bottes de vitesse -> Coques)
    if info.get('into'): 
        return False

    # 2. EXCEPTION BOTTES : Si c'est une botte finale (ex: Plated Steelcaps), on garde !
    # Les bottes T2 coutent ~1100g, donc elles passeraient à la trappe sinon.
    if "Boots" in info.get('tags', []):
        return True
        
    # 3. Sinon, filtre de prix pour les autres items (élimine Doran, composants chers, etc.)
    if info['gold']['total'] < 1600:
        return False
        
    return True

# --- Calculs ---

def calculate_gold_acceleration(purchase_timestamp_ms, gold_curve, timestamps_minutes):
    """Calcule le % d'augmentation du GPM dans les 5 minutes suivant l'achat."""
    purchase_min = purchase_timestamp_ms / 60000.0
    
    if purchase_min < 2: return None
    
    idx_buy = int(round(purchase_min))
    idx_future = idx_buy + 5
    
    if idx_buy >= len(gold_curve) or idx_future >= len(gold_curve):
        return None

    gold_at_buy = gold_curve[idx_buy]
    gold_at_future = gold_curve[idx_future]

    pre_gpm = gold_at_buy / (purchase_min if purchase_min > 0 else 1)
    gold_diff = gold_at_future - gold_at_buy
    post_gpm = gold_diff / 5.0

    if pre_gpm == 0: return 0
    
    acceleration = ((post_gpm - pre_gpm) / pre_gpm) * 100
    return acceleration

# --- Main ---

def main():
    # On récupère les données complètes (tags, prix, into...)
    full_item_data = get_item_data()
    
    os.makedirs(OUTPUT_ROOT, exist_ok=True)
    json_files = glob.glob(os.path.join(INPUT_FOLDER, "*.json"))
    
    if not json_files:
        print("Aucun fichier JSON trouvé.")
        return

    # Structure : stats[MyChamp][EnemyChamp][(ItemID, LastItemID)] = ...
    # Each stats entry includes wins, count, accels, golds (gold at purchase) and role_counts
    data_store = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: {
        'wins': 0,
        'count': 0,
        'accels': [],
        'golds': [],
        'role_counts': {}
    })))

    print(f"Analyse de {len(json_files)} parties (Bottes finales incluses)...")

    for filepath in json_files:
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                match = json.load(f)
            
            timestamps = match['timestamps_minutes']
            participants = match['participants']
            
            for p in participants:
                my_champ = p['championName']
                my_team = p['teamId']
                my_lane = p['lane']
                
                if my_lane not in ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"]: continue

                # Trouver l'adversaire direct
                opponent = None
                for opp in participants:
                    if opp['teamId'] != my_team and opp['lane'] == my_lane:
                        opponent = opp
                        break
                
                if not opponent: continue 

                enemy_champ = opponent['championName']
                processed_items = set()
                last_final_item = None  # item précendant (None si premier acheter)

                for purchase in p['item_purchases']:
                    item_id = str(purchase['itemId'])

                    # --- FILTRE AVEC EXCEPTION BOTTES ---
                    if not is_final_item(item_id, full_item_data):
                        continue
                    # ------------------------------------

                    # Use tuple key (current_item, last_item, role) to build a sequential dataset
                    role = p.get('lane')
                    key = (item_id, last_final_item, role)
                    if key in processed_items:
                        # still update last_final_item and skip double counting
                        last_final_item = item_id
                        continue

                    accel = calculate_gold_acceleration(purchase['timestamp'], p['gold_curve'], timestamps)

                    entry = data_store[my_champ][enemy_champ][key]
                    entry['count'] += 1
                    if p.get('win'):
                        entry['wins'] += 1

                    if accel is not None:
                        entry['accels'].append(accel)

                    # Track role: use the lane from parsed_matches as the role
                    role = p.get('lane')
                    if role:
                        rc = entry['role_counts']
                        rc[role] = rc.get(role, 0) + 1

                    # Record gold at purchase (if available)
                    purchase_min = purchase['timestamp'] / 60000.0
                    idx_buy = int(round(purchase_min))
                    gold_at_buy = None
                    try:
                        if isinstance(p.get('gold_curve'), list) and idx_buy < len(p.get('gold_curve')):
                            gold_at_buy = p['gold_curve'][idx_buy]
                    except Exception:
                        gold_at_buy = None

                    if gold_at_buy is not None:
                        entry['golds'].append(gold_at_buy)

                    processed_items.add(key)

                    # update last_final_item since this was a final item
                    last_final_item = item_id

        except Exception as e:
            pass

    # --- Écriture CSV ---
    print("Génération des fichiers CSV...")

    for my_champ, enemies_data in data_store.items():
        champ_dir = os.path.join(OUTPUT_ROOT, my_champ)
        os.makedirs(champ_dir, exist_ok=True)
        csv_path = os.path.join(champ_dir, "items_vs_champions.csv")
        
        rows = []
        for enemy_champ, items in enemies_data.items():
            for item_key, stats in items.items():
                # item_key is (item_id, last_item_id, role)
                item_id, last_item_id, role = item_key
                count = stats['count']
                if count == 0: continue

                winrate = (stats['wins'] / count) * 100
                avg_accel = np.mean(stats['accels']) if stats['accels'] else 0

                # Nom de l'item
                item_name = full_item_data.get(item_id, {}).get('name', f"Item {item_id}")
                last_item_name = "None" if last_item_id is None else full_item_data.get(last_item_id, {}).get('name', f"Item {last_item_id}")

                # role is taken from aggregation key (lane when purchase happened)
                if not role:
                    role = "Unknown"

                # Average gold at purchase for this aggregated entry
                avg_gold = 0
                if stats.get('golds'):
                    try:
                        avg_gold = float(np.mean(stats['golds']))
                    except Exception:
                        avg_gold = 0

                rows.append({
                    "VS Champion": enemy_champ,
                    "Item Name": item_name,
                    "Last Item": last_item_name,
                    "Role": role,
                    "Avg Gold At Purchase": round(avg_gold, 1),
                    "Win Rate (%)": round(winrate, 1),
                    "Gold Accel (5min) (%)": round(avg_accel, 2),
                    "Sample Size": count
                })

        # Tri : D'abord par Sample Size pour voir les items populaires en haut
        rows.sort(key=lambda x: x["Sample Size"], reverse=True)

        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            fieldnames = ["VS Champion", "Item Name", "Last Item", "Role", "Avg Gold At Purchase", "Win Rate (%)", "Gold Accel (5min) (%)", "Sample Size"]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
            
        print(f"  -> {my_champ} : Stats générées.")

    print(f"\n✅ Analyse terminée ! Voir '{OUTPUT_ROOT}'")

if __name__ == "__main__":
    main()


def build_feature_dataframe(matchup_root="matchup_analysis", champ_data_path="champ_data.csv", global_stats_root="global_stats"):
    """
    Construit un DataFrame pandas à partir des CSV de `matchup_analysis`, du `champ_data.csv` et du dossier `global_stats`.

    Columns returned:
      - Champion
      - Role
      - Adversaire
      - Dégat de l'adversaire (Damage Type)
      - Gold (Avg Gold At Purchase)
      - Item actuel (Last Item)
      - Next item (Item Name)

    Retourne: pandas.DataFrame
    """
    # Load champion metadata
    if not os.path.exists(champ_data_path):
        raise FileNotFoundError(f"champ_data.csv not found at {champ_data_path}")

    champ_df = pd.read_csv(champ_data_path)
    # Expect columns: Champion,Class,DmgType,Range
    champ_df = champ_df.rename(columns={c: c.strip() for c in champ_df.columns})
    dmg_map = dict(zip(champ_df['Champion'], champ_df['DmgType']))

    # Collect rows from matchup CSVs
    pattern = os.path.join(matchup_root, "*", "items_vs_champions.csv")
    files = glob.glob(pattern)
    rows = []
    for fpath in files:
        try:
            df = pd.read_csv(fpath)
        except Exception:
            continue

        champ_name = os.path.basename(os.path.dirname(fpath))
        df['Champion'] = champ_name
        # Standardize column names that may vary
        # Expect columns: VS Champion, Item Name, Last Item, Role, Avg Gold At Purchase
        for _, r in df.iterrows():
            vs = r.get('VS Champion') or r.get('VS_Champion')
            next_item = r.get('Item Name')
            last_item = r.get('Last Item')
            role = r.get('Role', 'Unknown')
            gold = r.get('Avg Gold At Purchase', 0)

            opponent_damage = dmg_map.get(vs, None)

            rows.append({
                'Champion': champ_name,
                'Role': role,
                'Adversaire': vs,
                'Dégat de l\'adversaire': opponent_damage,
                'Gold': gold,
                'Item actuel': last_item,
                'Next item': next_item
            })

    result_df = pd.DataFrame(rows)
    return result_df


# à rajouter option pour choisir si on veut étendre les features (classe, dégat) ou pas.
def build_feature_dataframe_from_parsed(parsed_folder="parsed_matches", champ_data_path="champ_data.csv", item_data_map=None):
    """
    Build a per-purchase pandas DataFrame from `parsed_matches` JSON files.

    Features returned:
      - Champion
      - Classe
      - dégat du champion
      - Role (uses `lane` from parsed_matches)
      - Adversaire
      - Classe de l'adversaire
      - Dégat de l'adversaire (Damage Type from `champ_data.csv`)
      - Gold (gold at purchase, if available)
      - Item actuel (last final item before this purchase)
      - Next item (the item bought at this purchase)

    This iterates every parsed match, each participant's purchase events and keeps only purchases
    that are considered "final items" by `is_final_item` (uses `item_data_map`).
    """
    if not os.path.exists(champ_data_path):
        raise FileNotFoundError(f"champ_data.csv not found at {champ_data_path}")

    champ_df = pd.read_csv(champ_data_path)
    dmg_map = dict(zip(champ_df['Champion'], champ_df['DmgType']))
    class_map = dict(zip(champ_df['Champion'], champ_df['Class']))

    if item_data_map is None:
        item_data_map = get_item_data()

    rows = []
    json_files = glob.glob(os.path.join(parsed_folder, "*.json"))
    for jf in json_files:
        try:
            with open(jf, 'r', encoding='utf-8') as f:
                match = json.load(f)
        except Exception:
            continue

        participants = match.get('participants', [])
        # build quick lookup by team+lane to find direct opponent
        for p in participants:
            champ = p.get('championName')
            role = p.get('lane')  # use lane as role
            team = p.get('teamId')
            gold_curve = p.get('gold_curve', [])

            # find opponent in same lane on opposite team
            opponent = None
            for opp in participants:
                if opp.get('teamId') != team and opp.get('lane') == role:
                    opponent = opp
                    break

            champ_damage = dmg_map.get(champ)
            champ_class = class_map.get(champ)

            opponent_champ = opponent.get('championName') if opponent else None
            
            opponent_damage = dmg_map.get(opponent_champ)
            opponent_class = class_map.get(opponent_champ)

            # iterate purchases in time order
            last_final_item = None
            purchases = sorted(p.get('item_purchases', []), key=lambda x: x.get('timestamp', 0))
            for purchase in purchases:
                item_id = str(purchase.get('itemId'))
                if not item_id:
                    continue

                if not is_final_item(item_id, item_data_map):
                    continue

                # gold at purchase
                purchase_min = purchase.get('timestamp', 0) / 60000.0
                idx = int(round(purchase_min))
                gold_at_buy = None
                if isinstance(gold_curve, list) and 0 <= idx < len(gold_curve):
                    gold_at_buy = gold_curve[idx]

                # map ids to names where possible
                next_item_name = item_data_map.get(item_id, {}).get('name') if isinstance(item_data_map.get(item_id), dict) else item_data_map.get(item_id, None)
                if not next_item_name:
                    next_item_name = f"Item {item_id}"

                last_item_name = None
                if last_final_item is None:
                    last_item_name = None
                else:
                    name = item_data_map.get(last_final_item, {})
                    last_item_name = name.get('name') if isinstance(name, dict) else item_data_map.get(last_final_item, f"Item {last_final_item}")

                rows.append({
                    'Champion': champ,
                    'Classe du champion': champ_class,
                    "Dégat du champion": champ_damage,
                    'Role': role,
                    'Adversaire': opponent_champ,
                    "Classe de l'adversaire": opponent_class,
                    "Dégat de l'adversaire": opponent_damage,
                    'Gold': gold_at_buy,
                    'Item actuel': last_item_name,
                    'Next item': next_item_name,
                })

                # update last_final_item
                last_final_item = item_id

    return pd.DataFrame(rows)