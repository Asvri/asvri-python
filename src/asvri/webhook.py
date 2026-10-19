"""Events ASVRI posts to your endpoint. Verify each one with the RAW body, before any JSON parsing:

    event = Webhook.construct_event(request.body, request.headers["Asvri-Signature"], os.environ["ASVRI_WEBHOOK_SECRET"])

Header: Asvri-Signature: t=<unix time>,v1=<hex HMAC-SHA256(secret, "<t>.<raw body>")>. The same event can arrive more
than once (retries keep its id): handle each id once.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any, Dict, Optional, Union

from .errors import SignatureVerificationError

Payload = Union[str, bytes, bytearray]


def _text(payload: Payload) -> str:
    if isinstance(payload, (bytes, bytearray)):
        return bytes(payload).decode("utf-8")
    if isinstance(payload, str):
        return payload
    raise SignatureVerificationError("Pass the raw request body (bytes or str), not parsed JSON: the signature covers the exact bytes.")


def _sign(secret: str, timestamp: Union[str, int], payload: str) -> str:
    return hmac.new(secret.encode("utf-8"), f"{timestamp}.{payload}".encode("utf-8"), hashlib.sha256).hexdigest()


class Webhook:
    DEFAULT_TOLERANCE = 300

    @staticmethod
    def verify_signature(payload: Payload, header: Optional[str], secret: str, tolerance: int = DEFAULT_TOLERANCE) -> bool:
        """True, or SignatureVerificationError saying why. tolerance: seconds an event may be old (0 = no check)."""
        if not secret:
            raise SignatureVerificationError("No signing secret given.")
        text = _text(payload)
        t: Optional[str] = None
        signatures = []
        for part in (header or "").split(","):
            k, sep, v = part.strip().partition("=")
            if not sep:
                continue
            if k == "t":
                t = v
            elif k == "v1":
                signatures.append(v)
        if t is None or not t.isdigit() or not signatures:
            raise SignatureVerificationError("No valid Asvri-Signature header (expected t=…,v1=…).")
        if tolerance > 0 and abs(time.time() - int(t)) > tolerance:
            raise SignatureVerificationError(f"The event is older than the tolerance ({tolerance} s): refused as a possible replay.")
        expected = _sign(secret, t, text)
        if any(hmac.compare_digest(expected, s) for s in signatures):
            return True
        raise SignatureVerificationError("The signature does not match this endpoint's secret.")

    @staticmethod
    def construct_event(payload: Payload, header: Optional[str], secret: str, tolerance: int = DEFAULT_TOLERANCE) -> Dict[str, Any]:
        """Verify, then parse: {"id", "type", "created", "test", "data"}, or SignatureVerificationError."""
        Webhook.verify_signature(payload, header, secret, tolerance)
        try:
            event = json.loads(_text(payload))
        except ValueError:
            event = None
        if not isinstance(event, dict) or "type" not in event or "data" not in event:
            raise SignatureVerificationError("The signature is valid but the body is not an ASVRI event.")
        return event

    @staticmethod
    def generate_test_header(payload: Payload, secret: str, timestamp: Optional[int] = None) -> str:
        """The header ASVRI would send for a payload: for your own tests."""
        t = int(time.time()) if timestamp is None else int(timestamp)
        return f"t={t},v1={_sign(secret, t, _text(payload))}"
