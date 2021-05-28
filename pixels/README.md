# Technical Documentation

This file documents some interesting parts of the project. If you want to contribute or are just curious, you should give this a read!

## Choosen Stack

We are using the following tools in this app:
- [FastAPI](https://fastapi.tiangolo.com/): Our core framework, providing the API interface.
- [PostgreSQL](https://www.postgresql.org/): Main data storage for our Pixel history and users.
- [Redis](https://redis.io/): Fast cache for the board state and ratelimits.

Our stack is managed with Docker and docker-compose to quickly start up a development setup However, we only deploy the main Python pod in production as we already have both PostgreSQL and Redis instances running in our cluster.

## Caching the Board State

As we would like to be able to go back in time with the board history, we made sure to keep every pixel edit in the database.
To get the most recent pixel edit of each coordinate, we made a [view capable of returning them](https://github.com/python-discord/pixels/blob/main/postgres/init.sql#L32-L43).

That said, this view can get slow very quickly. We added a single Redis entry holding the exact same data as returned by the `/get_pixels` endpoint, and made sure to update it every time a new pixel is set using a Redis [SETRANGE operation](https://redis.io/commands/setrange).

Another problem that arises from this solution is how do we make sure that, if the database is manually changed (for example for pixels have been dropped), how do we know that we need to update the cache?
For that, we have a [`cache_state` singleton](https://github.com/python-discord/pixels/blob/main/postgres/init.sql#L1-L9) in the database, which holds when the data was last modified and when the cache was last updated.
If `last_modified` is ever older than `last_synced`, a synchronisation is triggered.

To prevent us from forgetting to bump `last_modified` every time we make changes, a trigger is setup to call a [function to automatically bump it](https://github.com/python-discord/pixels/blob/main/postgres/init.sql#L45-L54) whenever an operation is done on the `pixel_history` table.

One *last* problem we had to deal with was to not have every worker synchronise the cache at the same time. For that we use the `sync_lock` row as a sort of spin lock.
Any worker that wishes to sync the cache will [run a query](https://github.com/python-discord/pixels/blob/main/pixels/canvas.py#L23-L37) setting the lock (to the current timestamp, more on that later) and returning the previous value.
If the value wasn't previously set, we acquired it. If it *was* set, another worker got there first. We also automatically clear the lock if it has been set for too long, just in case a worker crashed while syncing and never cleared it.

The cache implementation can be found [here](https://github.com/python-discord/pixels/blob/main/pixels/canvas.py).

## Rate Limits

To avoid having one person fill the entire board, we set up rate limits, leveraging Redis to keep it as efficient as possible.
One of the main requirements is that the request count must be removed after a set amount of time.
Redis [TTL functionality](https://redis.io/commands/TTL) is perfect to automatically remove expired requests.

Another requirement is to have a rolling window mechanism, so requesting the same endpoint every X seconds or in burst will result in the same speed. With that in mind, a sorted set is created for each bucket. Each entry contains a random dummy value and its score is set to be the current timestamp plus the rate limit duration.
Before counting entries, we simply remove entries from `-inf` to the current timestamp using a [ZREMBYSCORE](https://redis.io/commands/zremrangebyscore) operation, allowing it to stay O(log n).
