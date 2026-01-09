import json
import glob
import os
import matplotlib.pyplot as plt
from collections import Counter

# --- Configuration ---
script_dir = os.path.dirname(os.path.abspath(__file__))
INPUT_FOLDER = os.path.join(script_dir, "parsed_matches")
OUTPUT_FOLDER = os.path.join(script_dir, "analysis_graphs")

def main():
    # 1. Préparation
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)
    json_files = glob.glob(os.path.join(INPUT_FOLDER, "*.json"))
    
    if not json_files:
        print(f"❌ Aucun fichier trouvé dans {INPUT_FOLDER}")
        return

    print(f"Analyse de {len(json_files)} parties pour la popularité des champions...")

    # 2. Collecte des données
    champion_counts = Counter()
    total_games = 0

    for filepath in json_files:
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # On compte les champions présents dans la partie
            # Utiliser un set pour ne pas compter deux fois le même champion si bug (normalement impossible en ranked)
            champs_in_game = set()
            for p in data['participants']:
                champs_in_game.add(p['championName'])
            
            champion_counts.update(champs_in_game)
            total_games += 1
            
        except Exception as e:
            print(f"Erreur lecture {filepath}: {e}")

    if total_games == 0:
        print("Aucune partie valide analysée.")
        return

    # 3. Calcul des stats
    # On prépare les données pour le graph (Top 20 par exemple)
    TOP_N = 20
    most_common = champion_counts.most_common(TOP_N)
    
    champions = [item[0] for item in most_common]
    dates = [item[1] for item in most_common] # Raw counts
    percentages = [(count / total_games) * 100 for count in dates]

    # 4. Génération du Graphique
    plt.figure(figsize=(14, 8))
    
    # Bar chart
    bars = plt.bar(champions, percentages, color='skyblue', edgecolor='navy')
    
    plt.xlabel('Champions', fontsize=12)
    plt.ylabel('Présence (% des games)', fontsize=12)
    plt.title(f'Top {TOP_N} Champions les plus joués (sur {total_games} games)', fontsize=16, fontweight='bold')
    plt.xticks(rotation=45, ha='right')
    plt.grid(axis='y', linestyle='--', alpha=0.7)

    # Ajouter les pourcentages au dessus des barres
    for bar in bars:
        height = bar.get_height()
        plt.text(bar.get_x() + bar.get_width()/2., height + 0.5,
                 f'{height:.1f}%',
                 ha='center', va='bottom', fontsize=9, fontweight='bold')

    # Sauvegarde
    output_path = os.path.join(OUTPUT_FOLDER, "champion_popularity.png")
    plt.tight_layout()
    plt.savefig(output_path, dpi=100)
    plt.close()

    print(f"\n[OK] Graphique généré : {output_path}")
    
    # Affichage console du top 5
    print("\n--- Top 5 Champions ---")
    for i, (champ, count) in enumerate(most_common[:5], 1):
        rate = (count / total_games) * 100
        print(f"{i}. {champ}: {rate:.1f}% ({count} games)")

if __name__ == "__main__":
    main()
