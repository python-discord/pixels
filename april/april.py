import re
import secrets
import typing as t

import asyncpg
from asyncpg import Connection
from fastapi import FastAPI, Request, Response
from httpx import AsyncClient
from jose import jwt
from pydantic import BaseModel, validator
from starlette.responses import RedirectResponse

from april import canvas
from april import constants

app = FastAPI()

_RGB_RE = re.compile(r"[0-9a-f-A-F]{6}")


class Pixel(BaseModel):
    """A pixel as used by the api."""

    x: int
    y: int
    rgb: str

    @validator("x")
    def x_must_be_lt_width(cls, x: int) -> int:
        """Ensure that x is within the bounds of the image."""
        if 0 <= x < constants.width:
            return x
        else:
            raise ValueError(f"x must be inside range(0, {constants.width})")

    @validator("y")
    def y_must_be_lt_height(cls, y: int) -> int:
        """Ensure that y is within the bounds of the image."""
        if 0 <= y < constants.height:
            return y
        else:
            raise ValueError(f"y must be inside range(0, {constants.height})")

    @validator("rgb")
    def rgb_must_be_valid_hex(cls, rgb: str) -> str:
        """Ensure rgb is a 6 characters long hexadecimal string."""
        if _RGB_RE.fullmatch(rgb):
            return rgb
        else:
            raise ValueError(
                f"{rgb!r} is not a valid color, "
                "please use the hexadecimal format RRGGBB, "
                "for example FF00ff for purple."
            )


@app.on_event("startup")
async def startup() -> None:
    """Create a asyncpg connection pool on startup."""
    app.state.db_pool = await asyncpg.create_pool(constants.uri, max_size=constants.pool_size)
    async with app.state.db_pool.acquire() as connection:
        await canvas.reload_cache(connection)


@app.middleware("http")
async def get_connection_from_pool(request: Request, callnext: t.Callable) -> Response:
    """Get a connection from the pool for this request."""
    async with app.state.db_pool.acquire() as connection:
        request.state.db_conn = connection
        response = await callnext(request)
    request.state.db_conn = None
    return response


@app.get("/")
async def index(request: Request) -> dict:
    """Basic hello world endpoint."""
    return {"Message": "Hello!"}


@app.get("/get_pixels")
async def get_pixels(request: Request) -> Response:
    """Get the current state of all pixels from the db."""
    return Response(bytes(canvas.cache), media_type="application/octet-stream")


@app.get("/get_token")
async def get_token() -> Response:
    """
    Redirect the user to discord authorization, the flow continues in swap_code.

    Unlike other endpoints, you should open this one in the browser, since it redirects to a discord website.
    """
    return RedirectResponse(url=constants.auth_uri)


def build_oauth_token_request(code: str) -> t.Tuple[dict, dict]:
    """Given a code, return a dict of query params needed to complete the oath flow."""
    query = dict(
        client_id=constants.client_id,
        client_secret=constants.client_secret,
        grant_type="authorization_code",
        code=code,
        redirect_uri=constants.redirect_uri,
        scope="identify",
    )
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    return query, headers


@app.get("/swap_code", include_in_schema=False)
async def swap_code(request: Request) -> Response:
    """
    Create the user given the authorization code.

    This endpoint is only used as a redirect target from discord.
    Perhaps hide it from the docs.
    """
    code = request.query_params["code"]
    async with AsyncClient() as client:
        token_params, token_headers = build_oauth_token_request(code)
        token = (
            await client.post(
                constants.token_url, data=token_params, headers=token_headers
            )
        ).json()
        auth_header = {"Authorization": f"Bearer {token['access_token']}"}
        user = (await client.get(constants.user_url, headers=auth_header)).json()
        token = await reset_user_token(request.state.db_conn, user["id"])

    return RedirectResponse("/show_token?token=" + token)


@app.get("/show_token", include_in_schema=False)
async def show_token(request: Request) -> str:
    """Take a token from URL and show it."""
    return request.query_params["token"]


async def reset_user_token(conn: Connection, user_id: str) -> str:
    """
    Ensure a user exists and create a new token for them.

    If the user already exists, their token is regenerated and the old is invalidated.
    """
    # returns None if the user doesn't exist and false if they aren't banned
    is_banned = await conn.fetchval(
        "SELECT is_banned FROM users WHERE user_id = $1", int(user_id)
    )
    if is_banned:
        return "You are banned"
    # 22 long string
    token_salt = secrets.token_urlsafe(16)
    async with conn.transaction():
        await conn.execute(
            """INSERT INTO users (user_id, key_salt) VALUES ($1, $2)
            ON CONFLICT (user_id) DO UPDATE SET key_salt=$2;""",
            int(user_id),
            token_salt,
        )
    jwt_data = dict(id=user_id, salt=token_salt)
    return jwt.encode(jwt_data, constants.jwt_secret, algorithm="HS256")


@app.post("/set_pixel")
async def set_pixel(request: Request, pixel: Pixel) -> dict:
    """
    Create a new pixel at the specified position with the specified color.

    Override any pixel already at the same position.

    missing Ratelimit
    missing auth, uses a test user at id -1, you will need to create a test user in the users table
    """
    conn = request.state.db_conn
    async with conn.transaction():
        await conn.execute(
            """
            INSERT INTO pixel_history (x, y, rgb, user_id, deleted) VALUES ($1, $2, $3, -1, false);
        """,
            pixel.x,
            pixel.y,
            pixel.rgb,
        )
    canvas.update_cache(**pixel.dict())
    return dict(message=f"added pixel at x={pixel.x},y={pixel.y} of color {pixel.rgb}")
