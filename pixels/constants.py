from urllib.parse import unquote

import asyncpg
from decouple import config
from fastapi import Query


database_url = config("DATABASE_URL")
redis_url = config("REDIS_URL")

client_id = config("CLIENT_ID")
client_secret = config("CLIENT_SECRET")
jwt_secret = config("JWT_SECRET")
# starlette already quotes urls, so the url copied from discord ends up double encoded
auth_uri = config("AUTH_URI", cast=unquote)
base_url = config("BASE_URL", default="https://pixel.pythondiscord.com")
token_url = config("TOKEN_URL", default="https://discord.com/api/oauth2/token")
user_url = config("USER_URL", default="https://discord.com/api/users/@me")

api_base = "https://discord.com/api/v8"
webhook_url = config("WEBHOOK_URL")

width = 160
height = 90

x_query_validator = Query(None, ge=0, lt=width)
y_query_validator = Query(None, ge=0, lt=height)

min_pool_size = config("MIN_POOL_SIZE", cast=int, default=2)
max_pool_size = config("MAX_POOL_SIZE", cast=int, default=5)

log_level = config("LOG_LEVEL", default="INFO")

# Awaited in application startup
DB_POOL = asyncpg.create_pool(
    database_url,
    min_size=min_pool_size,
    max_size=max_pool_size
)

with open("pixels/resources/mods.txt") as f:
    mods = f.read().split()
