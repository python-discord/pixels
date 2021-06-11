import logging
import typing as t

import aioredis
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import RedirectResponse

from pixels.canvas import Canvas
from pixels.constants import Connections, Server
from pixels.endpoints import authorization, general, moderation
from pixels.utils import ratelimits

log = logging.getLogger(__name__)

app = FastAPI(
    docs_url=None,
    redoc_url=None
)

app.include_router(authorization.router)
app.include_router(general.router)
app.include_router(moderation.router)
app.include_router(ratelimits.router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "HEAD"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory="pixels/static"), name="static")


def custom_openapi() -> dict[str, t.Any]:
    """Creates a custom OpenAPI schema."""
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title="Pixels API",
        description=None,
        version="1.0.0",
        routes=app.routes,
    )
    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi


@app.exception_handler(StarletteHTTPException)
async def my_exception_handler(request: Request, exception: StarletteHTTPException) -> Response:
    """Custom exception handler to render template for 404 error."""
    if exception.status_code == 404:
        return Server.TEMPLATES.TemplateResponse(
            name="not_found.html",
            context={"request": request},
            status_code=exception.status_code
        )
    return JSONResponse(
        status_code=exception.status_code,
        content={"message": exception.detail}
    )


@app.on_event("startup")
async def startup() -> None:
    """Setup logging and create asyncpg and redis connection pools on startup."""
    # Setup logging
    format_string = "[%(asctime)s] [%(process)d] [%(levelname)s] %(name)s - %(message)s"
    date_format_string = "%Y-%m-%d %H:%M:%S %z"
    logging.basicConfig(
        format=format_string,
        datefmt=date_format_string,
        level=getattr(logging, Server.LOG_LEVEL.upper())
    )

    # Init DB and Redis Connections
    await Connections.DB_POOL

    app.state.redis_pool = await aioredis.create_redis_pool(Connections.REDIS_URL)
    Connections.REDIS_FUTURE.set_result(app.state.redis_pool)

    app.state.canvas = Canvas(app.state.redis_pool)
    await app.state.canvas.sync_cache(await Connections.DB_POOL.acquire())


@app.on_event("shutdown")
async def shutdown() -> None:
    """Close down the app."""
    app.state.rate_limit_cleaner.cancel()
    await Connections.DB_POOL.close()


@app.middleware("http")
async def setup_data(request: Request, callnext: t.Callable) -> Response:
    """Get a connection from the pool and a canvas reference for this request."""
    async with Connections.DB_POOL.acquire() as connection:
        request.state.db_conn = connection
        request.state.canvas = app.state.canvas
        request.state.redis_pool = app.state.redis_pool
        response = await callnext(request)
    request.state.db_conn = None
    request.state.canvas = None
    return response


@app.get("/", include_in_schema=False)
async def info(request: Request) -> Response:
    """
    Redirect index page to /info.

    /info is served upstream.
    """
    return RedirectResponse(url="/info", status_code=301)


@app.get("/docs", include_in_schema=False)
async def docs(request: Request) -> Response:
    """Return the API docs."""
    template_name = "docs.html"
    return Server.TEMPLATES.TemplateResponse(template_name, {"request": request})
