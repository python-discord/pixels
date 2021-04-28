FROM tiangolo/uvicorn-gunicorn-fastapi:python3.8-slim

# There are Pillow (SIMD) requirements.
RUN apt-get -y update \
    && apt-get install -y zlib1g-dev libjpeg-dev gcc \
    && rm -rf /var/lib/apt/lists/*

# Set pip to have cleaner logs and no saved cache
ENV PIP_NO_CACHE_DIR=false \
    PIPENV_HIDE_EMOJIS=1 \
    PIPENV_IGNORE_VIRTUALENVS=1 \
    PIPENV_NOSPIN=1 \
    MODULE_NAME="pixels" \
    MAX_WORKERS=10

# Install pipenv
RUN pip install -U pipenv

# Install project dependencies
COPY Pipfile* ./
RUN pipenv install --system --deploy

# Define Git SHA build argument
ARG git_sha="development"

# Set Git SHA environment variable for Sentry
ENV GIT_SHA=$git_sha

# Copy the source code in last to optimize rebuilding the image
COPY . /app
