from __future__ import annotations

import datetime
import functools
import inspect
import logging
import typing
from collections import namedtuple
from dataclasses import dataclass

import asyncpg
import fastapi
from fastapi import routing

from april import constants
from april.utils import database

log = logging.getLogger(__name__)


async def start_cleaner(db_pool: asyncpg.Pool) -> None:
    """Do periodic checks on the DB, and clean up expired rate limit entries."""
    cleanup_statement = (
        """
            DELETE FROM rate_limits WHERE (expiration < $1);
        """,
        datetime.datetime.now
    )
    failure_message = "Rate limit cleaner failed. Restarting."

    # Run the cleanup every 5 minutes
    await database.periodic_task(db_pool, 5 * 60, failure_message, *cleanup_statement)


class __BucketBase:
    """
    The base class for all rate limit buckets.

    Descendents must at the very least implement logic for:
        _record_interaction, _calculate_remaining_requests, _trigger_cooldown, _check_cooldown, _get_remaining_cooldown

    All other functions are designed to be as malleable as possible, but they can be modified as needed.
    Ideally, avoid changing the constructor, to provide the most consistent interface possible.
    """

    _BYPASS_TYPE = typing.Callable[[], typing.Union[bool, typing.Awaitable[bool]]]

    @dataclass
    class _StateVariables:
        remaining_requests: typing.Optional[int]
        clean_up_tasks: typing.List[typing.Callable]

    _STATE = typing.Dict[int, _StateVariables]

    class RequestTimeout(BaseException):
        """An exception class to provide information on the current timeout."""

        def __init__(self, remaining: float, *args):
            super().__init__(*args)
            self.remaining = remaining

    def __init__(
            self, *,
            requests: int,
            time_unit: int,
            cooldown: int,
            count_failed_requests: bool = True,
            bypass: _BYPASS_TYPE = lambda: False,
    ):
        """
        Bucket constructor. Limits are enforced as `requests` / `time unit`.

        :param requests: The maximum allowed requests for this bucket per `time_unit`.
        :param time_unit: The time unit for requests in seconds.
        :param cooldown: The penalty cooldown in seconds for passing the allowed request limit.
        :param count_failed_requests: Whether to count 4xx return codes in the rate limit. Defaults to True.
        :param bypass: A function that can override the regular rate limit checks.
        """
        # Instance management
        self.request_id = 0
        self.state: __BucketBase._STATE = {}

        # Bucket Params
        self.ROUTE_NAME: typing.Optional[str] = None
        self.ROUTES: typing.List[int] = []
        self.BYPASS = bypass

        _limits_type = namedtuple("LIMITS", "requests, time_unit, cooldown")
        self.LIMITS: _limits_type = _limits_type(requests, time_unit, cooldown)

        self.COUNT_FAILED = count_failed_requests

        self._post_init()

    def _post_init(self) -> None:
        """Helper that subclasses can use to avoid modifying init arguments."""
        return

    async def _pre_call(self, _request_id: int, request: fastapi.Request, *args, **kwargs) -> None:
        """Helper that subclasses can use to modify the instance before the rate limiting is run."""
        return

    async def _init_state(self, request_id: int, request: fastapi.Request) -> None:
        """Initialize the state for this request."""
        self.state.update({request_id: self._StateVariables(remaining_requests=None, clean_up_tasks=[])})

    def __call__(self, *args):
        """Wrap the route in a custom caller, and pass it to the route manager."""
        func: typing.Callable = args[0]
        if not isinstance(func, typing.Callable):
            raise Exception("First parameter of rate limiter must be a function.")

        if id(func) not in self.ROUTES:
            self.ROUTES.append(id(func))
            self.ROUTE_NAME = "|".join([str(route) for route in self.ROUTES])

        # functools.wraps is used here to wrap the endpoint while maintaining the signature
        @functools.wraps(func)
        async def caller(*_args, **_kwargs) -> fastapi.Response:
            # Instantiate request attributes
            request_id = self.request_id
            self.request_id += 1

            request: fastapi.Request = _kwargs.get("request")
            response: typing.Optional[fastapi.Response] = None

            await self._pre_call(*_args, _request_id=request_id, **_kwargs)
            await self._init_state(request_id, request)

            db_conn = request.state.db_conn

            # Try to skip rate limit checks
            bypass = await self.BYPASS() if inspect.iscoroutinefunction(self.BYPASS) else self.BYPASS()
            if not bypass:
                try:
                    await self._increment(request_id, db_conn)

                except self.RequestTimeout as e:
                    response = fastapi.Response("You are currently on cooldown. Try again later.", 429)
                    response.headers.append("X-Remaining-Cooldown", str(e.remaining))

                except Exception as e:
                    log.error("Failed to increment rate limiter, falling back to 429.", exc_info=e)
                    response = fastapi.Response("Unknown error occurred, please contact staff.", 429)

            if not response:
                result = await func(*_args, **_kwargs)
                response = fastapi.Response()

                if isinstance(result, fastapi.Response):
                    response = result
                else:
                    response.content = await routing.serialize_response(response_content=response)

                remaining_requests = await self.get_remaining_requests(request_id, db_conn)

                if self.COUNT_FAILED or str(response.status_code)[0] != "4":
                    # Subtract one to account for this request.
                    remaining_requests -= 1

                response.headers.append("X-Remaining-Requests", str(remaining_requests))

            # Setup post interaction tasks
            state = self.state.get(request_id)

            tasks = response.background or fastapi.BackgroundTasks()
            tasks.add_task(self.record_interaction, request_id=request_id, response_code=response.status_code)

            [tasks.add_task(task) for task in state.clean_up_tasks]
            self.clean_up_tasks = []

            # Make sure to remove the request state after everything else has been run
            tasks.add_task(functools.partial(self.state.pop, request_id))

            response.background = tasks
            return response

        return caller

    async def _increment(self, request_id: int, db_conn: asyncpg.Connection) -> None:
        """Reduce remaining quota, and check if a cooldown is needed."""
        cooldown = await self._check_cooldown(request_id, db_conn)

        if cooldown or await self.get_remaining_requests(request_id, db_conn) <= 0:
            raise self.RequestTimeout(await self._get_remaining_cooldown(request_id, db_conn))
        else:
            return

    async def get_remaining_requests(self, request_id: int, db_conn: asyncpg.Connection) -> int:
        """Return the number of remaining requests. Logic wrapper for _remaining_getter."""
        state = self.state.get(request_id)

        # Skip call if it is already known for this request.
        if state.remaining_requests is None:
            state.remaining_requests = await self._calculate_remaining_requests(request_id, db_conn)
        return state.remaining_requests

    async def record_interaction(self, request_id: int, response_code: int) -> None:
        """Record the current interaction in the database."""
        async with constants.DB_POOL.acquire() as db_conn:
            success = str(response_code)[0] != "4"

            if success or self.COUNT_FAILED:
                remaining = await self.get_remaining_requests(request_id, db_conn) - 1

                # Check if we need to trigger a cooldown
                if remaining <= 0:
                    await self._trigger_cooldown(request_id)

                await self._record_interaction(request_id, db_conn)

    async def _clear_rate_limits(self, request_id: int) -> None:
        """
        Clean the rate limit DB for a specific interaction following a cooldown creation.

        This allows for a cooldown to take priority over the rate limits, and function properly even if
        cooldown is shorter than the rate limit.
        """
        async with constants.DB_POOL.acquire() as db_conn:
            await db_conn.execute(
                """
                    DELETE FROM rate_limits WHERE (route = $1);
                """,
                self.ROUTE_NAME
            )

    async def _record_interaction(self, request_id: int, db_conn: asyncpg.Connection) -> None:
        """Insert an interaction into the database."""
        raise NotImplementedError()

    async def _calculate_remaining_requests(self, request_id: int, db_conn: asyncpg.Connection) -> int:
        """Calculate the number of remaining requests."""
        raise NotImplementedError()

    async def _trigger_cooldown(self, request_id: int) -> None:
        """Insert cooldown information into the database."""
        raise NotImplementedError()

    async def _check_cooldown(self, request_id: int, db_conn: asyncpg.Connection) -> bool:
        """
        Check the DB for a current cooldown, and check if it can be cleared.

        If the cooldown is cleared, the rate_limits table should also be cleared.
        """
        raise NotImplementedError()

    async def _get_remaining_cooldown(self, request_id: int, db_conn: asyncpg.Connection) -> int:
        """Return the time, in seconds, until a cooldown ends."""
        raise NotImplementedError()


class User(__BucketBase):
    """A per user request bucket."""

    @dataclass
    class _StateVariables:
        remaining_requests: typing.Optional[int]
        clean_up_tasks: typing.List[typing.Callable]
        user_id: int

    def _post_init(self) -> None:
        self.state: typing.Dict[int, User._StateVariables] = {}

    async def _pre_call(self, _request_id: int, request: fastapi.Request, *args, **kwargs) -> None:
        request.state.auth.raise_if_failed()

    async def _init_state(self, request_id: int, request: fastapi.Request) -> None:
        """Initialize the state for this request."""
        self.state.update({
            request_id: self._StateVariables(
                remaining_requests=None, clean_up_tasks=[], user_id=request.state.auth.user_id
            )
        })

    async def _clear_rate_limits(self, request_id: int) -> None:
        async with constants.DB_POOL.acquire() as db_conn:
            await db_conn.execute(
                """
                    DELETE FROM rate_limits WHERE (route = $1 AND user_id = $2);
                """,
                self.ROUTE_NAME, self.state.get(request_id).user_id
            )

    async def _record_interaction(self, request_id: int, db_conn: asyncpg.Connection) -> None:
        await db_conn.execute(
            """
                INSERT INTO rate_limits (user_id, route, expiration) VALUES ($1, $2, $3);
            """,
            self.state.get(request_id).user_id,
            self.ROUTE_NAME,
            datetime.datetime.now() + datetime.timedelta(seconds=self.LIMITS.time_unit)
        )

    async def _calculate_remaining_requests(self, request_id: int, db_conn: asyncpg.Connection) -> int:
        remaining = await db_conn.fetch(
            """
                SELECT COUNT(request_id) FROM rate_limits WHERE (user_id = $1 AND route = $2 AND expiration >= $3);
            """,
            self.state.get(request_id).user_id, self.ROUTE_NAME, datetime.datetime.now()
        )

        try:
            return self.LIMITS.requests - remaining[0].get("count")
        except ValueError:
            return 0

    async def _trigger_cooldown(self, request_id: int) -> None:
        async with constants.DB_POOL.acquire() as db_conn:
            if not await self._check_cooldown(request_id, db_conn):
                await db_conn.execute(
                    """
                        INSERT INTO cooldowns (user_id, route, expiration) VALUES ($1, $2, $3);
                    """,
                    self.state.get(request_id).user_id,
                    self.ROUTE_NAME,
                    datetime.datetime.now() + datetime.timedelta(seconds=self.LIMITS.cooldown)
                )

    async def _check_cooldown(self, request_id: int, db_conn: asyncpg.Connection) -> bool:
        remaining = await self._get_remaining_cooldown(request_id, db_conn)

        if remaining > 0:
            return True
        elif remaining == -1:
            return False
        else:
            await db_conn.execute(
                """
                    DELETE FROM cooldowns WHERE (user_id = $1 AND route = $2)
                """,
                self.state.get(request_id).user_id, self.ROUTE_NAME
            )
            await self._clear_rate_limits(request_id)

            return False

    async def _get_remaining_cooldown(self, request_id: int, db_conn: asyncpg.Connection) -> int:
        response = await db_conn.fetch(
            """
                SELECT * FROM cooldowns WHERE (user_id = $1 AND route = $2)
            """,
            self.state.get(request_id).user_id, self.ROUTE_NAME
        )

        if len(response) > 0:
            remaining: datetime.timedelta = response[0].get("expiration") - datetime.datetime.now()
            return int(remaining.total_seconds() // 1) if remaining.total_seconds() >= 0 else 0

        return -1


class ModUser(User):
    """A per user request bucket for mods."""

    async def _pre_call(self, request: fastapi.Request, *args, **kwargs) -> None:
        request.state.auth.raise_unless_mod()


class Global(__BucketBase):
    """A bucket that applies to all usages of a route."""

    async def _record_interaction(self, request_id: int, db_conn: asyncpg.Connection) -> None:
        await db_conn.execute(
            """
                INSERT INTO rate_limits (route, expiration) VALUES ($1, $2);
            """,
            self.ROUTE_NAME, datetime.datetime.now() + datetime.timedelta(seconds=self.LIMITS.time_unit)
        )

    async def _calculate_remaining_requests(self, request_id: int, db_conn: asyncpg.Connection) -> int:
        remaining = await db_conn.fetch(
            """
                SELECT COUNT(request_id) FROM rate_limits WHERE (route = $1 AND expiration >= $2);
            """,
            self.ROUTE_NAME, datetime.datetime.now()
        )

        try:
            return self.LIMITS.requests - remaining[0].get("count")
        except ValueError:
            return 0

    async def _trigger_cooldown(self, request_id: int) -> None:
        async with constants.DB_POOL.acquire() as db_conn:
            if not await self._check_cooldown(request_id, db_conn):
                await db_conn.execute(
                    """
                        INSERT INTO cooldowns (route, expiration) VALUES ($1, $2);
                    """,
                    self.ROUTE_NAME, datetime.datetime.now() + datetime.timedelta(seconds=self.LIMITS.cooldown)
                )

    async def _check_cooldown(self, request_id: int, db_conn: asyncpg.Connection) -> bool:
        remaining = await self._get_remaining_cooldown(request_id, db_conn)

        if remaining > 0:
            return True
        elif remaining == -1:
            return False
        else:
            await db_conn.execute(
                """
                    DELETE FROM cooldowns WHERE (route = $1)
                """,
                self.ROUTE_NAME
            )
            await self._clear_rate_limits(request_id)

            return False

    async def _get_remaining_cooldown(self, request_id: int, db_conn: asyncpg.Connection) -> int:
        response = await db_conn.fetch(
            """
                SELECT * FROM cooldowns WHERE (route = $1)
            """,
            self.ROUTE_NAME
        )

        if len(response) > 0:
            remaining: datetime.timedelta = response[0].get("expiration") - datetime.datetime.now()
            return int(remaining.total_seconds() // 1) if remaining.total_seconds() >= 0 else 0

        return -1
