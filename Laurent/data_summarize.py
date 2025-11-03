import pandas as pd
df = pd.read_csv("matches_item_purchases.csv")
summary = (
    df.groupby("itemId")
      .size()
      .sort_values(ascending=False)
)
print(summary.head(50))
import pandas as pd
import requests

# Your frequency data
freq = pd.Series(summary.head(50))

# Load DDragon item data
version = "14.20.1"  # change to current patch if needed
url = f"https://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/item.json"
data = requests.get(url).json()["data"]

# Create mapping
id_to_name = {int(k): v["name"] for k, v in data.items()}

# Build dataframe
df = freq.reset_index()
df.columns = ["itemId", "count"]
df["itemName"] = df["itemId"].map(id_to_name)
df = df[["itemName", "itemId", "count"]].sort_values("count", ascending=False)

print(df)
