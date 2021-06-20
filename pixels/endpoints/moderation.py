import asyncio
import io
import json
import logging
import typing as t
from datetime import datetime
from functools import partial

from PIL import Image
from asyncpg import Connection
from fastapi import APIRouter, Depends, Request, Response
from httpx import AsyncClient

from pixels.constants import Discord, Server, Sizes
from pixels.models import Message, ModBan, PixelHistory, User
from pixels.utils import auth

log = logging.getLogger(__name__)
router = APIRouter(
    tags=["Moderation Endpoints"],
    include_in_schema=Server.SHOW_DEV_ENDPOINTS,
    dependencies=[Depends(auth.JWTBearer(is_mod_endpoint=True))]
)


@router.get("/mod", response_model=Message)
async def mod_check(request: Request) -> Message:
    """Check if the authenticated user is a mod."""
    return Message(message="Hello fellow moderator!")


@router.post("/set_mod", response_model=Message)
async def set_mod(request: Request, user: User) -> Message:
    """Make another user a mod."""
    user_id = user.user_id
    conn: Connection = request.state.db_conn
    async with conn.transaction():
        user_state = await conn.fetchrow("SELECT is_mod FROM users WHERE user_id = $1", user_id)
        if user_state is None:
            return Message(message=f"User with user_id {user_id} does not exist.")
        elif user_state['is_mod']:
            return Message(message=f"User with user_id {user_id} is already a mod.")

        await conn.execute("UPDATE users SET is_mod = true WHERE user_id = $1", user_id)
    return Message(message=f"Successfully set user with user_id {user_id} to mod.")


@router.post("/mod_ban", response_model=ModBan)
async def ban_users(request: Request, user_list: list[User]) -> ModBan:
    """Ban users from using the API."""
    conn: Connection = request.state.db_conn
    users = [user.user_id for user in user_list]

    records = await conn.fetch("SELECT * FROM users WHERE user_id=any($1::bigint[])", tuple(users))
    db_users = [record["user_id"] for record in records]

    non_db_users = set(users) - set(db_users)

    async with conn.transaction():
        # Ref:
        # https://magicstack.github.io/asyncpg/current/faq.html#why-do-i-get-postgressyntaxerror-when-using-expression-in-1
        await conn.execute("UPDATE users SET is_banned=TRUE WHERE user_id=any($1::bigint[])", db_users)
        await conn.execute("UPDATE pixel_history SET deleted=TRUE WHERE user_id=any($1::bigint[])", db_users)

    await request.state.canvas.sync_cache(conn, skip_check=True)

    return ModBan(banned=db_users, not_found=list(non_db_users))


@router.get("/pixel_history", response_model=t.Union[PixelHistory, Message])
async def pixel_history(
        request: Request,
        x: int = Sizes.X_QUERY_VALIDATOR,
        y: int = Sizes.Y_QUERY_VALIDATOR
) -> t.Union[PixelHistory, Message]:
    """Get the user who placed a specific pixel given its coordinates."""
    sql = (
        "SELECT user_id::text FROM pixel_history "
        "WHERE x=$1 AND y=$2 AND NOT deleted "
        "ORDER BY pixel_history_id DESC "
        "LIMIT 1"
    )
    record = await request.state.db_conn.fetchrow(sql, x, y)

    if not record:
        return Message(message=f"No user history for pixel ({x}, {y}).")

    return PixelHistory(user_id=record["user_id"])


@router.post("/webhook", response_model=Message)
async def webhook(request: Request) -> Message:
    """Send or update the Discord webhook image."""
    last_message_id = await request.state.redis_pool.get("last-webhook-message")

    now = datetime.now()

    # Generate payload that will be sent in payload_json
    data = {
        "content": "",
        "embeds": [{
            "title": "Pixels State",
            "image": {
                "url": f"attachment://pixels_{now.timestamp()}.png"
            },
            "footer": {
                "text": "Last updated"
            },
            "timestamp": now.isoformat()
        }]
    }

    # Run Pillow stuff in executor because these actions are blocking
    loop = asyncio.get_event_loop()
    image = await loop.run_in_executor(
        None,
        partial(
            Image.frombytes,
            "RGB",
            (Sizes.WIDTH, Sizes.HEIGHT),
            await request.state.canvas.get_pixels()
        )
    )

    # Increase size of image so this looks better in Discord
    image = await loop.run_in_executor(
        None,
        partial(
            image.resize,
            Sizes.WEBHOOK_SIZE,
            Image.NEAREST
        )
    )

    # BytesIO gives a file-like interface for saving
    # and later this is able to get actual content that will be sent.
    file = io.BytesIO()
    await loop.run_in_executor(None, partial(image.save, file, format="PNG"))

    # Name file to pixels_TIMESTAMP.png
    files = {
        "file": (f"pixels_{now.timestamp()}.png", file.getvalue(), "image/png")
    }

    async with AsyncClient(timeout=None) as client:
        # If the last message exists in cache, try to edit it
        if last_message_id is not None:
            data["attachments"] = []
            edit_resp = await client.patch(
                f"{Discord.WEBHOOK_URL}/messages/{int(last_message_id)}",
                data={"payload_json": json.dumps(data)},
                files=files
            )

            if edit_resp.status_code != 200:
                log.warning(f"Non 200 status code from Discord: {edit_resp.status_code}\n{edit_resp.text}")
                last_message_id = None

        # If no message is found in cache, the message is missing or the edit failed, send a new message
        if last_message_id is None:
            # If we are sending a new message, don't specify attachments
            data.pop("attachments", None)
            # Username can only be set when sending a new message
            data["username"] = "Pixels"
            create_resp = (await client.post(
                Discord.WEBHOOK_URL,
                data={"payload_json": json.dumps(data)},
                files=files
            )).json()

            await request.state.redis_pool.set("last-webhook-message", create_resp["id"])

    return Message(message="Webhook posted successfully.")


@router.delete("/token")
async def reset_token(request: Request) -> Response:
    """Reset an API token."""
    await auth.reset_user_token(request.state.db_conn, request.state.user_id)

    return Response(status_code=204)


@router.post("/refresh_cache")
async def refresh_cache(request: Request) -> Response:
    """Force a refresh of the cache via the API."""
    await request.state.canvas.sync_cache(request.state.db_conn, skip_check=True)

    return Response(status_code=204)
