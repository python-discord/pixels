# Pixels!

## Welcome to Python Discord Pixels!

The core idea of Pixels is to have a collaborative canvas, where users paint pixel by pixel, by POSTing co-ordinates and a colour code to an API.

Our main goal for this project is to focus on it being a learning tool, for users who may not have previous experience with APIs.

With that said however, users of all experience levels are both welcome and encouraged to join in with the event!

This repository holds the source code for the web app running over at [pixels.pythondiscord.com](https://pixels.pythondiscord.com).

## API Documentation

The documentation can be found live [here](https://pixels.pythondiscord.com/info).

If you are part of the Python Discord organisation, you can directly edit it using [this](https://www.notion.so/pythondiscord/Python-Discord-Pixels-99e3058855a94f6cab69853d6e2c355b) Notion page. If you aren't, feel free to [open an issue](https://github.com/python-discord/pixels/issues/new) and we will have a look at it!

## Setting the Project up

This project uses `docker-compose` to setup the stack quickly. Running `docker-compose up` after setting up environment variables will start the development server on http://localhost:8000. As usual, you can navigate to http://localhost:8000/authorize to get a new token.

## Environment Variables

You must use a `.env` file to setup variables.

See this [document](https://github.com/tiangolo/uvicorn-gunicorn-fastapi-docker#environment-variables) for uvicorn/fastAPI image env vars. Additionally, we recommend you to set `LOG_LEVEL` to `debug`.

Additionally, the project uses these environment variables
```ini
# Postgres database URL. Not required when using compose.
DATABASE_URL=postgres://<username>:<password>@<address>:<port>/<database name>
# Redis storage URL. Not required when using compose.
REDIS_URL=redis://<address>:<port>/<db id>?password=<password>
# Discord OAuth variables. See below for how to generate them.
CLIENT_ID=<Discord app client ID>
CLIENT_SECRET=<Discord app client secret>
AUTH_URL=<Discord OAuth2 URL>
# Where the root endpoint can be found.
BASE_URL=http://localhost:8000
# 32 byte (64 digit hex string) secret for encoding tokens. Any value can be used.
JWT_SECRET=c78f1d852e2d5adefc2bc54ed256c5b0c031df81aef21a1ae1720e7f72c2d39
# Used to hide moderation endpoints in Redoc.
PRODUCTION=false
```

To setup your discord application go to https://discord.com/developers/applications/ and create a new application.

Under OAuth2 add the redirect `{BASE_URL}/callback`, we only need the `identify` scope.

Use the generatred URL for the `AUTH_URI` env var.

## Contributing

Any contribution is welcomed! In case of a Pull Request, please make sure that you have an approved issue opened first. See our [Contributing Guidelines](https://pydis.com/contributing.md) for more information.
