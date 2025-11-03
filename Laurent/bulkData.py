import requests, time

API_KEY = "RGAPI-5bff0b95-9db1-42b8-8dec-fd2105261042"
PLATFORM = "euw1"
REGION = "europe"

def riot_get(url):
    r = requests.get(url, headers={"X-Riot-Token": API_KEY})
    if r.status_code == 429:
        time.sleep(2)
        return riot_get(url)
    r.raise_for_status()
    return r.json()

# 1️⃣ Get ranked players
league_entries = []
for page in range(1, 3):  # 2 pages ~400 players
    url = f"https://{PLATFORM}.api.riotgames.com/lol/league/v4/entries/RANKED_SOLO_5x5/PLATINUM/IV?page={page}"
    league_entries += riot_get(url)
    time.sleep(1)

print(f"Fetched {len(league_entries)} ranked Platinum IV players from EUW.")
print(league_entries[0])

# 2️⃣ Get their puuids
puuids = []
for e in league_entries[:50]:  # just first 50 for demo
    sid = e["leagueId"]
    summ = riot_get(f"https://{PLATFORM}.api.riotgames.com/lol/summoner/v4/summoners/{sid}")
    puuids.append(summ["puuid"])
    time.sleep(1)

print(f"Collected {len(puuids)} puuids.")
# 3️⃣ Get match IDs
match_ids = set()
for p in puuids:
    matches = riot_get(f"https://{REGION}.api.riotgames.com/lol/match/v5/matches/by-puuid/{p}/ids?type=ranked&count=5?api_key=<RGAPI-5bff0b95-9db1-42b8-8dec-fd2105261042>")
    match_ids.update(matches)
    if len(match_ids) > 100:
        break
    time.sleep(1)

print(f"Collected {len(match_ids)} unique match IDs from Platinum IV EUW.")
