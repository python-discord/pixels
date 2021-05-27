import asyncio
import logging
import typing as t
from dataclasses import dataclass
from datetime import datetime, timedelta
from operator import attrgetter
from time import perf_counter

import asyncpg
from asyncpg import Pool

DB_POOL = asyncpg.create_pool(
    "postgres://pypixels:pypixels@127.0.0.1:5000/pypixels"
)

log = logging.getLogger()
format_string = "[%(asctime)s] [%(process)d] [%(levelname)s] %(name)s - %(message)s"
date_format_string = "%Y-%m-%d %H:%M:%S %z"
logging.basicConfig(
    format=format_string,
    datefmt=date_format_string,
    level=logging.INFO
)


def datetime_range(start: datetime, end: datetime, delta: timedelta) -> t.Generator[datetime, None, None]:
    """A generator for producing a list of datetimes at set intervals."""
    current = start
    while current < end:
        yield current
        current += delta


TIMES = datetime_range(
    datetime(2021, 5, 24, 23, 15),
    datetime(2021, 5, 27, 17),
    timedelta(minutes=5)
)


@dataclass
class Pixel():
    """Defines the attributes of a Pixel."""

    x: int
    y: int
    rgb: str


@dataclass
class Snapshot():
    """Defines the attributes of a Snapshot."""

    time: datetime
    pixels: t.List[Pixel]


async def fetch_one_snapshot(pool: Pool, time: datetime) -> Snapshot:
    """Gets a snapshot of the canvas at the given time."""
    sql = (
        "SELECT PH.x, PH.y, PH.rgb "
        "FROM ( "
        "   SELECT MAX(pixel_history_id) as pixel_history_id "
        "   FROM pixel_history "
        "   WHERE NOT deleted "
        "   AND created_at < $1 "
        "   GROUP BY x, y "
        ") most_recent_pixels "
        "INNER JOIN pixel_history PH USING (pixel_history_id)"
    )
    async with pool.acquire() as conn:
        async with conn.transaction():
            return Snapshot(
                time,
                [
                    Pixel(x, y, rgb)
                    async for x, y, rgb in conn.cursor(sql, time)
                ]
            )


async def get_snapshots() -> t.List[Snapshot]:
    """Fetch snapshots from the db using a connection pool."""
    pool = await DB_POOL
    tasks = [
        fetch_one_snapshot(pool, time)
        for time in TIMES
    ]
    return await asyncio.gather(*tasks)


log.info("Starting DB extract...")

start = perf_counter()
loop = asyncio.get_event_loop()
snapshots = loop.run_until_complete(get_snapshots())

log.info(f"DB extract done. Took {perf_counter()-start:.2f}s")

snapshots = sorted(snapshots, key=attrgetter("time"))

for snapshot in snapshots:
    print(snapshot)
