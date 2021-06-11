import asyncio
from urllib.parse import unquote

import asyncpg
from decouple import config
from fastapi import Query
from fastapi.templating import Jinja2Templates


class Connections:
    """How to connect to other, internal services."""

    database_url = config("DATABASE_URL")
    redis_url = config("REDIS_URL")

    min_pool_size = config("MIN_POOL_SIZE", cast=int, default=2)
    max_pool_size = config("MAX_POOL_SIZE", cast=int, default=5)

    # Awaited in application startup
    DB_POOL = asyncpg.create_pool(
        database_url,
        min_size=min_pool_size,
        max_size=max_pool_size
    )
    # Result set during application startup
    REDIS_FUTURE = asyncio.Future()


class Discord:
    """Any config required for interaction with Discord."""

    client_id = config("CLIENT_ID")
    client_secret = config("CLIENT_SECRET")
    # starlette already quotes urls, so the url copied from discord ends up double encoded
    auth_uri = config("AUTH_URI", cast=unquote)
    token_url = config("TOKEN_URL", default="https://discord.com/api/oauth2/token")
    user_url = config("USER_URL", default="https://discord.com/api/users/@me")

    api_base = "https://discord.com/api/v8"
    webhook_url = config("WEBHOOK_URL")


class Server:
    """General config for the pixels server."""

    base_url = config("BASE_URL", default="https://pixel.pythondiscord.com")
    jwt_secret = config("JWT_SECRET")
    git_sha = config("GIT_SHA")

    log_level = config("LOG_LEVEL", default="INFO")
    prod_hide = "true" != config("PRODUCTION", default="false")

    with open("pixels/resources/mods.txt") as f:
        mods = f.read().split()

    templates = Jinja2Templates(directory="pixels/templates")


class Sizes:
    """The size of the canvas and webhook upscale."""

    # For ease of scaling
    mutliplyer = 17
    width = 16 * mutliplyer
    height = 9 * mutliplyer

    # We want to push a larger image to Discord for visibility
    webhook_size = (1600, 900)

    x_query_validator = Query(None, ge=0, lt=width)
    y_query_validator = Query(None, ge=0, lt=height)


class Ratelimits:
    """The ratelimits and cooldowns for all endpoints."""

    PUT_PIXEL_AMOUNT = 6
    PUT_PIXEL_RATE_LIMIT = 120
    PUT_PIXEL_RATE_COOLDOWN = 180
