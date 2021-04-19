# Pixels!

## The General Idea
An open source, API-driven, collaborative learning tool. Users can colour a pixel by posting data to an API. In doing so, they will learn how to:
 - Read formal API docs,
 - Interact with an API,
 - Correctly handle rate limits & authentication,
 - Render images from raw bytes

## Notion
https://www.notion.so/pythondiscord/2021-April-Experiment-db5b5eb529ff47e096026ae8fedab02e

## How to use the API

Check out [this brief guide](./guide.md) on how to make authenticated API requests to pixels.

### Before release
Before we make pixels generally availible, we have added Discord OAuth to pixels.pythondiscord.com

This doesn't affect making requests to the API, as the gate it only on the root path.

## .env file
See this [document](https://github.com/tiangolo/uvicorn-gunicorn-fastapi-docker#environment-variables) for uvicorn/fastAPI image env vars

Additionally, the project uses these environment variables
```ini
DATABASE_URL=prostgres://<username>:<password>@<db server ip>:<db sever port>/<db name>
CLIENT_ID=<discord app client ID>
CLIENT_SECRET=<discord app client secret>
AUTH_URI=<discord OAuth2 URL>
BASE_URL=<base url for the web server>
# 32 byte = 64 digit hex string
JWT_SECRET=c78f1d852e2d5adefc2bc54ed256c5b0c031df81aef21a1ae1720e7f72c2d39
API_TOKEN=<An api token issued by the project, used by the test script>
```

To setup your discord application go to https://discord.com/developers/applications/ and create a new application.

Under OAuth2 add the redirect `{BASE_URL}/callback`, we only need the `identify` scope.

Use the generatred URL for the `AUTH_URI` env var.
