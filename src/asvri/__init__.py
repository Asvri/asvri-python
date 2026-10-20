"""ASVRI's API for Python: checkout sessions that take payment through every gateway you've connected, cards on file
(setup sessions, saved payment methods, charges), refunds, webhook endpoints and webhook signature checks.

    from asvri import Asvri
    asvri = Asvri(os.environ["ASVRI_SECRET_KEY"])
"""

from ._base import DEFAULT_API_BASE
from ._client import Asvri
from ._version import VERSION
from .errors import (
    APIConnectionError,
    APIError,
    AsvriError,
    AuthenticationError,
    InvalidRequestError,
    RateLimitError,
    ServerError,
    SignatureVerificationError,
)
from .webhook import Webhook

__version__ = VERSION


def __getattr__(name: str):
    # the async client imports httpx, so only when it's asked for
    if name == "AsyncAsvri":
        from ._async import AsyncAsvri

        return AsyncAsvri
    raise AttributeError(name)


__all__ = [
    "Asvri",
    "AsyncAsvri",
    "Webhook",
    "AsvriError",
    "APIError",
    "AuthenticationError",
    "InvalidRequestError",
    "RateLimitError",
    "ServerError",
    "APIConnectionError",
    "SignatureVerificationError",
    "DEFAULT_API_BASE",
    "VERSION",
]
