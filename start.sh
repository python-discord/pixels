#! /usr/bin/env sh

# This code is based from the script in https://github.com/tiangolo/uvicorn-gunicorn-docker
# There isn't a 3.9.5 image yet, so we had to make our own

set -e

export GUNICORN_CONF=/gunicorn_conf.py

# Start Gunicorn
exec gunicorn -k "uvicorn.workers.UvicornWorker" -c "$GUNICORN_CONF" "pixels:app"
