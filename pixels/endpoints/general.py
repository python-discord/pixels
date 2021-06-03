import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from pixels import constants
from pixels.models import GetSize, Message, Pixel
from pixels.utils import auth, ratelimits

log = logging.getLogger(__name__)
router = APIRouter(tags=["Canvas Endpoints"], dependencies=[Depends(auth.JWTBearer())])


@router.get("/get_size", response_model=GetSize)
async def get_size(request: Request) -> GetSize:
    """
    Get the size of the pixels canvas.

    You can use the data this endpoint returns to build some cool scripts
    that can start the ducky uprising on the canvas!

    This endpoint doesn't require any authentication so dont worry
    about giving any headers.

    #### Example Python Script
    ```py
    import requests

    r = requests.get("https://pixels.pythondiscord.com/get_size")
    payload = r.json()

    canvas_height = payload["height"]
    canvas_width = payload["width"]

    print(f"We got our canvas size! Height: {canvas_height}, Width: {canvas_width}.")
    ```
    """
    return GetSize(width=constants.width, height=constants.height)


@router.get("/get_pixels", response_class=Response, responses={
    200: {
        "description": "Successful Response.",
        "content": {
            "application/octet-stream": {
                "schema": {
                    "type": "application/octet-stream",
                    "format": "binary"
                }
            }
        }
    }
})
@ratelimits.UserRedis(requests=5, time_unit=10, cooldown=60)
async def get_pixels(request: Request) -> Response:
    """
    Get the current state of all pixels from the database.

    This endpoint requires an authentication token.
    See [this page](https://pixels.pythondiscord.com/info/authentication)
    for how to authenticate with the API.

    #### Example Python Script
    ```py
    from dotenv import load_dotenv
    from os import getenv
    import requests

    load_dotenv(".env")

    token = getenv("TOKEN")

    headers = {"Authorization": f"Bearer {token}"}
    r = requests.get("https://pixels.pythondiscord.com/get_pixels", headers=headers)
    data = r.content

    # have fun processing the returned data...
    ```
    """
    # The cast to bytes here is needed by FastAPI ¯\_(ツ)_/¯
    return Response(bytes(await request.state.canvas.get_pixels()),
                    media_type="application/octet-stream")


@router.get("/get_pixel", response_model=Pixel)
@ratelimits.UserRedis(requests=8, time_unit=10, cooldown=120)
async def get_pixel(x: int, y: int, request: Request) -> Pixel:
    """
    Get a single pixel given the x and y coordinates.

    This endpoint requires an authentication token.
    See [this page](https://pixels.pythondiscord.com/info/authentication)
    for how to authenticate with the API.

    #### Example Python Script
    ```py
    from dotenv import load_dotenv
    from os import getenv
    import requests

    load_dotenv(".env")

    token = getenv("TOKEN")

    headers = {"Authorization": f"Bearer {token}"}

    r = requests.get(
        "https://pixels.pythondiscord.com/get_pixel",
        headers=headers,
        params={  # Note: we're using query string parameters to define the coordinates, not the JSON body.
            "x": 87,
            "y": 69
        }
    )

    print("Here's the colour of the pixel:", r.json()["rgb"])
    ```
    """
    if x >= constants.width or y >= constants.height:
        raise HTTPException(400, "Pixel is out of the canvas bounds.")
    pixel_data = await request.state.canvas.get_pixel(x, y)

    return Pixel(x=x, y=y, rgb=''.join(f"{x:02x}" for x in pixel_data))


@router.post("/set_pixel", response_model=Message)
@ratelimits.UserRedis(requests=2, time_unit=constants.PIXEL_RATE_LIMIT, cooldown=int(constants.PIXEL_RATE_LIMIT * 1.5))
async def set_pixel(request: Request, pixel: Pixel) -> Message:
    """
    Override the pixel at the specified position with the specified color.

    This endpoint requires an authentication token.
    See [this page](https://pixels.pythondiscord.com/info/authentication)
    for how to authenticate with the API.

    #### Example Python Script
    ```py
    from dotenv import load_dotenv
    from os import getenv
    import requests

    load_dotenv(".env")

    token = getenv("TOKEN")

    headers = {"Authorization": f"Bearer {token}"}
    data = {
      "x": 80,
      "y": 45,
      "rgb": "00FF00"
    }
    r = requests.post(  # remember, this is a POST method not a GET method.
        "https://pixels.pythondiscord.com/set_pixel",
        json=data,
        headers=headers,
    )
    payload = r.json()

    print(f"We got a message back! {payload['message']}")
    ```
    """
    log.info(f"{request.state.user_id} is setting {pixel.x}, {pixel.y} to {pixel.rgb}")
    await request.state.canvas.set_pixel(request.state.db_conn, pixel.x, pixel.y, pixel.rgb, request.state.user_id)
    return Message(message=f"added pixel at x={pixel.x},y={pixel.y} of color {pixel.rgb}")
