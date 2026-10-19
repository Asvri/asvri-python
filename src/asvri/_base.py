"""What the sync and async clients share: options, requests as data, response handling, retry rules."""

from __future__ import annotations

import json
import platform
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional
from urllib.parse import urlencode

from ._version import VERSION
from .errors import APIConnectionError, APIError

DEFAULT_API_BASE = "https://api.asvri.com/app/api/v1"
KEY_PATTERN = re.compile(r"^sk_(test|live)_[A-Za-z0-9]{16,}$")


def check_key(secret_key: Optional[str]) -> str:
    key = (secret_key or "").strip()
    if key.startswith("pk_"):
        raise ValueError("That is a publishable key. The ASVRI API needs a secret key (sk_test_… or sk_live_…), kept on your server.")
    if not KEY_PATTERN.match(key):
        raise ValueError("Pass your ASVRI secret key (sk_test_… or sk_live_…), from ASVRI → Settings → API access.")
    return key


@dataclass
class Options:
    api_base: str = DEFAULT_API_BASE
    #: added to every path (".php" for a local ASVRI); empty by default
    api_ext: str = ""
    #: seconds before a call is given up
    timeout: float = 30
    #: extra tries for reads and idempotent creates after a dropped connection, a 429 or a 5xx
    max_retries: int = 2


@dataclass
class Request:
    method: str
    path: str
    query: Dict[str, Any] = field(default_factory=dict)
    body: Any = None
    idempotency_key: Optional[str] = None
    #: safe to send again: a read, or a create with an Idempotency-Key
    retryable: bool = False


def build(key: str, opts: Options, req: Request):
    """URL, headers and body bytes for one request."""
    query = {k: v for k, v in req.query.items() if v is not None and v != ""}
    url = f"{opts.api_base.rstrip('/')}/{req.path.lstrip('/')}{opts.api_ext}" + (f"?{urlencode(query)}" if query else "")
    headers = {
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
        "User-Agent": f"asvri-python/{VERSION} python/{platform.python_version()}",
    }
    data = None
    if req.body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(req.body, ensure_ascii=False).encode("utf-8")
    if req.idempotency_key:
        headers["Idempotency-Key"] = req.idempotency_key
    return url, headers, data


def should_retry(req: Request, attempt: int, opts: Options, status: Optional[int]) -> bool:
    """status None = no answer at all."""
    return req.retryable and attempt <= opts.max_retries and (status is None or status == 429 or status >= 500)


def backoff(attempt: int) -> float:
    return min(2.0, 0.5 * (2 ** (attempt - 1)))


def handle(status: int, raw: str) -> Dict[str, Any]:
    """The JSON for a 2xx, or the right exception."""
    try:
        body = json.loads(raw) if raw else None
    except ValueError:
        body = None
    if 200 <= status < 300:
        if not isinstance(body, dict):
            raise APIConnectionError(f"ASVRI answered HTTP {status} with a body that isn't JSON.", status)
        return body
    raise APIError.from_response(status, body, raw)


def params(given: Mapping[str, Any]) -> Dict[str, Any]:
    """Keyword arguments as a request body, without the ones left as None."""
    return {k: v for k, v in given.items() if v is not None}
