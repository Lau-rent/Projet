import requests
import csv

def get_latest_version():
    versions = requests.get("https://ddragon.leagueoflegends.com/api/versions.json").json()
    return versions[0]

def class_to_dmg_type(champ_class):
    # simplification pour déduire type de dégat à partir de la classe, Attention aux assassins et certains fighters
    mapping = {
        "Fighter": "AD",
        "Tank": "AP",
        "Assassin": "AD",
        "Marksman": "AD",
        "Mage": "AP",
        "Support": "AP"
    }
    return mapping.get(champ_class, "Mixed")  # fallback

def build_champ_data():
    # wukong = monkeyking
    version = get_latest_version()
    print("Using Data Dragon version:", version)

    url = f"https://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/champion.json"
    data = requests.get(url).json()["data"]

    rows = []

    for champ_name, champ_meta in data.items():
        champ_id = champ_meta["id"]

        # récupération des stats de base pour RangeType
        detail_url = f"https://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/champion/{champ_id}.json"
        full = requests.get(detail_url).json()["data"][champ_id]

        # classe Riot officielle
        champ_class = full["tags"][0] if full["tags"] else "Unknown"

        # RangeType
        range_type = "ranged" if full["stats"]["attackrange"] > 250 else "melee"

        dmg_type = class_to_dmg_type(champ_class)

        rows.append([champ_id, champ_class, dmg_type, range_type])

    with open("champ_data.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Champion", "Class", "DmgType", "RangeType"])
        writer.writerows(rows)

    print("champ_data.csv généré avec succès !")

if __name__ == "__main__":
    build_champ_data()
