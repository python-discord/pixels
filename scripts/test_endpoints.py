import requests
from decouple import config

api_token = config("API_TOKEN")
base_url = config("BASE_URL", default="https://pixel.pythondiscord.com")

HEADERS = {
    "Authorization": f"Bearer {api_token}"
}


def check_if_mod() -> dict:
    """Calls the `/mod` endpoint and returns the response."""
    r = requests.get(f"{base_url}/mod", headers=HEADERS)
    return r.json()


print(check_if_mod())
