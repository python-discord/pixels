import requests
from PIL import Image
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


def set_to_mod(user_id: int) -> dict:
    """Makes the given `user_id` a mod."""
    r = requests.post(
        f"{base_url}/set_mod",
        headers=HEADERS,
        json={"user_id": user_id}
    )
    return r.json()


def show_image() -> None:
    """Gets the current image it displays it on screen."""
    a = requests.get(base_url+'/get_pixels', headers=dict(Authorization='Bearer ' + api_token))
    a.raise_for_status()
    Image.frombytes('RGB', (160, 90), a.content).save('2.png')


show_image()
