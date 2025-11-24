import json
import os
import glob
import requests
import csv
import numpy as np
from collections import defaultdict

# --- Configuration ---
INPUT_FOLDER = "parsed_matches"
OUTPUT_ROOT = "global_stats"

# --- Data Dragon (Pour avoir les noms des items) ---
def get_item_map():
    print("Récupération des noms d'items via DataDragon...")
    try:
        v_url = "https://ddragon.leagueoflegends.com/api/versions.json"
        version = requests.get(v_url).json()[0]
        i_url = f"https://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/item.json"
        data = requests.get(i_url).json()
        
        mapping = {}
        for i_id, i_data in data['data'].items():
            mapping[str(i_id)] = i_data['name']
        return mapping
    except Exception as e:
        print(f"Erreur DDragon: {e}")
        return {}

# --- Fonctions de Calcul ---

def calculate_gold_acceleration(purchase_timestamp_ms, gold_curve, timestamps_minutes):
    """
    Calcule le % d'augmentation du GPM (Gold Per Minute) dans les 5 minutes suivant l'achat.
    Retourne None si la game finit avant 5 min.
    """
    purchase_min = purchase_timestamp_ms / 60000.0
    
    # On ne calcule pas pour les items de départ (avant 3 minutes) car le GPM est instable
    if purchase_min < 3:
        return None

    # Trouver l'index le plus proche dans la courbe d'or (qui est minute par minute)
    # timestamps_minutes est généralement [0, 1, 2, 3...]
    idx_buy = int(round(purchase_min))
    idx_future = idx_buy + 5
    
    # Vérifier qu'on ne sort pas du tableau (la game doit durer encore 5 min)
    if idx_buy >= len(gold_curve) or idx_future >= len(gold_curve):
        return None

    gold_at_buy = gold_curve[idx_buy]
    gold_at_future = gold_curve[idx_future]

    # 1. GPM Avant (Moyenne depuis le début de la game)
    # On évite la division par zéro
    pre_gpm = gold_at_buy / (purchase_min if purchase_min > 0 else 1)

    # 2. GPM Après (Sur la fenêtre de 5 minutes)
    gold_diff = gold_at_future - gold_at_buy
    post_gpm = gold_diff / 5.0

    # 3. Accélération en %
    if pre_gpm == 0: return 0
    
    acceleration = ((post_gpm - pre_gpm) / pre_gpm) * 100
    return acceleration

# --- Main Logic ---

def main():
    item_names = get_item_map()
    os.makedirs(OUTPUT_ROOT, exist_ok=True)
    
    json_files = glob.glob(os.path.join(INPUT_FOLDER, "*.json"))
    if not json_files:
        print("Aucun fichier JSON trouvé.")
        return

    # Structure de données :
    # champions_stats[ChampionName][ItemId] = { 'picks': 0, 'wins': 0, 'accel_values': [] }
    # champion_games_count[ChampionName] = total_games_played
    champions_stats = defaultdict(lambda: defaultdict(lambda: {'picks': 0, 'wins': 0, 'accel_values': []}))
    champion_games_count = defaultdict(int)

    print(f"Analyse de {len(json_files)} parties pour les statistiques globales...")

    for filepath in json_files:
        with open(filepath, 'r', encoding='utf-8') as f:
            match_data = json.load(f)
        
        timestamps = match_data['timestamps_minutes']
        
        # Pour compter le nombre de games par champion correctement
        # On doit savoir quels champions sont dans cette game
        present_champs = set()

        for p in match_data['participants']:
            champ = p['championName']
            present_champs.add(champ)
            win = p['win']
            gold_curve = p['gold_curve']
            
            # On note les items déjà comptés pour ce joueur dans cette game
            # pour ne pas compter 2 fois le même item s'il l'achète, le vend et le rachète (cas rare mais possible)
            # ou si on veut compter chaque achat. Ici comptons chaque achat distinct.
            processed_items_in_game = set()

            for purchase in p['item_purchases']:
                item_id = str(purchase['itemId'])
                
                # Ignorer les items insignifiants ou trinkets si besoin (optionnel)
                # if item_id in ["3340", "2055"]: continue 

                # Calcul Accélération
                accel = calculate_gold_acceleration(purchase['timestamp'], gold_curve, timestamps)
                
                # Mise à jour des stats
                stats_entry = champions_stats[champ][item_id]
                
                # On incrémente le pick rate (une fois par game par item max, ou à chaque achat ?)
                # Généralement "Pick Rate" = "Est-ce que l'item a été acheté dans la game ?"
                if item_id not in processed_items_in_game:
                    stats_entry['picks'] += 1
                    if win:
                        stats_entry['wins'] += 1
                    processed_items_in_game.add(item_id)
                
                # On ajoute l'accélération à la liste (si valide)
                if accel is not None:
                    stats_entry['accel_values'].append(accel)

        # Mise à jour du compteur total de games pour les champions présents
        for champ in present_champs:
            champion_games_count[champ] += 1

    # --- Génération des Rapports ---
    
    print("Génération des fichiers de statistiques...")

    for champ, items_data in champions_stats.items():
        # Créer dossier champion
        champ_dir = os.path.join(OUTPUT_ROOT, champ)
        os.makedirs(champ_dir, exist_ok=True)
        
        csv_path = os.path.join(champ_dir, "item_stats.csv")
        total_games = champion_games_count[champ]

        # Préparer les lignes pour le CSV
        rows = []
        for item_id, stats in items_data.items():
            item_name = item_names.get(item_id, f"Item {item_id}")
            
            picks = stats['picks']
            wins = stats['wins']
            accel_list = stats['accel_values']
            
            # Calculs finaux
            pick_rate = (picks / total_games) * 100
            win_rate = (wins / picks) * 100 if picks > 0 else 0
            
            # Moyenne de l'accélération
            avg_accel = np.mean(accel_list) if accel_list else 0
            
            rows.append({
                "Item Name": item_name,
                "Item ID": item_id,
                "Pick Rate (%)": round(pick_rate, 2),
                "Win Rate (%)": round(win_rate, 2),
                "Gold Accel (5min) (%)": round(avg_accel, 2),
                "Sample Size (Games)": picks
            })

        # Trier par Pick Rate décroissant (les items les plus achetés en premier)
        rows.sort(key=lambda x: x["Pick Rate (%)"], reverse=True)

        # Écriture CSV
        with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = ["Item Name", "Item ID", "Pick Rate (%)", "Win Rate (%)", "Gold Accel (5min) (%)", "Sample Size (Games)"]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
        
        print(f"  -> {champ} : stats sauvegardées ({total_games} games)")

    print(f"\n✅ Analyse terminée ! Dossiers créés dans '{OUTPUT_ROOT}/'")

if __name__ == "__main__":
    main()