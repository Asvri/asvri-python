"""The synchronous client: standard library only (urllib)."""

from __future__ import annotations

import socket
import time
import urllib.error
import urllib.request
import uuid
from typing import Any, Dict, Iterator, List, Optional

from ._base import DEFAULT_API_BASE, Options, Request, backoff, build, check_key, handle, params, should_retry
from .errors import APIConnectionError
from .webhook import Webhook


class _Http:
    def __init__(self, key: str, opts: Options) -> None:
        self.key = key
        self.opts = opts

    def request(self, req: Request) -> Dict[str, Any]:
        url, headers, data = build(self.key, self.opts, req)
        attempt = 0
        while True:
            attempt += 1
            status: Optional[int] = None
            raw = ""
            failure: Optional[BaseException] = None
            try:
                r = urllib.request.Request(url, data=data, headers=headers, method=req.method)
                with urllib.request.urlopen(r, timeout=self.opts.timeout) as res:
                    status, raw = res.status, res.read().decode("utf-8", "replace")
            except urllib.error.HTTPError as e:  # a 4xx/5xx is still an answer
                status, raw = e.code, e.read().decode("utf-8", "replace")
            except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError) as e:
                failure = e
            if should_retry(req, attempt, self.opts, status):
                time.sleep(backoff(attempt))
                continue
            if status is None:
                reason = getattr(failure, "reason", failure)
                why = f"no answer within {self.opts.timeout:g} s" if isinstance(reason, (socket.timeout, TimeoutError)) else str(reason)
                raise APIConnectionError(f"Could not reach ASVRI: {why}")
            return handle(status, raw)


class CheckoutSessions:
    def __init__(self, http: _Http) -> None:
        self._http = http

    def create(self, *, currency: str, amount: Optional[float] = None, line_items: Optional[List[Dict[str, Any]]] = None,
               description: Optional[str] = None, reference: Optional[str] = None, customer: Optional[Dict[str, str]] = None,
               success_url: Optional[str] = None, cancel_url: Optional[str] = None, metadata: Optional[Dict[str, str]] = None,
               payment_methods: Optional[List[str]] = None, expires_in: Optional[int] = None,
               idempotency_key: Optional[str] = None) -> Dict[str, Any]:
        """A session for an amount (major units) or line items: send the customer to its "url". The same
        idempotency_key returns the same session (a retry, a double click); one is made for you when left out, so
        this call is safely retried."""
        body = params(dict(amount=amount, line_items=line_items, currency=currency, description=description, reference=reference,
                           customer=customer, success_url=success_url, cancel_url=cancel_url, metadata=metadata,
                           payment_methods=payment_methods, expires_in=expires_in))
        key = idempotency_key or f"asvri-python-{uuid.uuid4().hex}"
        return self._http.request(Request("POST", "checkout/sessions", body=body, idempotency_key=key, retryable=True))

    def retrieve(self, id: str) -> Dict[str, Any]:
        """One session as ASVRI has it now. Confirm payment here (status "paid"), never from the redirect alone."""
        return self._http.request(Request("GET", "checkout/sessions", query={"id": id}, retryable=True))

    def list(self, *, limit: Optional[int] = None, status: Optional[str] = None, starting_after: Optional[str] = None) -> Dict[str, Any]:
        """Sessions made with this key's mode, newest first: {"object": "list", "data": [...], "has_more": bool}."""
        return self._http.request(Request("GET", "checkout/sessions", query=params(dict(limit=limit, status=status, starting_after=starting_after)), retryable=True))

    def list_all(self, *, status: Optional[str] = None, limit: int = 100) -> Iterator[Dict[str, Any]]:
        """Every session, page after page: for s in asvri.checkout_sessions.list_all(status="paid")."""
        after = None
        while True:
            page = self.list(limit=limit, status=status, starting_after=after)
            yield from page["data"]
            if not page.get("has_more") or not page["data"]:
                return
            after = page["data"][-1]["id"]

    def expire(self, id: str) -> Dict[str, Any]:
        """Close an open session so it can't be paid. Not retried: a lost answer would turn a retry into a 409 for a
        call that worked; after an APIConnectionError, retrieve() the session instead."""
        return self._http.request(Request("POST", "checkout/sessions", query={"id": id, "action": "expire"}))


class Refunds:
    def __init__(self, http: _Http) -> None:
        self._http = http

    def create(self, *, session: Optional[str] = None, payment: Optional[str] = None, amount: Optional[float] = None,
               reason: Optional[str] = None) -> Dict[str, Any]:
        """Refund a paid session (or payment) through the gateway that took it; amount left out = everything not
        refunded yet. Never retried: a second try could refund twice."""
        return self._http.request(Request("POST", "refunds", body=params(dict(session=session, payment=payment, amount=amount, reason=reason))))


class WebhookEndpoints:
    def __init__(self, http: _Http) -> None:
        self._http = http

    def create(self, *, url: str, events: Optional[List[str]] = None, description: Optional[str] = None) -> Dict[str, Any]:
        """Register an HTTPS endpoint; keep the returned "secret" (whsec_…). The same URL again returns the existing
        endpoint ("created": False), so this is safe on every deploy."""
        return self._http.request(Request("POST", "webhooks", body=params(dict(url=url, events=events, description=description)), retryable=True))

    def list(self) -> Dict[str, Any]:
        return self._http.request(Request("GET", "webhooks", retryable=True))

    def delete(self, id: str) -> Dict[str, Any]:
        return self._http.request(Request("DELETE", "webhooks", query={"id": id}))


class Asvri:
    """ASVRI's API. Keep the secret key on your server:

        asvri = Asvri(os.environ["ASVRI_SECRET_KEY"])
        session = asvri.checkout_sessions.create(amount=25, currency="USD", success_url="https://…")
    """

    DEFAULT_API_BASE = DEFAULT_API_BASE
    webhook = Webhook

    def __init__(self, secret_key: Optional[str], *, api_base: str = DEFAULT_API_BASE, api_ext: str = "", timeout: float = 30, max_retries: int = 2) -> None:
        key = check_key(secret_key)
        self.mode = "test" if key.startswith("sk_test_") else "live"
        http = _Http(key, Options(api_base=api_base, api_ext=api_ext, timeout=timeout, max_retries=max(0, max_retries)))
        self.checkout_sessions = CheckoutSessions(http)
        self.refunds = Refunds(http)
        self.webhook_endpoints = WebhookEndpoints(http)
