import enum
import logging
import re
import secrets
import traceback
import typing as t

import asyncpg
from asyncpg import Connection
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.security.utils import get_authorization_scheme_param
from fastapi.templating import Jinja2Templates
from httpx import AsyncClient
from jose import JWTError, jwt
from pydantic import BaseModel, validator
from starlette.responses import RedirectResponse

from april import canvas
from april import constants

log = logging.getLogger(__name__)

app = FastAPI()
templates = Jinja2Templates(directory="april/templates")

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

    class Config:
        """Additional settings for this model."""

        schema_extra = {"example": {"x": constants.width // 2, "y": constants.height // 2, "rgb": "00FF00"}}


class AuthState(enum.Enum):
    """Represents possible outcomes of a user attempting to authorize."""

    NO_TOKEN = (
        "There is no token provided, provide one in an Authorization header (case insensitive), "
        "or navigate to /authorize to get a one"
    )
    BAD_HEADER = "The Authorization header does not specify the Bearer scheme."
    INVALID_TOKEN = "The token provided is not a valid token, navigate to /authorize to get a new one."
    BANNED = "You are banned."
    MODERATOR = "This token belongs to a moderator"
    USER = "This token belongs to a regular user"

    def __bool__(self) -> bool:
        """Return whether the authorization was successful."""
        return self == AuthState.USER or self == AuthState.MODERATOR

    def raise_if_failed(self) -> None:
        """Raise an HTTPException if a user isn't authorized."""
        if self:
            return
        raise HTTPException(status_code=401, detail=self.value)

    def raise_unless_mod(self) -> None:
        """Raise an HTTPException if a moderator isn't authorized."""
        if self == AuthState.MODERATOR:
            return
        elif self == AuthState.USER:
            raise HTTPException(status_code=401, detail="This endpoint is limited to moderators")
        self.raise_if_failed()


@app.on_event("startup")
async def startup() -> None:
    """Create a asyncpg connection pool on startup."""
    app.state.db_pool = await asyncpg.create_pool(constants.uri, max_size=constants.pool_size)
    async with app.state.db_pool.acquire() as connection:
        await canvas.reload_cache(connection)


@app.middleware("http")
async def setup_data(request: Request, callnext: t.Callable) -> Response:
    """Get a connection from the pool for this request."""
    async with app.state.db_pool.acquire() as connection:
        request.state.db_conn = connection
        request.state.auth = await authorized(connection, request.headers.get("Authorization"))
        response = await callnext(request)
    request.state.db_conn = None
    return response


def build_oauth_token_request(code: str) -> t.Tuple[dict, dict]:
    """Given a code, return a dict of query params needed to complete the oath flow."""
    query = dict(
        client_id=constants.client_id,
        client_secret=constants.client_secret,
        grant_type="authorization_code",
        code=code,
        redirect_uri=f"{constants.base_url}/callback",
        scope="identify",
    )
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    return query, headers


@app.get("/callback", include_in_schema=False)
async def auth_callback(request: Request) -> Response:
    """
    Create the user given the authorization code and output the token.

    This endpoint is only used as a redirect target from discord.
    """
    code = request.query_params["code"]
    try:
        async with AsyncClient() as client:
            token_params, token_headers = build_oauth_token_request(code)
            token = (await client.post(constants.token_url, data=token_params, headers=token_headers)).json()
            auth_header = {"Authorization": f"Bearer {token['access_token']}"}
            user = (await client.get(constants.user_url, headers=auth_header)).json()
            token = await reset_user_token(request.state.db_conn, user["id"])
    except KeyError:
        # ensure that users don't land on the show_pixel page,
        log.error(traceback.format_exc())
        raise HTTPException(401, "Unknown error while creating token")
    except PermissionError:
        raise HTTPException(401, "You are banned")

    return templates.TemplateResponse("api_token.html", {"request": request, "token": token})


async def authorized(conn: Connection, authorization: t.Optional[str]) -> AuthState:
    """Attempt to authorize the user given a token and a database connection."""
    if authorization is None:
        return AuthState.NO_TOKEN
    scheme, token = get_authorization_scheme_param(authorization)
    if scheme.lower() != "bearer":
        return AuthState.BAD_HEADER
    try:
        token_data = jwt.decode(token, constants.jwt_secret)
    except JWTError:
        return AuthState.INVALID_TOKEN
    else:
        user_id = token_data["id"]
        token_salt = token_data["salt"]
        user_state = await conn.fetchrow(
            "SELECT is_banned, is_mod FROM users WHERE user_id = $1 AND key_salt = $2;", int(user_id), token_salt,
        )
        if user_state is None:
            return AuthState.INVALID_TOKEN
        elif user_state["is_banned"]:
            return AuthState.BANNED
        elif user_state["is_mod"]:
            return AuthState.MODERATOR
        else:
            return AuthState.USER


async def reset_user_token(conn: Connection, user_id: str) -> str:
    """
    Ensure a user exists and create a new token for them.

    If the user already exists, their token is regenerated and the old is invalidated.
    """
    # returns None if the user doesn't exist and false if they aren't banned
    is_banned = await conn.fetchval("SELECT is_banned FROM users WHERE user_id = $1", int(user_id))
    if is_banned:
        raise PermissionError
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


# ENDPOINTS


@app.get("/")
async def index(request: Request) -> dict:
    """Basic hello world endpoint."""
    return {"Message": "Hello!"}


@app.get("/mod")
async def mod_check(request: Request) -> dict:
    """Exmaple of a mod check endpoint."""
    request.state.auth.raise_unless_mod()
    return {"Message": "Hello fellow moderator!"}


@app.get("/authorize")
async def authorize() -> Response:
    """
    Redirect the user to discord authorization, the flow continues in /callback.

    Unlike other endpoints, you should open this one in the browser, since it redirects to a discord website.
    """
    return RedirectResponse(url=constants.auth_uri)


@app.get("/get_pixels")
async def get_pixels(request: Request) -> Response:
    """
    Get the current state of all pixels from the db.

    Requires a valid token in an Authorization header.
    """
    request.state.auth.raise_if_failed()
    return Response(bytes(canvas.cache), media_type="application/octet-stream")


@app.post("/set_pixel")
async def set_pixel(request: Request, pixel: Pixel) -> dict:
    """
    Create a new pixel at the specified position with the specified color.

    Override any pixel already at the same position.

    Requires a valid token in an Authorization header.

    missing Ratelimit
    """
    request.state.auth.raise_if_failed()
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
