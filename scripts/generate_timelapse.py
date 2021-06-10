import asyncio
import logging
import os
import typing as t
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from time import perf_counter

import asyncpg
from PIL import Image
from asyncpg import Pool

DB_POOL = asyncpg.create_pool(
    "postgres://pypixels:pypixels@127.0.0.1:5000/pypixels"
)

MAX_WIDTH = 272
MAX_HEIGHT = 153

START_DATE = datetime(2021, 5, 24, 23, 10)
END_DATE = datetime(2021, 6, 10, 21, 13)
INTERVAL_DELTA = timedelta(minutes=1)
FPS = 120

_EXECUTOR = ThreadPoolExecutor(5)

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


def save_image(image_bytes: bytearray, filepath: str) -> None:
    """Renders and saves an image from raw bytes."""
    image = Image.frombytes("RGB", (MAX_WIDTH, MAX_HEIGHT), bytes(image_bytes))
    image = image.resize((1600, 900), Image.NEAREST)
    image.save(filepath, format="png")


async def save_one_snapshot(pool: Pool, time: datetime) -> None:
    """Gets a snapshot of the canvas at the given time."""
    interval_offset = int((time - START_DATE).total_seconds() // INTERVAL_DELTA.seconds)
    file_path = Path(f"timelapse_output/frames/frame{interval_offset}.png")
    if file_path.is_file():
        return

    sql = (
        "SELECT PH.x, PH.y, PH.rgb "
        "FROM ( "
        "   SELECT MAX(pixel_history_id) as pixel_history_id "
        "   FROM pixel_history "
        "   WHERE NOT deleted "
        "   AND created_at < $1 "
        "   GROUP BY x, y "
        ") most_recent_pixels "
        "INNER JOIN pixel_history PH USING (pixel_history_id) "
        "ORDER BY PH.y, PH.x"
    )
    cache = bytearray(MAX_WIDTH * MAX_HEIGHT * 3)
    async with pool.acquire() as conn:
        async with conn.transaction():
            async for record in conn.cursor(sql, time):
                position = record["y"] * MAX_WIDTH + record["x"]
                cache[position * 3:(position + 1) * 3] = bytes.fromhex(record["rgb"])

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(_EXECUTOR, save_image, cache, file_path)


async def get_snapshots() -> None:
    """Fetch snapshots from the db using a connection pool."""
    pool = await DB_POOL
    times = [*datetime_range(START_DATE, END_DATE, INTERVAL_DELTA)]

    batch_size = 100
    total_blocks = (len(times) // batch_size) + 1
    for i in range(total_blocks):
        log.info(f"Running block {i+1} of {total_blocks}")
        await asyncio.gather(*[
            save_one_snapshot(pool, time)
            for time in times[i*100:(i+1)*100]
        ])

Path("timelapse_output/frames").mkdir(parents=True, exist_ok=True)

log.info("Starting DB extract...")

start = perf_counter()
loop = asyncio.get_event_loop()
snapshots = loop.run_until_complete(get_snapshots())

log.info(f"DB extract done. Took {perf_counter()-start:.2f}s")

log.info("Rendering frames to a mp4...")
start = perf_counter()
os.system(
    "ffmpeg "
    "-hide_banner -loglevel error "  # Silence output
    f"-r {FPS} "  # Output FPS
    r"-i ./timelapse_output/frames/frame%01d.png "  # Image source
    "-vcodec libx264 -crf 30 -pix_fmt yuv420p "  # Formats and codecs
    "-y "  # Skip confirm
    "./timelapse_output/timelapse.mp4"  # Output file.
)
log.info(f"MP4 saving done. Took {perf_counter()-start:.2f}s")
