import colorsys
import math
import random

import click
import requests
from PIL import Image
from decouple import config

api_token = config("API_TOKEN")
base_url = config("BASE_URL", default="https://pixels.pythondiscord.com")

HEADERS = {
    "Authorization": f"Bearer {api_token}"
}


@click.group()
def cli() -> None:
    """The main click group for all sub commands."""
    pass


@cli.command()
def check_if_mod() -> dict:
    """Calls the `/mod` endpoint and returns the response."""
    a = requests.get(f"{base_url}/mod", headers=HEADERS)
    print(f"Response:{a.text}\nHeaders:{a.headers}")
    a.raise_for_status()


@cli.command()
@click.argument("user_id", type=int)
def set_to_mod(user_id: int) -> dict:
    """Makes the given `user_id` a mod."""
    a = requests.post(
        f"{base_url}/set_mod",
        headers=HEADERS,
        json={"user_id": user_id}
    )
    print(f"Response:{a.text}\nHeaders:{a.headers}")
    a.raise_for_status()


@cli.command()
def show_image() -> None:
    """Gets the current image it displays it on screen."""
    a = requests.get(f"{base_url}/get_pixels", headers=HEADERS)
    print(f"Response:{a.text}\nHeaders:{a.headers}")
    a.raise_for_status()
    Image.frombytes('RGB', (160, 90), a.content).save('2.png')


@cli.command()
def do_webhook() -> None:
    """Gets the current image it displays it on screen."""
    a = requests.post(f"{base_url}/webhook", headers=HEADERS)
    print(f"Response:{a.text}\nHeaders:{a.headers}")
    a.raise_for_status()


@cli.command()
@click.option("--x", prompt=True, type=int)
@click.option("--y", prompt=True, type=int)
def set_pixel(x: int, y: int) -> None:
    """Sets the coordinate to a random colour."""
    [r, g, b] = [math.ceil(x * 255) for x in colorsys.hsv_to_rgb(random.random() * 0.089, 0.8, 1)]

    a = requests.post(
        f"{base_url}/set_pixel",
        json={
            "x": x,
            "y": y,
            "rgb": f"{r:02x}{g:02x}{b:02x}"
        },
        headers=HEADERS
    )
    print(f"Response:{a.text}\nHeaders:{a.headers}")
    a.raise_for_status()


@cli.command()
@click.option("--x", prompt=True, type=int)
@click.option("--y", prompt=True, type=int)
def pixel_history(x: int, y: int) -> None:
    """Sets the coordinate to a random colour."""
    a = requests.get(
        f"{base_url}/pixel_history",
        params={
            "x": x,
            "y": y
        },
        headers=HEADERS
    )
    print(f"Response:{a.text}\nHeaders:{a.headers}")
    a.raise_for_status()


if __name__ == "__main__":
    cli()
