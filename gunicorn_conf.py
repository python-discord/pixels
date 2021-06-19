# This code is sourced from https://github.com/tiangolo/uvicorn-gunicorn-docker
# There isn't a 3.9.5 image yet, so we had to make our own
import json
import multiprocessing
import os

use_max_workers = int(os.getenv("MAX_WORKERS", "0"))
web_concurrency = int(os.getenv("WEB_CONCURRENCY", "0"))
workers_per_core = float(os.getenv("WORKERS_PER_CORE", "1"))
if not web_concurrency:
    web_concurrency = max(int(workers_per_core * multiprocessing.cpu_count()), 2)
    if use_max_workers:
        web_concurrency = min(web_concurrency, use_max_workers)

host = os.getenv("HOST", "0.0.0.0")
port = os.getenv("PORT", "80")
bind = os.getenv("BIND") or f"{host}:{port}"

# Gunicorn config variables
workers = web_concurrency

loglevel = os.getenv("LOG_LEVEL", "info")
errorlog = os.getenv("ERROR_LOG")
accesslog = os.getenv("ACCESS_LOG")

graceful_timeout = int(os.getenv("GRACEFUL_TIMEOUT", "120"))
timeout = int(os.getenv("TIMEOUT", "120"))
keepalive = int(os.getenv("KEEP_ALIVE", "5"))

# For debugging and testing
log_data = {
    "loglevel": loglevel,
    "workers": workers,
    "bind": bind,
    "graceful_timeout": graceful_timeout,
    "timeout": timeout,
    "keepalive": keepalive,
    "errorlog": errorlog,
    "accesslog": accesslog,
    # Additional, non-gunicorn variables
    "workers_per_core": workers_per_core,
    "use_max_workers": use_max_workers,
    "host": host,
    "port": port,
}
print(json.dumps(log_data))
