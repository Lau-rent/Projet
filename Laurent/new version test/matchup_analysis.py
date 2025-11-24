import json
import os
import glob
import requests
import csv
import numpy as np
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

    # Structure : stats[MyChamp][EnemyChamp][ItemID] = ...
    data_store = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: {'wins': 0, 'count': 0, 'accels': []})))

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
                
                for purchase in p['item_purchases']:
                    item_id = str(purchase['itemId'])
                    
                    # --- FILTRE AVEC EXCEPTION BOTTES ---
                    if not is_final_item(item_id, full_item_data):
                        continue 
                    # ------------------------------------
                    
                    if item_id in processed_items: continue

                    accel = calculate_gold_acceleration(purchase['timestamp'], p['gold_curve'], timestamps)
                    
                    entry = data_store[my_champ][enemy_champ][item_id]
                    entry['count'] += 1
                    if p['win']:
                        entry['wins'] += 1
                    
                    if accel is not None:
                        entry['accels'].append(accel)
                        
                    processed_items.add(item_id)

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
            for item_id, stats in items.items():
                count = stats['count']
                if count == 0: continue
                
                winrate = (stats['wins'] / count) * 100
                avg_accel = np.mean(stats['accels']) if stats['accels'] else 0
                
                # Nom de l'item
                item_name = full_item_data.get(item_id, {}).get('name', f"Item {item_id}")
                
                rows.append({
                    "VS Champion": enemy_champ,
                    "Item Name": item_name,
                    "Win Rate (%)": round(winrate, 1),
                    "Gold Accel (5min) (%)": round(avg_accel, 2),
                    "Sample Size": count
                })

        # Tri : D'abord par Sample Size pour voir les items populaires en haut
        rows.sort(key=lambda x: x["Sample Size"], reverse=True)

        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            fieldnames = ["VS Champion", "Item Name", "Win Rate (%)", "Gold Accel (5min) (%)", "Sample Size"]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
            
        print(f"  -> {my_champ} : Stats générées.")

    print(f"\n✅ Analyse terminée ! Voir '{OUTPUT_ROOT}'")

if __name__ == "__main__":
    main()