import asyncio
import logging
import typing

import asyncpg


async def periodic_task(
        pool: asyncpg.Pool,
        frequency: int,
        failure_message: typing.Optional[str] = None,
        *execute_args: any
) -> None:
    """
    Runs an sql statement every `frequency` seconds. Restarts on failure.

    If a callable or awaitable is passed in args, it is evaluated before
    being passed into execute.
    """
    async def eval_args(args: typing.Tuple[any]) -> typing.List[any]:
        """Helper method to update execute_args."""
        _evaluated_args = []

        for _arg in args:
            if isinstance(_arg, typing.Callable):
                _evaluated_args.append(_arg())
            elif isinstance(_arg, typing.Coroutine):
                _evaluated_args.append(await _arg)
            else:
                _evaluated_args.append(_arg)

        return _evaluated_args

    try:
        async with pool.acquire() as connection:
            connection: asyncpg.Connection
            while True:
                await connection.execute(*await eval_args(execute_args))
                await asyncio.sleep(frequency)

    except asyncio.CancelledError:
        # Program is stopping
        return

    except Exception as e:
        logging.getLogger(__name__).error(failure_message, exc_info=e)

        # Sleep a little before retrying to avoid spam with infinite loops
        await asyncio.sleep(60)
        await periodic_task(pool, frequency, failure_message, *execute_args)
