import json
import glob
import os
import matplotlib.pyplot as plt
import numpy as np
from collections import Counter

# --- Configuration ---
script_dir = os.path.dirname(os.path.abspath(__file__))
INPUT_FOLDER = os.path.join(script_dir, "parsed_matches")
OUTPUT_FOLDER = os.path.join(script_dir, "analysis_graphs")

# Données u.gg (Global - Emerald+ - Patch 16.1 - extracted 2026-01-09)
GLOBAL_STATS = {
    "Kai'Sa": 19.8,
    "Aphelios": 15.9,
    "Lucian": 15.2,
    "Caitlyn": 15.1,
    "Nami": 14.5,
    "Ezreal": 13.8,
    "Jhin": 13.7,
    "Lee Sin": 12.7,
    "Karma": 12.2,
    "Nautilus": 11.9,
    "Lulu": 11.7,
    "Thresh": 11.7,
    "Katarina": 11.1,
    "Akali": 11.0,
    "Jayce": 10.5,
    "Jinx": 10.1,
    "Diana": 10.1,
    "Viego": 10.1,
    "Yunara": 10.0,
    "Aatrox": 8.9
}

def main():
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)
    json_files = glob.glob(os.path.join(INPUT_FOLDER, "*.json"))
    
    if not json_files:
        print(f"❌ Aucun fichier trouvé dans {INPUT_FOLDER}")
        return

    print(f"Analyse de {len(json_files)} parties locales...")

    # --- 1. Calcul des Stats Locales ---
    champion_counts = Counter()
    total_local_games = 0

    for filepath in json_files:
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            champs_in_game = set()
            for p in data['participants']:
                champs_in_game.add(p['championName'])
            
            champion_counts.update(champs_in_game)
            total_local_games += 1
            
        except Exception:
            pass

    if total_local_games == 0:
        print("Aucune partie valide.")
        return

    # --- 2. Préparation des Données Comparatives ---
    # Normalisation pour comparaison (ex: "Kai'Sa" vs "Kaisa", "Lee Sin" vs "LeeSin")
    def normalize(name):
        return name.replace("'", "").replace(" ", "").lower()

    # Map normalized names to proper display names from Global list
    global_norm_map = {normalize(k): k for k in GLOBAL_STATS.keys()}
    
    # Pre-calculate local counts with normalized keys
    local_counts_norm = {normalize(k): v for k, v in champion_counts.items()}

    champions = list(GLOBAL_STATS.keys())
    global_values = list(GLOBAL_STATS.values())
    
    local_values = []
    diffs = []

    print("\n--- Comparatif (Local vs Global) ---")
    print(f"{'Champion':<12} | {'Local %':<8} | {'Global %':<8} | {'Diff':<6}")
    print("-" * 45)

    for champ in champions:
        norm_name = normalize(champ)
        
        # On cherche dans le dict local normalisé
        count = local_counts_norm.get(norm_name, 0)
        local_rate = (count / total_local_games) * 100
        
        local_values.append(local_rate)
        diff = local_rate - GLOBAL_STATS[champ]
        diffs.append(diff)
        
        print(f"{champ:<12} | {local_rate:<8.1f} | {GLOBAL_STATS[champ]:<8.1f} | {diff:+.1f}")

    # --- 3. Génération du Graphique ---
    x = np.arange(len(champions))
    width = 0.35

    plt.figure(figsize=(15, 8))
    
    # Barres
    bars1 = plt.bar(x - width/2, global_values, width, label='Global (u.gg)', color='#e0e0e0', edgecolor='#999999')
    bars2 = plt.bar(x + width/2, local_values, width, label='Local (Dataset)', color='#3b82f6', edgecolor='#1e40af')

    # Lignes et Labels
    plt.axhline(0, color='black', linewidth=0.8)
    plt.xlabel('Champions (Top 20 u.gg)', fontsize=12)
    plt.ylabel('Pick Rate (%)', fontsize=12)
    plt.title(f'Comparaison Popularité : Dataset Local ({total_local_games} games) vs Global (u.gg)', fontsize=16, fontweight='bold')
    plt.xticks(x, champions, rotation=45, ha='right')
    plt.legend()
    plt.grid(axis='y', linestyle='--', alpha=0.5)

    # Annotations sur les barres locales
    for bar, val in zip(bars2, local_values):
        height = bar.get_height()
        plt.text(bar.get_x() + bar.get_width()/2., height + 0.2,
                 f'{val:.1f}%',
                 ha='center', va='bottom', fontsize=8, color='black', fontweight='bold')

    output_path = os.path.join(OUTPUT_FOLDER, "champion_comparison_ugg.png")
    plt.tight_layout()
    plt.savefig(output_path, dpi=100)
    plt.close()

    print(f"\n[OK] Graphique comparatif généré : {output_path}")

if __name__ == "__main__":
    main()
