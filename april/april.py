import typing as t

import asyncpg
from fastapi import FastAPI, Request, Response
from pydantic import BaseModel, validator

from april import constants

app = FastAPI()


class Pixel(BaseModel):
    """
    A pixel as used by the api.

    missing Bounds checking
    """

    x: int
    y: int
    rgb: str

    @classmethod
    @validator("rgb")
    def rgb_must_be_valid_hex(cls, rgb: str) -> str:
        """Ensure rgb is a 6 characters long hexadecimal string."""
        error_msg = (
            f"{rgb!r} is not a valid color, "
            "please use the hexadecimal format RRGGBB, "
            "for example FF00ff for puprle"
        )
        try:
            int(rgb, 16)
        except ValueError:
            raise ValueError(error_msg)
        else:
            if len(rgb) == 6:
                return rgb.upper()
            else:
                raise ValueError(error_msg)


@app.on_event("startup")
async def startup() -> None:
    """Create a asyncpg connection pool on startup."""
    app.state.db_pool = await asyncpg.create_pool(constants.uri)


@app.middleware("http")
async def get_connection_from_pool(request: Request, callnext: t.Callable) -> Response:
    """Get a connection from the pool for this request."""
    async with app.state.db_pool.acquire() as connection:
        request.state.db_conn = connection
        response = await callnext(request)
    request.state.db_conn = None
    return response


@app.get("/")
async def index(request: Request) -> dict:
    """Basic hello world endpoint."""
    return {"Message": "Hello!"}


@app.get("/get_pixels")
async def get_pixels(request: Request) -> list:
    """Get the current state of all pixels from the db."""
    return await request.state.db_conn.fetch(
        """
    SELECT *
    FROM current_pixel
    """
    )


@app.post("/set_pixel")
async def set_pixel(request: Request, pixel: Pixel) -> dict:
    """
    Create a new pixel at the specified position with the specified color.

    Override any pixel already at the same position.

    missing Ratelimit
    missing auth, uses a test user at id -1, you will need to create a test user in the users table
    """
    conn = request.state.db_conn
    async with conn.transaction():
        await conn.execute(
            """
            INSERT INTO pixel_history (x, y, rgb, user_id, deleted) VALUES ($1, $2, $3, -1, false);
        """,
            pixel.x,
            pixel.y,
            pixel.rgb,
        )
    return dict(message=f'added pixel at x={pixel.x},y={pixel.y} of color {pixel.rgb}')
