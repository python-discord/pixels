import logging
import traceback

from fastapi import APIRouter, Cookie, HTTPException, Request, Response
from httpx import AsyncClient
from starlette.responses import RedirectResponse

from pixels import constants
from pixels.utils import auth

log = logging.getLogger(__name__)
router = APIRouter(include_in_schema=False)


@router.get("/authorize")
async def authorize() -> Response:
    """
    Redirect the user to discord authorization, the flow continues in /callback.

    Unlike other endpoints, you should open this one in the browser, since it redirects to a discord website.
    """
    return RedirectResponse(url=constants.auth_uri)


@router.get("/show_token")
async def show_token(request: Request, token: str = Cookie(None)) -> Response:  # noqa: B008
    """Take a token from URL and show it."""
    template_name = "cookie_disabled.html"
    context = {"request": request}

    if token:
        context["token"] = token
        template_name = "api_token.html"

    return constants.templates.TemplateResponse(template_name, context)


def build_oauth_token_request(code: str) -> tuple[dict, dict]:
    """Given a code, return a dict of query params needed to complete the oath flow."""
    query = dict(
        client_id=constants.client_id,
        client_secret=constants.client_secret,
        grant_type="authorization_code",
        code=code,
        redirect_uri=f"{constants.base_url}/callback",
        scope="identify",
    )
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    return query, headers


@router.get("/callback")
async def auth_callback(request: Request) -> Response:
    """
    Create the user given the authorization code and output the token.

    This endpoint is only used as a redirect target from discord.
    """
    code = request.query_params["code"]
    try:
        async with AsyncClient() as client:
            token_params, token_headers = build_oauth_token_request(code)
            token = (await client.post(constants.token_url, data=token_params, headers=token_headers)).json()
            auth_header = {"Authorization": f"Bearer {token['access_token']}"}
            user = (await client.get(constants.user_url, headers=auth_header)).json()
            token = await auth.reset_user_token(request.state.db_conn, user["id"])
    except KeyError:
        # ensure that users don't land on the show_pixel page,
        log.error(traceback.format_exc())
        raise HTTPException(401, "Unknown error while creating token")
    except PermissionError:
        raise HTTPException(401, "You are banned")

    # Redirect so that a user doesn't refresh the page and spam discord
    redirect = RedirectResponse("/show_token", status_code=303)
    redirect.set_cookie(
        key='token',
        value=token,
        httponly=True,
        max_age=10,
        path='/show_token',
    )
    return redirect
