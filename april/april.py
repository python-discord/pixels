import asyncio
import enum
import logging
import re
import secrets
import traceback
import typing as t

from asyncpg import Connection
from fastapi import Cookie, FastAPI, HTTPException, Request, Response
from fastapi.security.utils import get_authorization_scheme_param
from fastapi.templating import Jinja2Templates
from httpx import AsyncClient
from itsdangerous import URLSafeSerializer
from jose import JWTError, jwt
from pydantic import BaseModel, validator
from starlette.responses import RedirectResponse

from april import canvas, constants
from april.utils import ratelimits

log = logging.getLogger(__name__)

app = FastAPI()
templates = Jinja2Templates(directory="april/templates")

auth_s = URLSafeSerializer(secrets.token_hex(16))

_RGB_RE = re.compile(r"[0-9a-fA-F]{6}")


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


class User(BaseModel):
    """A user as used by the API."""

    user_id: int

    @validator("user_id")
    def user_id_must_be_snowflake(cls, user_id: int) -> int:
        """Ensure the user_id is a valid twitter snowflake."""
        if user_id.bit_length() <= 63:
            return user_id
        else:
            raise ValueError("user_id must fit within a 64 bit int.")


class AuthState(enum.Enum):
    """Represents possible outcomes of a user attempting to authorize."""

    NO_TOKEN = (
        "There is no token provided, provide one in an Authorization header in the format 'Bearer {your token here}'"
        "or navigate to /authorize to get one"
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


class AuthResult(t.NamedTuple):
    """The possible outcomes of authorization with the user id."""

    state: AuthState
    user_id: t.Optional[int]

    def __bool__(self) -> bool:
        """Return whether the authorization was successful."""
        return bool(self.state)

    def raise_if_failed(self) -> None:
        """Raise an HTTPException if a user isn't authorized."""
        self.state.raise_if_failed()

    def raise_unless_mod(self) -> None:
        """Raise an HTTPException if a moderator isn't authorized."""
        self.state.raise_unless_mod()


@app.on_event("startup")
async def startup() -> None:
    """Create a asyncpg connection pool on startup."""
    # Init DB Connection
    await constants.DB_POOL

    # Start background tasks
    app.state.rate_cleaner = asyncio.create_task(ratelimits.start_cleaner(constants.DB_POOL))

    async with constants.DB_POOL.acquire() as connection:
        await canvas.reload_cache(connection)


@app.on_event("shutdown")
async def shutdown() -> None:
    """Close down the app."""
    app.state.rate_limit_cleaner.cancel()
    await constants.DB_POOL.close()


@app.middleware("http")
async def setup_data(request: Request, callnext: t.Callable) -> Response:
    """Get a connection from the pool for this request."""
    async with constants.DB_POOL.acquire() as connection:
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

    # Redirect so that a user doesn't refresh the page and spam discord
    token = auth_s.dumps(token)
    redirect = RedirectResponse("/show_token", status_code=303)
    redirect.set_cookie(
        key='token',
        value=token,
        httponly=True,
        max_age=10,
        path='/show_token',
    )
    return redirect


@app.get("/show_token", include_in_schema=False)
async def show_token(request: Request, token: str = Cookie(None)) -> Response:  # noqa: B008
    """Take a token from URL and show it."""
    token = auth_s.loads(token)
    return templates.TemplateResponse("api_token.html", {"request": request, "token": token})


async def authorized(conn: Connection, authorization: t.Optional[str]) -> AuthResult:
    """Attempt to authorize the user given a token and a database connection."""
    if authorization is None:
        return AuthResult(AuthState.NO_TOKEN, None)
    scheme, token = get_authorization_scheme_param(authorization)
    if scheme.lower() != "bearer":
        return AuthResult(AuthState.BAD_HEADER, None)
    try:
        token_data = jwt.decode(token, constants.jwt_secret)
    except JWTError:
        return AuthResult(AuthState.INVALID_TOKEN, None)
    else:
        user_id = token_data["id"]
        token_salt = token_data["salt"]
        user_state = await conn.fetchrow(
            "SELECT is_banned, is_mod FROM users WHERE user_id = $1 AND key_salt = $2;", int(user_id), token_salt,
        )
        if user_state is None:
            return AuthResult(AuthState.INVALID_TOKEN, None)
        elif user_state["is_banned"]:
            return AuthResult(AuthState.BANNED, int(user_id))
        elif user_state["is_mod"]:
            return AuthResult(AuthState.MODERATOR, int(user_id))
        else:
            return AuthResult(AuthState.USER, int(user_id))


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
    is_mod = user_id in constants.mods
    async with conn.transaction():
        await conn.execute(
            """INSERT INTO users (user_id, key_salt, is_mod) VALUES ($1, $2, $3)
            ON CONFLICT (user_id) DO UPDATE SET key_salt=$2, is_mod=$3;""",
            int(user_id),
            token_salt,
            is_mod,
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


@app.post("/set_mod")
async def set_mod(request: Request, user: User) -> dict:
    """Make another user a mod."""
    user_id = user.user_id
    request.state.auth.raise_unless_mod()
    conn = request.state.db_conn
    async with conn.transaction():
        user_state = await conn.fetchrow(
            "SELECT is_mod FROM users WHERE user_id = $1;", user_id,
        )
        if user_state is None:
            return {"Message": f"User with user_id {user_id} does not exist."}
        elif user_state['is_mod']:
            return {"Message": f"User with user_id {user_id} is already a mod."}

        await conn.execute(
            """
            UPDATE users SET is_mod = 1 WHERE user_id = $1;
        """,
            user_id,
        )
    return {"Message": f"Successfully set user with user_id {user_id} to mod"}


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
            INSERT INTO pixel_history (x, y, rgb, user_id, deleted) VALUES ($1, $2, $3, $4, false);
        """,
            pixel.x,
            pixel.y,
            pixel.rgb,
            request.state.auth.user_id
        )
    canvas.update_cache(**pixel.dict())
    return dict(message=f"added pixel at x={pixel.x},y={pixel.y} of color {pixel.rgb}")
