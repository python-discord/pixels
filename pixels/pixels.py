import asyncio
import logging
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
from starlette.responses import HTMLResponse, RedirectResponse

from pixels import canvas, constants
from pixels.models import AuthResult, AuthState, Pixel, User
from pixels.utils import docs, ratelimits

log = logging.getLogger(__name__)

tags_metadata = [
    {
        "name": "Getting Started",
        "description": docs.get_doc("getting_started"),
    },
    {
        "name": "Rate Limits",
        "description": docs.get_doc("rate_limits"),
    },
]

app = FastAPI(
    title="Pixels API",
    description=docs.get_doc("welcome"),
    version="0.0.1",
    openapi_tags=tags_metadata,
    docs_url=None,
    redoc_url=None,
)
templates = Jinja2Templates(directory="pixels/templates")

auth_s = URLSafeSerializer(secrets.token_hex(16))


@app.on_event("startup")
async def startup() -> None:
    """Create a asyncpg connection pool on startup and setup logging."""
    # Setup logging
    format_string = "[%(asctime)s] [%(process)d] [%(levelname)s] %(name)s - %(message)s"
    date_format_string = "%Y-%m-%d %H:%M:%S %z"
    logging.basicConfig(
        format=format_string,
        datefmt=date_format_string,
        level=getattr(logging, constants.log_level.upper())
    )

    # Init DB and Redis Connections
    await constants.DB_POOL
    await constants.REDIS_POOL

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
@app.get("/", tags=["General Endpoints"])
async def docs() -> HTMLResponse:
    """Return the API docs."""
    template = templates.get_template("docs.html")
    return HTMLResponse(template.render())


@app.get("/mod", tags=["Moderation Endpoints"])
async def mod_check(request: Request) -> dict:
    """Check if the authenticated user is a mod."""
    request.state.auth.raise_unless_mod()
    return {"Message": "Hello fellow moderator!"}


@app.post("/set_mod", tags=["Moderation Endpoints"])
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


@app.post("/mod_ban", tags=["Moderation Endpoints"])
async def ban_users(request: Request, user_list: t.List[User]) -> dict:
    """Ban users from using the API."""
    request.state.auth.raise_unless_mod()

    conn = request.state.db_conn
    users = [user.user_id for user in user_list]

    # Should be fetched from cache whenever it is implemented.
    sql = "SELECT * FROM users WHERE user_id=any($1::bigint[])"
    records = await conn.fetch(sql, tuple(users))
    db_users = [record["user_id"] for record in records]

    non_db_users = set(users)-set(db_users)

    # Ref:
    # https://magicstack.github.io/asyncpg/current/faq.html#why-do-i-get-postgressyntaxerror-when-using-expression-in-1
    sql = "UPDATE users SET is_banned=TRUE where user_id=any($1::bigint[])"

    await conn.execute(
        sql, db_users
    )

    resp = {"Banned": db_users}
    if non_db_users:
        resp["Not Found"] = non_db_users

    return resp


@app.get("/pixel_history", tags=["Moderation Endpoints"])
async def pixel_history(
        request: Request,
        x: int = constants.x_query_validator,
        y: int = constants.y_query_validator
) -> dict:
    """GET the user who edited the pixel with the given co-ordinates."""
    request.state.auth.raise_unless_mod()

    conn = request.state.db_conn

    sql = """
    select user_id
    from pixel_history
    where x=$1
    and y=$2
    and not deleted
    order by pixel_history_id desc
    limit 1
    """
    record = await conn.fetchrow(sql, x, y)

    if not record:
        return {"Message": f"No user history for pixel ({x}, {y})"}

    user_id = record["user_id"]

    return {
        "user_id": user_id
    }


@app.get("/authorize", tags=["Authorization Endpoints"])
async def authorize() -> Response:
    """
    Redirect the user to discord authorization, the flow continues in /callback.

    Unlike other endpoints, you should open this one in the browser, since it redirects to a discord website.
    """
    return RedirectResponse(url=constants.auth_uri)


@app.get("/get_size", tags=["Canvas Endpoints"])
async def get_size(request: Request) -> dict:
    """Get the size of the pixels canvas."""
    return dict(width=constants.width, height=constants.height)


@app.get("/get_pixels", tags=["Canvas Endpoints"])
async def get_pixels(request: Request) -> Response:
    """
    Get the current state of all pixels from the db.

    Requires a valid token in an Authorization header.
    """
    request.state.auth.raise_if_failed()
    return Response(bytes(canvas.cache), media_type="application/octet-stream")


@app.post("/set_pixel", tags=["Canvas Endpoints"])
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
