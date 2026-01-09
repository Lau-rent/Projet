import json
import os
import glob
import requests
from collections import defaultdict
import sys

# --- Configuration ---
script_dir = os.path.dirname(os.path.abspath(__file__))
INPUT_FOLDER = os.path.join(script_dir, "parsed_matches")
BRAIN_FILE = os.path.join(script_dir, "ai_brain.json") # Le fichier où on stocke l'intelligence

# --- Data Dragon & Filtres ---

def get_item_data():
    print("Chargement des items (DataDragon)...")
    try:
        v = requests.get("https://ddragon.leagueoflegends.com/api/versions.json").json()[0]
        data = requests.get(f"https://ddragon.leagueoflegends.com/cdn/{v}/data/en_US/item.json").json()
        return data['data']
    except:
        return {}

def is_final_item(item_id, item_data_map):
    if item_id not in item_data_map: return False
    info = item_data_map[item_id]
    if "Boots" in info.get('tags', []) and not info.get('into'): return True
    if info.get('into') or info['gold']['total'] < 1600: return False
    return True

# --- Cerveau IA (Markov) ---

class ItemAdvisorAI:
    def __init__(self):
        self.item_data = get_item_data()
        # On utilise des dict normaux ici pour faciliter la sauvegarde JSON
        self.specific_memory = {} 
        self.general_memory = {}

    def save_brain(self):
        """Sauvegarde les matrices dans un fichier JSON."""
        data = {
            "specific": self.specific_memory,
            "general": self.general_memory
        }
        with open(BRAIN_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f)
        print(f"[OK] Cerveau sauvegardé dans '{BRAIN_FILE}'")

    def load_brain(self):
        """Charge les matrices depuis le fichier JSON."""
        if not os.path.exists(BRAIN_FILE):
            return False
        
        print(f"Chargement du cerveau depuis '{BRAIN_FILE}'...")
        try:
            with open(BRAIN_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.specific_memory = data["specific"]
                self.general_memory = data["general"]
            return True
        except Exception as e:
            print(f"Erreur lecture cerveau: {e}")
            return False

    def train(self):
        """Lit les fichiers et construit les matrices de probabilités."""
        # On utilise defaultdict temporairement pour l'entraînement
        # memory[MyChamp][EnemyChamp][CurrentItem][NextItem] = Score
        temp_specific = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(float))))
        temp_general = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
        
        files = glob.glob(os.path.join(INPUT_FOLDER, "*.json"))
        print(f"[..] Démarrage de l'entraînement sur {len(files)} parties...")
        
        for filepath in files:
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    match = json.load(f)
                
                participants = match['participants']
                for p in participants:
                    my_champ = p['championName']
                    my_team = p['teamId']
                    my_lane = p['lane']
                    win = p['win']
                    
                    if my_lane not in ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"]: continue

                    opponent = None
                    for opp in participants:
                        if opp['teamId'] != my_team and opp['lane'] == my_lane:
                            opponent = opp
                            break
                    
                    enemy_champ = opponent['championName'] if opponent else "Unknown"

                    build_sequence = ["START"]
                    processed_ids = set()
                    
                    for purchase in p['item_purchases']:
                        i_id = str(purchase['itemId'])
                        if not is_final_item(i_id, self.item_data): continue
                        if i_id in processed_ids: continue
                        
                        build_sequence.append(i_id)
                        processed_ids.add(i_id)
                    
                    # Poids : Victoire = 3, Défaite = 0.5
                    weight = 3.0 if win else 0.5
                    
                    for i in range(len(build_sequence) - 1):
                        current_node = build_sequence[i]
                        next_node = build_sequence[i+1]
                        
                        temp_specific[my_champ][enemy_champ][current_node][next_node] += weight
                        temp_general[my_champ][current_node][next_node] += weight
                        
            except Exception:
                pass
        
        # Conversion en dict standard pour la sauvegarde
        # (Les defaultdict ne sont pas compatibles JSON direct)
        self.specific_memory = json.loads(json.dumps(temp_specific))
        self.general_memory = json.loads(json.dumps(temp_general))
        
        print("Entraînement terminé !")
        self.save_brain()

    def get_item_name(self, item_id):
        return self.item_data.get(item_id, {}).get('name', f"ID {item_id}")

    def _print_path(self, transitions, title):
        current_item = "START"
        visited = set()
        
        print(f"\n--- [@] {title} ---")
        
        for i in range(1, 7): 
            if current_item not in transitions:
                break 
            
            next_options = transitions[current_item]
            if not next_options: break
            
            # Algorithme glouton : prendre le meilleur score
            # On trie les options par score décroissant
            sorted_opts = sorted(next_options.items(), key=lambda x: x[1], reverse=True)
            
            best_next = None
            score = 0
            
            # On cherche le premier item non visité (pour éviter d'acheter 2 fois le même)
            for item, s in sorted_opts:
                if item not in visited:
                    best_next = item
                    score = s
                    break
            
            if not best_next: break # Plus d'options valides

            item_name = self.get_item_name(best_next)
            print(f"Item {i}: {item_name} (Score: {score:.1f})")
            
            visited.add(best_next)
            current_item = best_next

    def recommend_build(self, my_champ, enemy_champ):
        print(f"\n[?] --- Analyse IA : {my_champ} vs {enemy_champ} ---")
        
        # 1. Build Général (Toujours affiché)
        if my_champ in self.general_memory and "START" in self.general_memory[my_champ]:
            self._print_path(self.general_memory[my_champ], f"Build GÉNÉRAL (Reference)")
        else:
            print(f"[!] Pas de données générales pour {my_champ}.")
            return # Si pas de général, probablement pas de champ du tout, on arrête ? Ou on check spécifique ?
                   # Généralement si on a spécifique on a général (car update simultané), donc return est safe.

        # 2. Build Spécifique (Si disponible)
        has_specific = (my_champ in self.specific_memory and 
                        enemy_champ in self.specific_memory[my_champ] and
                        "START" in self.specific_memory[my_champ][enemy_champ])
        
        if has_specific:
            print(f"[OK] Données SPÉCIFIQUES trouvées (Matchup connu).")
            self._print_path(self.specific_memory[my_champ][enemy_champ], f"Build SPÉCIFIQUE (vs {enemy_champ})")
        else:
            print(f"[!] Pas de données spécifiques vs {enemy_champ}. (Comparaison impossible)")

# --- Interface ---

def main():
    ai = ItemAdvisorAI()
    
    # Logique de chargement intelligente
    if os.path.exists(BRAIN_FILE):
        # Si le fichier existe, on charge
        ai.load_brain()
        print("\n[?] Astuce : Supprimez 'ai_brain.json' pour forcer un ré-entraînement.")
    else:
        # Sinon, on entraîne
        print("[!] Cerveau introuvable. Lancement de l'entraînement...")
        ai.train()
    
    # Boucle
    while True:
        print("\n" + "="*30)
        user_input = input("Entrez 'MonChampion vs Ennemi' (ex: Garen vs Darius)\n'retrain' pour recalculer\n'q' pour quitter : ")
        
        if user_input.lower() == 'q':
            break
        
        if user_input.lower() == 'retrain':
            ai.train()
            continue
            
        try:
            if " vs " in user_input:
                parts = user_input.split(" vs ")
                my_c = parts[0].strip()
                en_c = parts[1].strip()
                ai.recommend_build(my_c, en_c)
            else:
                print("Format invalide. Utilisez 'Champion vs Champion'.")
        except Exception as e:
            print(f"Erreur : {e}")

if __name__ == "__main__":
    main()