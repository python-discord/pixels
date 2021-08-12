import logging
import secrets
from datetime import datetime, timedelta, timezone

from asyncpg import Connection
from fastapi import HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from pixels.constants import Authorization, Server
from pixels.models import AuthState

log = logging.getLogger(__name__)


class JWTBearer(HTTPBearer):
    """Dependency for routes to enforce JWT auth."""

    def __init__(self, auto_error: bool = True, is_mod_endpoint: bool = False):
        super().__init__(auto_error=auto_error)
        self.is_mod_endpoint = is_mod_endpoint

    async def __call__(self, request: Request):
        """Check if the supplied credentials are valid for this endpoint."""
        credentials: HTTPAuthorizationCredentials = await super().__call__(request)
        credentials = credentials.credentials
        if not credentials:
            raise HTTPException(status_code=403, detail=AuthState.NO_TOKEN)

        try:
            token_data = jwt.decode(credentials, Server.JWT_SECRET)
        except JWTError:
            raise HTTPException(status_code=403, detail=AuthState.INVALID_TOKEN.value)

        user_state = await request.state.db_conn.fetchrow(
            "SELECT is_banned, is_mod, key_salt FROM users WHERE user_id = $1",
            int(token_data["id"])
        )

        # Handle bad scenarios

        if token_data["grant_type"] != "access_token":
            raise HTTPException(status_code=403, detail=AuthState.WRONG_TOKEN)

        expired = int(token_data["expiration"]) < datetime.now(timezone.utc).timestamp()
        if user_state is None or user_state["key_salt"] != token_data["salt"] or expired:
            raise HTTPException(status_code=403, detail=AuthState.INVALID_TOKEN.value)
        elif user_state["is_banned"]:
            raise HTTPException(status_code=403, detail=AuthState.BANNED.value)
        elif self.is_mod_endpoint and not user_state["is_mod"]:
            raise HTTPException(status_code=403, detail=AuthState.NEEDS_MODERATOR.value)

        request.state.user_id = int(token_data["id"])
        return credentials


async def reset_user_token(conn: Connection, user_id: str) -> str:
    """
    Ensure a user exists and create a new token for them.

    If the user already exists, their token is regenerated and the old is invalidated.
    """
    # Returns None if the user doesn't exist and false if they aren't banned
    is_banned = await conn.fetchval("SELECT is_banned FROM users WHERE user_id = $1", int(user_id))
    if is_banned:
        raise PermissionError
    # 22 character long string
    token_salt = secrets.token_urlsafe(16)
    is_mod = user_id in Server.MODS

    await conn.execute(
        "INSERT INTO users (user_id, key_salt, is_mod) "
        "VALUES ($1, $2, $3) "
        "ON CONFLICT (user_id) DO UPDATE SET key_salt=$2",
        int(user_id),
        token_salt,
        is_mod,
    )
    return jwt.encode(
        {
            "id": user_id,
            "grant_type": "authorization_code",
            "salt": token_salt
        },
        Server.JWT_SECRET,
        algorithm="HS256"
    )


async def generate_access_token(conn: Connection, refresh_token: str) -> str:
    """
    Generate a new access token for a user from its refresh token.

    This does not invalidate the old access token, rather it only generates a new
    access token with a newer `expiration` field.
    """
    try:
        token_data = jwt.decode(refresh_token, Server.JWT_SECRET)
    except JWTError:
        raise HTTPException(status_code=403, detail=AuthState.INVALID_TOKEN.value)

    is_banned, key_salt = await conn.fetchrow(
        "SELECT is_banned, key_salt FROM users WHERE user_id = $1", int(token_data["id"])
    )
    if is_banned:
        raise PermissionError
    elif key_salt != token_data["salt"]:
        raise HTTPException(status_code=403, detail=AuthState.INVALID_TOKEN.value)

    expiration = datetime.now(timezone.utc) + timedelta(seconds=Authorization.EXPIRES_IN)
    return jwt.encode(
        {
            "id": token_data["id"],
            "grant_type": "refresh_token",
            "expiration": expiration.timestamp(),
            "salt": key_salt
        },
        Server.JWT_SECRET,
        algorithm="HS256"
    )
