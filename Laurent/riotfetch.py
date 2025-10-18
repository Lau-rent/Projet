import requests

def get_puuid_from_riot_id(api_key, region, game_name, tag_line):

    headers = {"X-Riot-Token": api_key}
    
    encoded_name = requests.utils.quote(game_name)
    encoded_tag = requests.utils.quote(tag_line)
    url = f"https://{region}.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{encoded_name}/{encoded_tag}"
    print(f"Requesting URL: {url}")
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()
        
        print(f"Game Name: {data['gameName']}#{data['tagLine']}")
        print(f"PUUID: {data['puuid']}")
        return data['puuid']
    
    except requests.exceptions.HTTPError as e:
        if response.status_code == 404:
            print(f"Error: Riot ID '{game_name}#{tag_line}' not found in {region}")
        elif response.status_code == 403:
            print("Error: Invalid or expired API key")
        else:
            print(f"HTTP error: {e}")
        return None
    except Exception as e:
        print(f"Error: {e}")
        return None

if __name__ == "__main__":
    API_KEY = "RGAPI-6bb3f659-7a2b-459b-8d53-3ed8e4d4cd0a"
    REGION = "europe"  # Use 'americas', 'asia', or 'europe' depending on your account
    GAME_NAME = "gogopotato"
    TAG_LINE = "777"
    
    puuid = get_puuid_from_riot_id(API_KEY, REGION, GAME_NAME, TAG_LINE)
    
    if puuid:
        print(f"\n✅ Success! PUUID: {puuid}")
    else:
        print("\n❌ Failed to retrieve PUUID")
