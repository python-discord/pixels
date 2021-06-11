import asyncio
import logging
from time import time

from aioredis import Redis
from asyncpg import Connection

from pixels.constants import Server, Sizes

log = logging.getLogger(__name__)


# How long before considering that the key is deadlocked and won't be released
KEY_TIMEOUT = 10


class Canvas:
    """Class used for interacting with the canvas."""

    def __init__(self, redis: Redis):
        self.redis = redis

    @staticmethod
    async def _try_acquire_lock(conn: Connection) -> bool:
        """
        Try to acquire the sync lock from the cache state.

        Returns True if the lock has been acquired. The lock functions as a spinlock.
        """
        # We try to set the lock but use a self join to return the previous state.
        previous_record, = await conn.fetch(
            """UPDATE cache_state x
            SET sync_lock = now()
            FROM (SELECT sync_lock FROM cache_state FOR UPDATE) y
            RETURNING y.sync_lock AS previous_state
            """)
        return previous_record["previous_state"] is None

    async def _populate_cache(self, conn: Connection) -> None:
        """Populate the cache and discard old values."""
        start_time = time()

        cache = bytearray(Sizes.width * Sizes.height * 3)

        sql = (
            "SELECT x, y, rgb "
            "FROM current_pixel "
            "WHERE x < $1 "
            "AND y < $2"
        )
        records = await conn.fetch(sql, Sizes.width, Sizes.height)
        for record in records:
            position = record["y"] * Sizes.width + record["x"]
            cache[position * 3:(position + 1) * 3] = bytes.fromhex(record["rgb"])

        await self.redis.set(f"{Server.git_sha}-canvas-cache", cache)

        log.info(f"Cache updated finished! (took {time() - start_time}s)")
        await conn.execute("UPDATE cache_state SET last_synced = now()")

    async def is_cache_out_of_date(self, conn: Connection) -> bool:
        """Return true if the cache can be considered out of date."""
        cache = await self.get_pixels()
        if not cache or len(cache)//3 != Sizes.width*Sizes.height:
            # Canvas size has changed, force a cache refresh
            return True

        record, = await conn.fetch("SELECT last_modified, last_synced FROM cache_state")
        return record["last_modified"] > record["last_synced"]

    async def sync_cache(self, conn: Connection, *, skip_check: bool = False) -> None:
        """
        Make sure that the cache is up-to-date.

        `skip_check` is used when you want to force a canvas refresh, ignoring the
        stored cache state in the db.
        """
        lock_cleared = False

        while skip_check or await self.is_cache_out_of_date(conn):
            log.info("Cache will be updated")

            if await self._try_acquire_lock(conn) or lock_cleared:
                log.info("Lock acquired. Starting synchronisation.")
                lock_cleared = False
                skip_check = False  # Don't infinite loop after refreshing cache.
                try:
                    await self._populate_cache(conn)
                # Use a finally block to make sure that the lock is freed
                finally:
                    await conn.execute("UPDATE cache_state SET sync_lock = NULL")
            else:
                # Another process is already syncing the cache, let's just wait patiently.
                log.info("Lock in use. Waiting for process to be finished")

                while True:
                    record, = await conn.fetch("SELECT sync_lock FROM cache_state")

                    if record["sync_lock"] is None:
                        break

                    # If it has been too long since the lock has been set
                    # we consider it as deadlocked and clear it
                    result = await conn.execute(
                        f"""UPDATE cache_state
                        SET sync_lock = now()
                        WHERE now() - sync_lock > interval '{KEY_TIMEOUT} seconds'"""
                    )
                    if result.split()[1] == "1":
                        log.warning("Lock considered as deadlocked. Clearing it.")
                        await conn.execute("UPDATE cache_state SET sync_lock = now()")
                        lock_cleared = True
                        break

                    await asyncio.sleep(.1)
        else:
            log.debug("Cache is up-to-date")

    async def set_pixel(self, conn: Connection, x: int, y: int, rgb: str, user_id: int) -> None:
        """Set the provided pixel."""
        await self.sync_cache(conn)

        async with conn.transaction():
            # Insert the pixel into the database
            await conn.execute(
                """
                INSERT INTO pixel_history (x, y, rgb, user_id, deleted) VALUES ($1, $2, $3, $4, false);
            """,
                x,
                y,
                rgb,
                user_id
            )

            # Update the cache
            position = (y * Sizes.width + x) * 3
            await self.redis.setrange(f"{Server.git_sha}-canvas-cache", position, bytes.fromhex(rgb))

            await conn.execute("UPDATE cache_state SET last_synced = now()")

    async def get_pixels(self) -> bytearray:
        """Returns the whole board."""
        return await self.redis.get(f"{Server.git_sha}-canvas-cache")

    async def get_pixel(self, x: int, y: int) -> bytearray:
        """Returns a single pixel from the board."""
        position = (y * Sizes.width + x) * 3
        return await self.redis.getrange(f"{Server.git_sha}-canvas-cache", position, position+2)
