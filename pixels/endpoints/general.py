import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from pixels.constants import Ratelimits, Sizes
from pixels.models import GetSize, Message, Pixel
from pixels.utils import auth, ratelimits

log = logging.getLogger(__name__)
router = APIRouter(tags=["Canvas Endpoints"], dependencies=[Depends(auth.JWTBearer())])


@router.get("/size", response_model=GetSize)
async def size(request: Request) -> GetSize:
    """
    Get the size of the Pixels canvas.

    You can use the data this endpoint returns to build some cool scripts
    that can start the ducky uprising on the canvas!

    This endpoint doesn't require any authentication so don't worry
    about the headers usually required.

    #### Example Python Script
    ```py
    import requests

    r = requests.get("https://pixels.pythondiscord.com/size")
    payload = r.json()

    canvas_height = payload["height"]
    canvas_width = payload["width"]

    print(f"We got our canvas size! Height: {canvas_height}, Width: {canvas_width}.")
    ```
    """
    return GetSize(width=Sizes.WIDTH, height=Sizes.HEIGHT)


@router.get("/pixels", response_class=Response, responses={
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
@ratelimits.UserRedis(
    requests=Ratelimits.GET_PIXELS_AMOUNT,
    time_unit=Ratelimits.GET_PIXELS_RATE_LIMIT,
    cooldown=Ratelimits.GET_PIXELS_RATE_COOLDOWN
)
async def pixels(request: Request) -> Response:
    """
    Get the current state of all pixels from the canvas.

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
    r = requests.get("https://pixels.pythondiscord.com/pixels", headers=headers)
    data = r.content

    # have fun processing the returned data...
    ```
    """
    return Response(
        await request.state.canvas.get_pixels(),
        media_type="application/octet-stream"
    )


@router.get("/pixel", response_model=Pixel)
@ratelimits.UserRedis(
    requests=Ratelimits.GET_PIXEL_AMOUNT,
    time_unit=Ratelimits.GET_PIXEL_RATE_LIMIT,
    cooldown=Ratelimits.GET_PIXEL_RATE_COOLDOWN
)
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
        "https://pixels.pythondiscord.com/pixel",
        headers=headers,
        # Note: We're using query parameters to pass the coordinates, not the request body:
        params={
            "x": 87,
            "y": 69
        }
    )

    print("Here's the colour of the pixel:", r.json()["rgb"])
    ```
    """
    if x >= Sizes.WIDTH or y >= Sizes.HEIGHT:
        raise HTTPException(400, "Pixel is out of the canvas bounds.")
    pixel_data = await request.state.canvas.get_pixel(x, y)

    return Pixel(x=x, y=y, rgb=''.join(f"{x:02x}" for x in pixel_data))


@router.put("/pixel", response_model=Message)
@ratelimits.UserRedis(
    requests=Ratelimits.PUT_PIXEL_AMOUNT,
    time_unit=Ratelimits.PUT_PIXEL_RATE_LIMIT,
    cooldown=Ratelimits.PUT_PIXEL_RATE_COOLDOWN
)
async def put_pixel(request: Request, pixel: Pixel) -> Message:
    """
    Override the pixel at the specified coordinate with the specified color.

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
    # Remember, this is a PUT method.
    r = requests.put(
        "https://pixels.pythondiscord.com/pixel",
        # Request body this time:
        json=data,
        headers=headers,
    )
    payload = r.json()

    print(f"We got a message back! {payload['message']}")
    ```
    """
    log.info(f"{request.state.user_id} is setting {pixel.x}, {pixel.y} to {pixel.rgb}")
    await request.state.canvas.set_pixel(request.state.db_conn, pixel.x, pixel.y, pixel.rgb, request.state.user_id)
    return Message(message=f"Set pixel at x={pixel.x},y={pixel.y} to color {pixel.rgb}.")
