"""Everything the SDK raises is an AsvriError.

ASVRI's own answers are APIError subclasses (by HTTP status); a call that got no answer is APIConnectionError; a
webhook that fails its check is SignatureVerificationError.
"""

from __future__ import annotations

from typing import Any, Optional


class AsvriError(Exception):
    """Base class for every error raised by the SDK."""


class APIError(AsvriError):
    """ASVRI answered with an error. status, type (authentication_error, invalid_request_error…) and param (the field
    at fault, when there is one) say what happened; the message is ASVRI's own and fit to log."""

    def __init__(self, message: str, status: int, type: Optional[str] = None, param: Optional[str] = None, body: Any = None) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.type = type
        self.param = param
        self.body = body

    @staticmethod
    def from_response(status: int, body: Any, raw: str) -> "APIError":
        """The right subclass for a status: 401 Authentication, 429 RateLimit, 5xx Server, other 4xx InvalidRequest."""
        err = body.get("error") if isinstance(body, dict) and isinstance(body.get("error"), dict) else {}
        message = err.get("message") or f"ASVRI answered HTTP {status}." + (f" {raw[:200]}" if body is None and raw else "")
        cls = AuthenticationError if status == 401 else RateLimitError if status == 429 else ServerError if status >= 500 else InvalidRequestError
        return cls(message, status, err.get("type"), err.get("param"), body)


class AuthenticationError(APIError):
    """401: the key is missing, wrong, revoked or expired."""


class InvalidRequestError(APIError):
    """4xx: something in the request (param names the field), 404 for an unknown id, 409 for an expired session."""


class RateLimitError(APIError):
    """429: too many requests; wait and try again."""


class ServerError(APIError):
    """5xx: a problem at ASVRI or at the gateway."""


class APIConnectionError(AsvriError):
    """No answer from ASVRI (network, timeout), or an answer that wasn't JSON."""

    def __init__(self, message: str, status: int = 0) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


class SignatureVerificationError(AsvriError):
    """A webhook whose Asvri-Signature doesn't check out: forged, stale, or verified with the wrong secret."""
