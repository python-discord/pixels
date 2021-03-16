from urllib.parse import unquote

from decouple import config

uri = config("DATABASE_URL")

client_id = config("CLIENT_ID")
client_secret = config("CLIENT_SECRET")
# starlette already quotes urls, so the url copied from discord ends up double encoded
auth_uri = config('AUTH_URI', cast=unquote)

width = 160
height = 90
pool_size = 20
