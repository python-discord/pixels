import enum
import re
import typing as t

from fastapi import HTTPException
from pydantic import BaseModel, validator

from pixels import constants

_RGB_RE = re.compile(r"[0-9a-fA-F]{6}")


class Pixel(BaseModel):
    """A pixel as used by the api."""

    x: int
    y: int
    rgb: str

    @validator("x")
    def x_must_be_lt_width(cls, x: int) -> int:
        """Ensure that x is within the bounds of the image."""
        if 0 <= x < constants.width:
            return x
        else:
            raise ValueError(f"x must be inside range(0, {constants.width})")

    @validator("y")
    def y_must_be_lt_height(cls, y: int) -> int:
        """Ensure that y is within the bounds of the image."""
        if 0 <= y < constants.height:
            return y
        else:
            raise ValueError(f"y must be inside range(0, {constants.height})")

    @validator("rgb")
    def rgb_must_be_valid_hex(cls, rgb: str) -> str:
        """Ensure rgb is a 6 characters long hexadecimal string."""
        if _RGB_RE.fullmatch(rgb):
            return rgb
        else:
            raise ValueError(
                f"{rgb!r} is not a valid color, "
                "please use the hexadecimal format RRGGBB, "
                "for example FF00ff for purple."
            )

    class Config:
        """Additional settings for this model."""

        schema_extra = {"example": {"x": constants.width // 2, "y": constants.height // 2, "rgb": "00FF00"}}


class User(BaseModel):
    """A user as used by the API."""

    user_id: int

    @validator("user_id")
    def user_id_must_be_snowflake(cls, user_id: int) -> int:
        """Ensure the user_id is a valid twitter snowflake."""
        if user_id.bit_length() <= 63:
            return user_id
        else:
            raise ValueError("user_id must fit within a 64 bit int.")


class AuthState(enum.Enum):
    """Represents possible outcomes of a user attempting to authorize."""

    NO_TOKEN = (
        "There is no token provided, provide one in an Authorization header in the format 'Bearer {your token here}'"
        "or navigate to /authorize to get one"
    )
    BAD_HEADER = "The Authorization header does not specify the Bearer scheme."
    INVALID_TOKEN = "The token provided is not a valid token, navigate to /authorize to get a new one."
    BANNED = "You are banned."
    MODERATOR = "This token belongs to a moderator"
    USER = "This token belongs to a regular user"

    def __bool__(self) -> bool:
        """Return whether the authorization was successful."""
        return self == AuthState.USER or self == AuthState.MODERATOR

    def raise_if_failed(self) -> None:
        """Raise an HTTPException if a user isn't authorized."""
        if self:
            return
        raise HTTPException(status_code=401, detail=self.value)

    def raise_unless_mod(self) -> None:
        """Raise an HTTPException if a moderator isn't authorized."""
        if self == AuthState.MODERATOR:
            return
        elif self == AuthState.USER:
            raise HTTPException(status_code=401, detail="This endpoint is limited to moderators")
        self.raise_if_failed()


class AuthResult(t.NamedTuple):
    """The possible outcomes of authorization with the user id."""

    state: AuthState
    user_id: t.Optional[int]

    def __bool__(self) -> bool:
        """Return whether the authorization was successful."""
        return bool(self.state)

    def raise_if_failed(self) -> None:
        """Raise an HTTPException if a user isn't authorized."""
        self.state.raise_if_failed()

    def raise_unless_mod(self) -> None:
        """Raise an HTTPException if a moderator isn't authorized."""
        self.state.raise_unless_mod()


class Message(BaseModel):
    """An API response message."""

    message: str


class ModBan(BaseModel):
    """Users who were banned from the API, or were not found."""

    banned: t.List[int]
    not_found: t.List[int]


class PixelHistory(BaseModel):
    """Pixel history for a canvas pixel."""

    user_id: int


class GetSize(BaseModel):
    """The size of the pixels canvas."""

    width: int
    height: int
