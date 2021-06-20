import logging

from fastapi import APIRouter, Request

from pixels.constants import Sizes
from pixels.models import GetSize

log = logging.getLogger(__name__)
router = APIRouter(tags=["Canvas Endpoints"])


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
