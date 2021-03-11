import typing as t

from asyncpg import Connection

from april import constants as c

cache: t.Optional[bytearray] = None


def _empty_cache() -> None:
    for i, _ in enumerate(cache):
        # ensure the default background is white
        cache[i] = 255


def parse_rgb(rgb: str) -> t.Tuple[int, int, int]:
    """
    Convert a hexadecimal string in the form RRGGBB into the 3 channels.

    This function does no input validation, since that is already done in the Pixel model.
    """
    r = rgb[:2]
    g = rgb[2:4]
    b = rgb[4:]
    return int(r, 16), int(g, 16), int(b, 16)


def update_cache(x: int, y: int, rgb: str) -> None:
    """Place a pixel into the cache."""
    colors = parse_rgb(rgb)
    pixel = (y * c.width + x) * 3
    cache[pixel], cache[pixel + 1], cache[pixel + 2] = colors


async def reload_cache(conn: Connection) -> None:
    """Drop the current cache and recompute it from database."""
    _empty_cache()
    async with conn.transaction():
        async for row in conn.cursor("SELECT x, y, rgb FROM current_pixel"):
            update_cache(**row)
