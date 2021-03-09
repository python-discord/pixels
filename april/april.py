import typing as t

import asyncpg
from fastapi import FastAPI, Request, Response

from april import constants

app = FastAPI()


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
async def index(request: Request) -> Response:
    """Basic hello world endpoint."""
    return {"Message": "Hello!"}


@app.get("/get_pixels")
async def get_pixels(request: Request) -> Response:
    """Get the current state of all pixels from the db."""
    return await request.state.db_conn.fetch(
        """
    SELECT *
    FROM current_pixel
    """
    )
