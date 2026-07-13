import requests
import config

token_response = requests.post(
    "https://accounts.spotify.com/api/token",
    data={
        "grant_type": "client_credentials",
        "client_id": config.SPOTIFY_CLIENT_ID,
        "client_secret": config.SPOTIFY_CLIENT_SECRET
    }
)
print("token request status:", token_response.status_code)
token = token_response.json().get("access_token")

if not token:
    print("could not get token, response:", token_response.json())
else:
    search_response = requests.get(
        "https://api.spotify.com/v1/search",
        headers={"Authorization": f"Bearer {token}"},
        params={"q": "artist:Michael Jackson", "type": "artist", "limit": 1}
    )
    print("search request status:", search_response.status_code)
    print("response:", search_response.json())