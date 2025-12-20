import json
import os
import glob
import requests
from collections import defaultdict

# --- Configuration ---
INPUT_FOLDER = "parsed_matches"

# --- Data Dragon & Filtres ---

def get_item_data():
    """Récupère les noms et les infos pour filtrer les composants."""
    print("Chargement des items (DataDragon)...")
    try:
        v = requests.get("https://ddragon.leagueoflegends.com/api/versions.json").json()[0]
        data = requests.get(f"https://ddragon.leagueoflegends.com/cdn/{v}/data/en_US/item.json").json()
        return data['data']
    except:
        return {}

def is_final_item(item_id, item_data_map):
    """Même filtre que précédemment : on ne veut que les vrais items."""
    if item_id not in item_data_map: return False
    info = item_data_map[item_id]
    
    # Garder les bottes finales
    if "Boots" in info.get('tags', []) and not info.get('into'):
        return True
    
    # Exclure composants et items pas chers
    if info.get('into') or info['gold']['total'] < 1600:
        return False
        
    return True

# --- Cerveau IA (Markov) ---

class ItemAdvisorAI:
    def __init__(self):
        self.item_data = get_item_data()
        # Structure: memory[MyChamp][EnemyChamp][CurrentItem][NextItem] = Score
        self.specific_memory = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(float))))
        # Structure: memory[MyChamp][CurrentItem][NextItem] = Score (Pour le cas général)
        self.general_memory = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))

    def train(self):
        """Lit les fichiers et construit les matrices de probabilités."""
        files = glob.glob(os.path.join(INPUT_FOLDER, "*.json"))
        print(f"Entraînement de l'IA sur {len(files)} parties...")
        
        count = 0
        for filepath in files:
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    match = json.load(f)
                
                participants = match['participants']
                
                # On analyse chaque joueur de la game
                for p in participants:
                    my_champ = p['championName']
                    my_team = p['teamId']
                    my_lane = p['lane']
                    win = p['win']
                    
                    # Ignorer les lanes exotiques
                    if my_lane not in ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"]: continue

                    # Trouver l'adversaire direct
                    opponent = None
                    for opp in participants:
                        if opp['teamId'] != my_team and opp['lane'] == my_lane:
                            opponent = opp
                            break
                    
                    enemy_champ = opponent['championName'] if opponent else "Unknown"

                    # --- Extraction de la séquence d'achat ---
                    build_sequence = ["START"] # Point de départ
                    
                    # On filtre pour ne garder que la séquence d'items finaux
                    processed_ids = set()
                    for purchase in p['item_purchases']:
                        i_id = str(purchase['itemId'])
                        
                        # Filtre Composants
                        if not is_final_item(i_id, self.item_data): continue
                        # Pas de doublons immédiats dans la séquence
                        if i_id in processed_ids: continue
                        
                        build_sequence.append(i_id)
                        processed_ids.add(i_id)
                    
                    # --- Apprentissage (Renforcement) ---
                    # Poids : Victoire = 3 points, Défaite = 0.5 point
                    # On veut que l'IA favorise fortement les chemins qui gagnent
                    weight = 3.0 if win else 0.5
                    
                    for i in range(len(build_sequence) - 1):
                        current_node = build_sequence[i]
                        next_node = build_sequence[i+1]
                        
                        # 1. Apprentissage Spécifique (Garen vs Darius)
                        self.specific_memory[my_champ][enemy_champ][current_node][next_node] += weight
                        
                        # 2. Apprentissage Général (Garen vs All)
                        self.general_memory[my_champ][current_node][next_node] += weight
                        
                count += 1
            except Exception as e:
                pass
        print("Entraînement terminé !")

    def get_item_name(self, item_id):
        return self.item_data.get(item_id, {}).get('name', f"ID {item_id}")

    def recommend_build(self, my_champ, enemy_champ):
        """Génère le build optimal."""
        print(f"\n🤖 --- Analyse IA : {my_champ} vs {enemy_champ} ---")
        
        # Étape 1 : A-t-on assez de données sur ce matchup précis ?
        # On regarde si on a des transitions depuis "START" pour ce duel
        specific_data = self.specific_memory[my_champ].get(enemy_champ)
        
        transitions = None
        mode = ""
        
        if specific_data and len(specific_data["START"]) > 0:
            print(f"✅ Données spécifiques trouvées pour le duel {my_champ} vs {enemy_champ}.")
            transitions = specific_data
            mode = "SPECIFIC"
        else:
            print(f"⚠️ Pas assez de données vs {enemy_champ}. Utilisation du build GÉNÉRAL pour {my_champ}.")
            transitions = self.general_memory.get(my_champ)
            mode = "GENERAL"

        if not transitions:
            print("❌ Aucune donnée pour ce champion. Lancez le scraper d'abord !")
            return

        # Étape 2 : Simulation de la chaîne de Markov (Greedy)
        # On part de START et on prend le chemin le plus lourd à chaque fois
        current_item = "START"
        build_path = []
        visited = set()
        
        print("\n--- 🛡️ Build Recommandé ---")
        
        for i in range(1, 7): # Max 6 items
            next_options = transitions.get(current_item)
            
            if not next_options:
                break # Fin du chemin connue
            
            # Trouver l'item avec le plus gros score
            # next_options est un dict {ItemId: Score}
            best_next = max(next_options, key=next_options.get)
            score = next_options[best_next]
            
            # Sécurité anti-boucle infinie (rare mais possible)
            if best_next in visited: 
                # Essayer le 2ème meilleur si le 1er est déjà pris
                sorted_opts = sorted(next_options.items(), key=lambda x: x[1], reverse=True)
                found_new = False
                for item, s in sorted_opts:
                    if item not in visited:
                        best_next = item
                        score = s
                        found_new = True
                        break
                if not found_new: break

            item_name = self.get_item_name(best_next)
            print(f"Item {i}: {item_name} (Score de confiance: {score:.1f})")
            
            build_path.append(best_next)
            visited.add(best_next)
            current_item = best_next # On avance dans la chaîne

        return build_path

# --- Interface Utilisateur ---

def main():
    # 1. Initialisation
    ai = ItemAdvisorAI()
    
    # 2. Entraînement
    ai.train()
    
    # 3. Boucle d'interaction
    while True:
        print("\n" + "="*30)
        user_input = input("Entrez 'MonChampion vs Ennemi' (ex: Garen vs Darius)\nOu 'q' pour quitter : ")
        
        if user_input.lower() == 'q':
            break
            
        try:
            if " vs " in user_input:
                parts = user_input.split(" vs ")
                my_c = parts[0].strip()
                en_c = parts[1].strip()
                
                # On lance la recommandation
                ai.recommend_build(my_c, en_c)
            else:
                print("Format invalide. Utilisez 'Champion vs Champion'.")
        except Exception as e:
            print(f"Erreur : {e}")

if __name__ == "__main__":
    main()