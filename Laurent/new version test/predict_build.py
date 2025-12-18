import pandas as pd
import joblib

MODEL_PATH = "item_recommender.joblib"
ENCODER_PATH = "role_encoder.joblib"
CHAMP_DATA_PATH = "champ_data.csv"

# Chargement des artefacts
model = joblib.load(MODEL_PATH)
role_encoder = joblib.load(ENCODER_PATH)
champ_data = pd.read_csv(CHAMP_DATA_PATH)

# Le modèle doit avoir stocké la liste des items pendant l'entraînement
item_labels = model.item_labels


def get_champion_info(name):
    row = champ_data[champ_data["champion"] == name]
    if row.empty:
        raise ValueError(f"Champion inconnu : {name}")

    return {
        "role": row["role"].iloc[0],
        "damage_type": row["damage_type"].iloc[0],
        "range": row["range"].iloc[0]
    }


def encode(champ, opponent):
    c = get_champion_info(champ)
    o = get_champion_info(opponent)

    # Conversion damage type
    dmg_map = {"AD": 1, "AP": 2, "Mixed": 3}

    X = pd.DataFrame([{
        "att_role": role_encoder.transform([c["role"]])[0],
        "att_damage": dmg_map.get(c["damage_type"], 3),
        "att_range": c["range"],

        "def_role": role_encoder.transform([o["role"]])[0],
        "def_damage": dmg_map.get(o["damage_type"], 3),
        "def_range": o["range"],
    }])

    return X


def predict_build(champ, opponent):
    X = encode(champ, opponent)
    pred = model.predict(X)[0]

    recommended = [
        item_labels[i]
        for i, flag in enumerate(pred)
        if flag == 1
    ]

    return recommended


if __name__ == "__main__":
    print(predict_build("Aatrox", "Kayn"))
