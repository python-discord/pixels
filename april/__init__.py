import asyncpg

from april import constants

# Awaited in application startup
DB_POOL = asyncpg.create_pool(constants.uri, max_size=constants.pool_size)

from april.april import app  # noqa: E402 I202, F401 Import not at top of file, Unused import
