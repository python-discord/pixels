import logging
import secrets

from asyncpg import Connection
from fastapi import HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from pixels.constants import Server
from pixels.models import AuthState

log = logging.getLogger(__name__)


class JWTBearer(HTTPBearer):
    """Dependency for routes to enforce JWT auth."""

    def __init__(self, auto_error: bool = True, is_mod_endpoint: bool = False):
        super(JWTBearer, self).__init__(auto_error=auto_error)
        self.is_mod_endpoint = is_mod_endpoint

    async def __call__(self, request: Request):
        """Check if the supplied credentials are valid for this endpoint."""
        credentials: HTTPAuthorizationCredentials = await super(JWTBearer, self).__call__(request)
        credentials = credentials.credentials
        if credentials:
            try:
                token_data = jwt.decode(credentials, Server.JWT_SECRET)
            except JWTError:
                raise HTTPException(status_code=403, detail=AuthState.INVALID_TOKEN.value)
            else:
                user_id = token_data["id"]
                token_salt = token_data["salt"]
                user_state = await request.state.db_conn.fetchrow(
                    "SELECT is_banned, is_mod, key_salt FROM users WHERE user_id = $1;", int(user_id),
                )
                if user_state is None or user_state["key_salt"] != token_salt:
                    raise HTTPException(status_code=403, detail=AuthState.INVALID_TOKEN.value)
                elif user_state["is_banned"]:
                    raise HTTPException(status_code=403, detail=AuthState.BANNED.value)
                elif self.is_mod_endpoint and not user_state["is_mod"]:
                    raise HTTPException(status_code=403, detail=AuthState.NEEDS_MODERATOR.value)
                else:
                    request.state.user_id = int(user_id)
                    return credentials
        else:
            raise HTTPException(status_code=403, detail=AuthState.NO_TOKEN)


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
    return jwt.encode({"id": user_id, "salt": token_salt}, Server.JWT_SECRET, algorithm="HS256")
