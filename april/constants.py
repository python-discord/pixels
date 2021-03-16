from urllib.parse import unquote

from decouple import config

uri = config("DATABASE_URL")

client_id = config("CLIENT_ID")
client_secret = config("CLIENT_SECRET")
# starlette already quotes urls, so the url copied from discord ends up double encoded
auth_uri = config('AUTH_URI', cast=unquote)
redirect_uri = config('REDIRECT_URI')
token_url = config('TOKEN_URL', default='https://discord.com/api/oauth2/token')

width = 160
height = 90
pool_size = 20
