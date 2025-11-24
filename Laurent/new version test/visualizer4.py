import json
import matplotlib.pyplot as plt
from matplotlib.offsetbox import OffsetImage, AnnotationBbox
import os
import numpy as np
import glob
import sys

# --- Configuration ---
INPUT_FOLDER = "parsed_matches"
ICONS_FOLDER = "item_icons"
OUTPUT_FOLDER = "analysis_graphs"

# Seuil de temps (en minutes) pour considérer que des achats sont "simultanés"
STACK_TIME_WINDOW = 1.5 

def load_json(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)

def get_item_icon_path(item_id):
    direct_path = os.path.join(ICONS_FOLDER, f"{item_id}.png")
    if os.path.exists(direct_path):
        return direct_path
    for root, dirs, files in os.walk(ICONS_FOLDER):
        if f"{item_id}.png" in files:
            return os.path.join(root, f"{item_id}.png")
    return None

def get_max_stack_size(purchases):
    """Scanne les achats pour trouver le plus haut stack."""
    if not purchases: return 0
    max_stack = 0
    current_stack = 0
    cluster_start_time = -999
    
    sorted_purchases = sorted(purchases, key=lambda x: x["timestamp"])
    
    for item in sorted_purchases:
        ts_min = item["timestamp"] / 60000.0
        if ts_min - cluster_start_time < STACK_TIME_WINDOW:
            current_stack += 1
        else:
            max_stack = max(max_stack, current_stack)
            current_stack = 1
            cluster_start_time = ts_min
    return max(max_stack, current_stack)

def plot_player_graph(player_data, timestamps, match_info, output_dir):
    champion = player_data["championName"]
    pid = player_data["participantId"]
    win = player_data["win"]
    gold_curve = player_data["gold_curve"]
    purchases = player_data["item_purchases"]
    lane = player_data["lane"]
    
    timestamps_np = np.array(timestamps)
    
    # 1. Calcul Échelle
    max_stack_height = get_max_stack_size(purchases)
    max_gold = max(gold_curve) if gold_curve else 10000
    
    # Facteur d'étirement si beaucoup d'items empilés
    stretch_factor = 1.0
    if max_stack_height > 3:
        stretch_factor = 1.0 + ((max_stack_height - 3) * 0.12)
    
    adjusted_ymax = max_gold * stretch_factor

    # 2. Création Graphique
    plt.figure(figsize=(14, 8))
    ax = plt.gca()
    ax.set_ylim(bottom=-max_gold*0.05, top=adjusted_ymax)

    line_color = "#FFD700" if win else "#808080"
    ax.plot(timestamps_np, gold_curve, color=line_color, linewidth=2.5, label="Total Gold")
    ax.fill_between(timestamps_np, gold_curve, color=line_color, alpha=0.1)

    # 3. Items
    last_annotation_time = -999
    stack_counter = 0 
    
    for item in purchases:
        ts_ms = item["timestamp"]
        ts_min = ts_ms / 60000.0
        item_id = str(item["itemId"])
        
        icon_path = get_item_icon_path(item_id)
        if not icon_path: continue
            
        if ts_min - last_annotation_time < STACK_TIME_WINDOW:
            stack_counter += 1
        else:
            stack_counter = 0
            last_annotation_time = ts_min
            
        y_offset = 25 + (stack_counter * 35)
            
        try:
            img = plt.imread(icon_path)
            imagebox = OffsetImage(img, zoom=0.35) 
            ab = AnnotationBbox(
                imagebox, (ts_min, 0), xycoords=('data', 'data'),
                boxcoords="offset points", xybox=(0, y_offset),
                frameon=False, pad=0
            )
            ax.add_artist(ab)
            
            if stack_counter == 0:
                ax.axvline(x=ts_min, color='gray', linestyle=':', alpha=0.3, zorder=0)
            
        except Exception:
            pass

    # 4. Info & Save
    match_id = match_info.get("matchId", "Unknown")
    date = match_info.get("gameDate", "N/A")
    rank = match_info.get("rank", "N/A")
    duration = match_info.get("gameDuration", 0) // 60
    
    outcome = "VICTOIRE" if win else "DÉFAITE"
    title_color = "green" if win else "red"
    
    plt.title(f"{champion} ({lane}) - {outcome}\n{rank} - {date} - {duration} min", 
              fontsize=16, fontweight='bold', color=title_color)
    plt.xlabel("Temps de jeu (Minutes)")
    plt.ylabel("Gold Total")
    plt.grid(True, linestyle='--', alpha=0.5)
    plt.legend(loc='upper left')
    
    safe_champ = "".join(x for x in champion if x.isalnum())
    filename = f"{match_id}_{pid}_{safe_champ}.png"
    full_path = os.path.join(output_dir, filename)
    
    plt.tight_layout()
    plt.savefig(full_path, dpi=100)
    plt.close()
    print(f"  -> Graphique généré : {filename}")

def show_graph(TARGET_MATCH_ID = None):
    
    # Petit bonus : permet de passer l'ID en ligne de commande si envie
    # ex: python analyzer.py EUW1_123456
    if len(sys.argv) > 1:
        TARGET_MATCH_ID = sys.argv[1]

    json_files = []

    if TARGET_MATCH_ID:
        print(f"--- Mode Cible Unique : {TARGET_MATCH_ID} ---")
        # On utilise le wildcard * car le nom du fichier contient le préfixe du mode de jeu (RANKED_...)
        # qu'on ne connait pas forcément par coeur.
        search_pattern = os.path.join(INPUT_FOLDER, f"*{TARGET_MATCH_ID}.json")
        json_files = glob.glob(search_pattern)
        
        if not json_files:
            print(f"❌ Fichier introuvable pour l'ID : {TARGET_MATCH_ID}")
            print(f"   Vérifiez que le fichier existe bien dans '{INPUT_FOLDER}'")
            return
    else:
        print("--- Mode Traitement de masse (Tout le dossier) ---")
        json_files = glob.glob(os.path.join(INPUT_FOLDER, "*.json"))

    if not json_files:
        print(f"Aucun fichier .json trouvé dans '{INPUT_FOLDER}'.")
        return

    print(f"Fichier(s) à traiter : {len(json_files)}")

    for json_file in json_files:
        print(f"\nTraitement : {os.path.basename(json_file)}")
        try:
            data = load_json(json_file)
            match_info = {
                "matchId": data.get("matchId"),
                "gameDate": data.get("gameDate"),
                "rank": data.get("rank"),
                "gameDuration": data.get("gameDuration")
            }
            timestamps = data["timestamps_minutes"]
            
            for participant in data["participants"]:
                plot_player_graph(participant, timestamps, match_info, OUTPUT_FOLDER)
                
        except Exception as e:
            print(f"Erreur : {e}")

    print(f"\n✅ Terminé ! Voir '{OUTPUT_FOLDER}'")




def main():
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)
    
    # ==========================================
    # 🎯 CONFIGURATION CIBLE
    # Mettez l'ID ici (ex: "EUW1_7237077366") pour traiter une seule game.
    # Mettez None pour traiter tout le dossier.
    # ==========================================
    TARGET_MATCH_ID = 7555047844
    show_graph(TARGET_MATCH_ID)
    # ==========================================


if __name__ == "__main__":
    main()