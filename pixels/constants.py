import asyncio
from urllib.parse import unquote

import asyncpg
import tomlkit
from decouple import config
from fastapi import Query
from fastapi.templating import Jinja2Templates


class Connections:
    """How to connect to other, internal services."""

    DATABASE_URL = config("DATABASE_URL")
    REDIS_URL = config("REDIS_URL")

    # Awaited in application startup
    DB_POOL = asyncpg.create_pool(
        DATABASE_URL,
        min_size=config("MIN_POOL_SIZE", cast=int, default=2),
        max_size=config("MAX_POOL_SIZE", cast=int, default=5)
    )
    # Result set during application startup
    REDIS_FUTURE = asyncio.Future()


class Discord:
    """Any config required for interaction with Discord."""

    CLIENT_ID = config("CLIENT_ID")
    CLIENT_SECRET = config("CLIENT_SECRET")
    # starlette already quotes urls, so the url copied from discord ends up double encoded
    AUTH_URL = config("AUTH_URL", cast=unquote)
    TOKEN_URL = config("TOKEN_URL", default="https://discord.com/api/oauth2/token")
    USER_URL = config("USER_URL", default="https://discord.com/api/users/@me")
    WEBHOOK_URL = config("WEBHOOK_URL")
    API_BASE = "https://discord.com/api/v8"


class Server:
    """General config for the pixels server."""

    def _get_project_version() -> str:
        with open("pyproject.toml") as pyproject:
            file_contents = pyproject.read()

        return tomlkit.parse(file_contents)["tool"]["poetry"]["version"]

    VERSION = _get_project_version()
    BASE_URL = config("BASE_URL", default="https://pixel.pythondiscord.com")
    JWT_SECRET = config("JWT_SECRET")
    GIT_SHA = config("GIT_SHA")

    LOG_LEVEL = config("LOG_LEVEL", default="INFO")
    SHOW_DEV_ENDPOINTS = "true" != config("PRODUCTION", default="false")

    with open("pixels/resources/mods.txt") as f:
        MODS = f.read().split()

    TEMPLATES = Jinja2Templates(directory="pixels/templates")


class Sizes:
    """The size of the canvas and webhook upscale."""

    # For ease of scaling
    MULTIPLYER = 17
    WIDTH = 16 * MULTIPLYER
    HEIGHT = 9 * MULTIPLYER

    # We want to push a larger image to Discord for visibility
    WEBHOOK_SIZE = (1600, 900)

    X_QUERY_VALIDATOR = Query(None, ge=0, lt=WIDTH)
    Y_QUERY_VALIDATOR = Query(None, ge=0, lt=HEIGHT)


class Ratelimits:
    """The ratelimits and cooldowns for all endpoints."""

    PUT_PIXEL_AMOUNT = 6
    PUT_PIXEL_RATE_LIMIT = 120
    PUT_PIXEL_RATE_COOLDOWN = 180

    GET_PIXEL_AMOUNT = 8
    GET_PIXEL_RATE_LIMIT = 10
    GET_PIXEL_RATE_COOLDOWN = 120

    GET_PIXELS_AMOUNT = 5
    GET_PIXELS_RATE_LIMIT = 10
    GET_PIXELS_RATE_COOLDOWN = 60
