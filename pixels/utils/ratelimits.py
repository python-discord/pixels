from __future__ import annotations

import asyncio
import functools
import hashlib
import inspect
import itertools
import logging
import typing
import uuid
from collections import namedtuple
from dataclasses import dataclass
from time import time

import fastapi
from aioredis import Redis
from fastapi import requests
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response

from pixels import constants

log = logging.getLogger(__name__)


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

    class OnCooldown(BaseException):
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
        self.request_id = itertools.count(0)
        self.state: __BucketBase._STATE = {}

        # Bucket Params
        self.ROUTE_NAME: typing.Optional[str] = None
        self.ROUTES: typing.List[str] = []
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
        from pixels.pixels import app  # Local import to avoid circular dependencies

        route_callback: typing.Callable = args[0]
        if not isinstance(route_callback, typing.Callable):
            raise Exception("First parameter of rate limiter must be a function.")

        function_hash = hashlib.md5(inspect.getsource(route_callback).encode("utf8")).hexdigest()
        if function_hash not in self.ROUTES:
            self.ROUTES.append(function_hash)
            self.ROUTE_NAME = "|".join(self.ROUTES)

        # Add an HEAD endpoint to get rate limit details
        @app.head("/" + route_callback.__name__)
        async def head_endpoint(request: requests.Request) -> Response:
            response = Response()

            request_id = next(self.request_id)
            await self._pre_call(request_id, request)
            await self._init_state(request_id, request)

            if await self._check_cooldown(request_id):
                response.headers.append(
                    "Cooldown-Reset",
                    str(await self._get_remaining_cooldown(request_id))
                )
            else:
                await self.add_headers(response, request_id)
            return response

        # functools.wraps is used here to wrap the endpoint while maintaining the signature
        @functools.wraps(route_callback)
        async def caller(*_args, **_kwargs) -> typing.Union[JSONResponse, Response]:
            # Instantiate request attributes
            request_id = next(self.request_id)

            request: fastapi.Request = _kwargs['request']
            response: typing.Optional[typing.Union[JSONResponse, Response]] = None

            await self._pre_call(*_args, _request_id=request_id, **_kwargs)
            await self._init_state(request_id, request)

            # Try to skip rate limit checks
            bypass = await self.BYPASS() if inspect.iscoroutinefunction(self.BYPASS) else self.BYPASS()
            if not bypass:
                try:
                    await self._increment(request_id)

                except self.OnCooldown as e:
                    response = JSONResponse(
                        content={"message": "You are currently on cooldown. Try again later."},
                        status_code=429
                    )
                    response.headers.append("Cooldown-Reset", str(e.remaining))

                except Exception as e:
                    log.error("Failed to increment rate limiter, falling back to 500.", exc_info=e)
                    response = JSONResponse(
                        content={"message": "Unknown error occurred, please contact staff."},
                        status_code=500
                    )

            # If we don't have a preformatted response because of an error or cooldown,
            # we run the route base function
            if not response:
                result = await route_callback(*_args, **_kwargs)

                if isinstance(result, Response):
                    response = result
                else:
                    clean_result = jsonable_encoder(result)
                    response = JSONResponse(content=clean_result)

                await self.add_headers(response, request_id)

            # Setup post interaction tasks
            state = self.state[request_id]

            tasks = response.background or fastapi.BackgroundTasks()

            for task in state.clean_up_tasks:
                tasks.add_task(task)
            self.clean_up_tasks = []

            # Make sure to remove the request state after everything else has been run
            tasks.add_task(functools.partial(self.state.pop, request_id))

            response.background = tasks
            return response

        return caller

    async def add_headers(self, response: Response, request_id: int) -> None:
        """Add ratelimit headers to the provided request."""
        remaining_requests = await self.get_remaining_requests(request_id)
        request_reset = await self._reset_time(request_id)

        response.headers.append("Requests-Remaining", str(remaining_requests))
        response.headers.append("Requests-Limit", str(self.LIMITS.requests))
        response.headers.append("Requests-Period", str(self.LIMITS.time_unit))
        response.headers.append("Requests-Reset", str(request_reset))

    async def _increment(self, request_id: int) -> None:
        """Reduce remaining quota, and check if a cooldown is needed."""
        if await self._check_cooldown(request_id):
            raise self.OnCooldown(await self._get_remaining_cooldown(request_id))

        await self._record_interaction(request_id)

        if await self.get_remaining_requests(request_id) < 0:
            await self._trigger_cooldown(request_id)
            raise self.OnCooldown(await self._get_remaining_cooldown(request_id))
        else:
            return

    async def get_remaining_requests(self, request_id: int) -> int:
        """Return the number of remaining requests. Logic wrapper for _remaining_getter."""
        state = self.state[request_id]

        # Skip call if it is already known for this request.
        if state.remaining_requests is None:
            state.remaining_requests = await self._calculate_remaining_requests(request_id)
        return state.remaining_requests

    async def _record_interaction(self, request_id: int) -> None:
        """Insert an interaction into the database."""
        raise NotImplementedError()

    async def _calculate_remaining_requests(self, request_id: int) -> int:
        """Calculate the number of remaining requests."""
        raise NotImplementedError()

    async def _trigger_cooldown(self, request_id: int) -> None:
        """Insert cooldown information into the database."""
        raise NotImplementedError()

    async def _check_cooldown(self, request_id: int) -> bool:
        """
        Check the DB for a current cooldown, and check if it can be cleared.

        If the cooldown is cleared, the rate_limits table should also be cleared.
        """
        raise NotImplementedError()

    async def _get_remaining_cooldown(self, request_id: int) -> int:
        """Return the time, in seconds, until a cooldown ends."""
        raise NotImplementedError()

    async def _reset_time(self, request_id: int) -> int:
        """Return the time, in seconds, before getting every interaction back."""
        raise NotImplementedError()


class UserRedis(__BucketBase):
    """A per user request bucket backed by Redis."""

    @dataclass
    class _StateVariables:
        remaining_requests: typing.Optional[int]
        clean_up_tasks: typing.List[typing.Callable]
        user_id: int

    state: typing.Dict[int, _StateVariables]

    redis: typing.Optional[Redis] = None

    async def _pre_call(self, _request_id: int, request: fastapi.Request, *args, **kwargs) -> None:
        request.state.auth.raise_if_failed()

        if not self.redis:
            try:
                self.redis = await constants.REDIS_FUTURE
            except asyncio.InvalidStateError:
                raise ValueError("Redis connection isn't ready yet.")

    async def _init_state(self, request_id: int, request: fastapi.Request) -> None:
        self.state.update({
            request_id: self._StateVariables(
                remaining_requests=None, clean_up_tasks=[], user_id=request.state.auth.user_id
            )
        })

    async def _record_interaction(self, request_id: int) -> None:
        key = f"interaction-{self.ROUTE_NAME}-{self.state[request_id].user_id}"
        log.debug(f"Recorded interaction of user {self.state[request_id].user_id} on {self.ROUTE_NAME}.")

        await self.redis.zadd(key, time() + self.LIMITS.time_unit, str(uuid.uuid4()))
        await self.redis.expire(key, self.LIMITS.time_unit)

    async def _calculate_remaining_requests(self, request_id: int) -> int:
        key = f"interaction-{self.ROUTE_NAME}-{self.state[request_id].user_id}"

        # Cleanup expired entries
        await self.redis.zremrangebyscore(key, max=time())
        remaining = self.LIMITS.requests - int(await self.redis.zcount(key) or 0)

        log.debug(f"Remaining interactions of user {self.state[request_id].user_id} on {self.ROUTE_NAME}: {remaining}.")
        return remaining

    async def _trigger_cooldown(self, request_id: int) -> None:
        key = f"cooldown-{self.ROUTE_NAME}-{self.state[request_id].user_id}"

        log.info(
            f"Triggering cooldown for user {self.state[request_id].user_id} "
            f"on {self.ROUTE_NAME} for {self.LIMITS.cooldown} seconds."
        )
        await self.redis.set(key, 1, expire=self.LIMITS.cooldown)

    async def _check_cooldown(self, request_id: int) -> bool:
        key = f"cooldown-{self.ROUTE_NAME}-{self.state[request_id].user_id}"

        if await self.redis.get(key):
            log.debug(f"User {self.state[request_id].user_id} is already on cooldown.")
            return True
        return False

    async def _get_remaining_cooldown(self, request_id: int) -> int:
        key = f"cooldown-{self.ROUTE_NAME}-{self.state[request_id].user_id}"

        return await self.redis.ttl(key)

    async def _reset_time(self, request_id: int) -> int:
        key = f"interaction-{self.ROUTE_NAME}-{self.state[request_id].user_id}"

        if not (newest_uuid := await self.redis.zrange(key, 0, 0)):
            return -1

        return await self.redis.zscore(key, newest_uuid[0]) - time()
