import colorsys
import math
import multiprocessing
import random

import httpx
import requests
from PIL import Image
from decouple import config

api_token = config("API_TOKEN")
base_url = config("BASE_URL", default="https://pixels.pythondiscord.com")

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


def do_webhook() -> None:
    """Gets the current image it displays it on screen."""
    a = requests.post('https://pixels.pythondiscord.com/webhook', headers=dict(Authorization='Bearer ' + api_token))
    a.raise_for_status()


def generate_coordinates() -> list:
    """Generates the list of coordinates to populate."""
    coordinates = []
    for x in range(0, 160):
        for y in range(0, 90):
            coordinates.append((x, y))

    return coordinates


def set_pixel(coordinate: list) -> None:
    """Sets the coordinate to a random colour."""
    [r, g, b] = [math.ceil(x * 255) for x in colorsys.hsv_to_rgb(random.random() * 0.089, 0.8, 1)]

    resp = httpx.post(base_url+"/set_pixel", json={
        "x": coordinate[0],
        "y": coordinate[1],
        "rgb": f"{r:02x}{g:02x}{b:02x}"
    }, headers=HEADERS)
    resp.raise_for_status()
    print(resp.text)


if __name__ == "__main__":
    with multiprocessing.Pool(5) as p:
        p.map(set_pixel, generate_coordinates())
