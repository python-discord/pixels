import logging
import secrets
from datetime import datetime, timedelta, timezone

from asyncpg import Connection, Record
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

        expired = int(token_data["expiration"]) < datetime.now(timezone.utc).timestamp()
        if user_state is None or user_state["key_salt"] != token_data["salt"] or expired:
            raise HTTPException(status_code=403, detail=AuthState.INVALID_TOKEN.value)
        elif token_data["grant_type"] != "refresh_token":
            raise HTTPException(status_code=403, detail=AuthState.WRONG_TOKEN)
        elif user_state["is_banned"]:
            raise HTTPException(status_code=403, detail=AuthState.BANNED.value)
        elif self.is_mod_endpoint and not user_state["is_mod"]:
            raise HTTPException(status_code=403, detail=AuthState.NEEDS_MODERATOR.value)

        request.state.user_id = int(token_data["id"])
        return credentials


async def reset_user_token(conn: Connection, user_id: str) -> tuple[str, Record]:
    """
    Ensure a user exists and create a new token for them.

    If the user already exists, their token is regenerated and the old is invalidated.
    This function returns the new refresh token, as well as the new row in the database.
    By returning the new row an extra database call can be skipped when generating
    access tokens. For most uses this can ignored.
    """
    # Returns None if the user doesn't exist and false if they aren't banned
    is_banned = await conn.fetchval("SELECT is_banned FROM users WHERE user_id = $1", int(user_id))
    if is_banned:
        raise PermissionError
    # 22 character long string
    token_salt = secrets.token_urlsafe(16)
    is_mod = user_id in Server.MODS

    row = await conn.fetchrow(
        "INSERT INTO users (user_id, key_salt, is_mod) "
        "VALUES ($1, $2, $3) "
        "ON CONFLICT (user_id) DO UPDATE SET key_salt=$2 "
        "RETURNING *",
        int(user_id),
        token_salt,
        is_mod,
    )

    # Refresh tokens don't expire automatically, but when a request to
    # renew an access token is made and this timestamp has passed the refresh
    # token will be reset. The new token is then returned for the user to
    # replace locally.
    expiration = datetime.now(timezone.utc) + timedelta(seconds=Authorization.REFRESH_EXPIRES_IN)
    token = jwt.encode(
        {
            "id": user_id,
            "grant_type": "authorization_code",
            "expiration": expiration.timestamp(),
            "salt": token_salt
        },
        Server.JWT_SECRET,
        algorithm="HS256"
    )
    return token, row


async def generate_access_token(conn: Connection, refresh_token: str) -> tuple[str, str]:
    """
    Generate a new access token for a user from its refresh token.

    This does not invalidate the old access token, rather it only generates a new
    access token with a newer `expiration` field. That is unless the refresh
    token used hasn't expired, in which case it will be reset and the old access
    token will no longer work because the salt has changed.

    This function returns the new access token and a potentially new refresh token.
    """
    try:
        token_data = jwt.decode(refresh_token, Server.JWT_SECRET)
    except JWTError:
        raise HTTPException(status_code=403, detail=AuthState.INVALID_TOKEN.value)

    row = await conn.fetchrow(
        "SELECT is_banned, user_id, key_salt FROM users WHERE user_id = $1", int(token_data["id"])
    )
    if row['is_banned']:
        raise PermissionError
    elif row['key_salt'] != token_data["salt"]:
        raise HTTPException(status_code=403, detail=AuthState.INVALID_TOKEN.value)

    if int(token_data["expiration"]) < datetime.now(timezone.utc).timestamp():
        # Time to renew the refresh token
        refresh_token, row = await reset_user_token(conn, row['user_id'])

    expiration = datetime.now(timezone.utc) + timedelta(seconds=Authorization.ACCESS_EXPIRES_IN)
    token = jwt.encode(
        {
            "id": token_data["id"],
            "grant_type": "refresh_token",
            "expiration": expiration.timestamp(),
            "salt": row['key_salt']
        },
        Server.JWT_SECRET,
        algorithm="HS256"
    )
    return token, refresh_token
