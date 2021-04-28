Tate limiting functionality.

The following buckets are implemented:
- Per User
- Per Mod User
- Global (Applies the limit to all usages of the route, regardless of source)
- Multi Route support (the bucket is shared between all uses of the bucket instance

## Examples:
Here are examples of all the buckets in action:

User/Mod User
```py
# Limit requests to 5 requests per 10 seconds per user, with a 20-second timeout if the limit is exceeded.

@app.get("/")
@ratelimits.User(requests=5, time_unit=10, cooldown=20)
async def index(request: Request) -> dict:
    """Basic hello world endpoint."""
    return {"Message": "Hello!"}
```

Global
```py
# Limit requests to 5 requests per 10 seconds for all users, with a 20-second timeout if the limit is exceeded.
# Requests that return 4xx codes are not counted in the rate limit thanks to the `count_failed_requests` flag.

@app.get("/")
@ratelimits.Global(requests=5, time_unit=10, cooldown=20, count_failed_requests=False)
async def index(request: Request) -> dict:
    """Basic hello world endpoint."""
    return {"Message": "Hello!"}
```

Multi Route
```py
# Limit requests to 5 requests per 10 seconds for all users, with a 20-second timeout if the limit is exceeded.
# Handle the "/" and "/mod" routes under one bucket.
limiter = ratelimits.Global(requests=5, time_unit=10, cooldown=20)

@app.get("/")
@limiter
async def index(request: Request) -> dict:
    """Basic hello world endpoint."""
    return {"Message": "Hello!"}

@app.get("/mod")
@limiter
async def index(request: Request) -> dict:
    """Basic hello world endpoint."""
    return {"Message": "Hello!"}
```

## Specifications
Ratelimits use two database tables:
- Ratelimits - Used to keep a rolling record of requests
- Cooldowns - Used as a quick check that blocks further processing for users that are on a timeout

Note: User endpoints handle authentication
Note: Mutli route logic is all handled by the base bucket, other buckets don't have to worry about that logic.

The buckets were designed with extensibility in mind. You can create your own buckets by filling in a couple functions, and writing a few SQL queries. See Global bucket for an example. They are also designed to be highly modifiable with minimal effort. See User buckets for example.

The interface for the buckets is thoroughly documented in the docstrings, and aims to be consistent across all buckets.
