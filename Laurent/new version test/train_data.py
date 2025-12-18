import os
import pandas as pd
from sklearn.preprocessing import OneHotEncoder
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Load champion features
champ_data = pd.read_csv(os.path.join(BASE_DIR, "champ_data.csv"))
champ_data['Champion'] = champ_data['Champion'].str.strip().str.lower()

# Load matchup-specific item data
matchup_folder = os.path.join(BASE_DIR, "matchup_analysis")
matchup_rows = []
for champ_folder in os.listdir(matchup_folder):
    champ_path = os.path.join(matchup_folder, champ_folder)
    if os.path.isdir(champ_path):
        for file in os.listdir(champ_path):
            if file.endswith(".csv"):
                opp_name = file.replace("_item_stats.csv", "").strip().lower()
                df = pd.read_csv(os.path.join(champ_path, file))
                df['Champion'] = champ_folder.strip().lower()
                df['Opponent'] = opp_name
                matchup_rows.append(df)
matchup_data = pd.concat(matchup_rows, ignore_index=True)

# Only keep relevant columns and drop rows with missing values
required_cols = ['Champion', 'Opponent', 'Item Name', 'Pick Rate (%)']
missing_cols = [col for col in required_cols if col not in matchup_data.columns]
if missing_cols:
    raise KeyError(f"Missing columns in matchup_data: {missing_cols}")
matchup_data = matchup_data[required_cols].dropna()

# For each (champion, opponent), get the most picked item
print(matchup_data.head())
targets = matchup_data.sort_values(['Champion', 'Opponent', 'Pick Rate (%)'], ascending=False)\
    .groupby(['Champion', 'Opponent'], as_index=False).first()[['Champion', 'Opponent', 'Item Name']]

# Merge champion features for both champion and opponent
data = targets.merge(champ_data, left_on='Champion', right_on='Champion', how='inner', suffixes=('', '_champ'))
data = data.merge(champ_data, left_on='Opponent', right_on='Champion', how='inner', suffixes=('', '_opp'))

# Prepare features
feature_cols = ['Class', 'Damage_Type', 'Range', 'Class_opp', 'Damage_Type_opp', 'Range_opp']
data = data.rename(columns={
    'Class': 'Class',
    'Damage_Type': 'Damage_Type',
    'Range': 'Range',
    'Class_opp': 'Class_opp',
    'Damage_Type_opp': 'Damage_Type_opp',
    'Range_opp': 'Range_opp'
})

# If columns are not renamed automatically, do it manually
for col in ['Class_opp', 'Damage_Type_opp', 'Range_opp']:
    if col not in data.columns:
        data[col] = data[col.replace('_opp', '') + '_opp']

X = data[feature_cols]
y = data['Item Name']

# One-hot encode categorical features
encoder = OneHotEncoder(sparse=False, handle_unknown="ignore")
X_encoded = encoder.fit_transform(X)

# Train/test split
X_train, X_test, y_train, y_test = train_test_split(
    X_encoded, y, test_size=0.2, random_state=42, stratify=y
)

# Train model
rf = RandomForestClassifier(n_estimators=200, random_state=42)
rf.fit(X_train, y_train)

# Evaluate
y_pred = rf.predict(X_test)
print(classification_report(y_test, y_pred))
