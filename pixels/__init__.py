import logging

from pixels.pixels import app  # noqa: F401 Unused import


ENDPOINTS_TO_FILTER_OUT = (
    "/set_pixel",
    "/get_size"
)


class EndpointFilter(logging.Filter):
    """Used to filter out unicorn endpoint logging."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Returns true for logs that don't contain anything we want to filter out."""
        log = record.getMessage()
        return all(endpoint not in log for endpoint in ENDPOINTS_TO_FILTER_OUT)


# Filter out all endpoints in `ENDPOINTS_TO_FILTER_OUT`
logging.getLogger("uvicorn.access").addFilter(EndpointFilter())
