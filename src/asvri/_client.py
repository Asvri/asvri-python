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


class SetupSessions:
    """Cards on file, step one: a customer saves a card (or wallet) now, with nothing paid, to be charged later with
    asvri.charges. Open the session's "url", or embed it in your page with asvri.js and its "setup_token" (a
    single-use token for that one add-card page, safe in a browser; never put your sk_ API key in a page).
    "client_secret" is a deprecated alias with the same value. Guide: https://www.asvri.com/developers/cards-on-file"""

    def __init__(self, http: _Http) -> None:
        self._http = http

    def create(self, *, customer: Optional[Dict[str, str]] = None, customer_id: Optional[str] = None, gateway: Optional[str] = None,
               payment_methods: Optional[List[str]] = None, success_url: Optional[str] = None, cancel_url: Optional[str] = None,
               metadata: Optional[Dict[str, str]] = None, expires_in: Optional[int] = None,
               idempotency_key: Optional[str] = None) -> Dict[str, Any]:
        """A session for a customer ({"email", "name"}, matched to yours by email) or customer_id. The same
        idempotency_key returns the same session (a retry, a double click); one is made for you when left out, so
        this call is safely retried."""
        body = params(dict(customer=customer, customer_id=customer_id, gateway=gateway, payment_methods=payment_methods,
                           success_url=success_url, cancel_url=cancel_url, metadata=metadata, expires_in=expires_in))
        key = idempotency_key or f"asvri-python-{uuid.uuid4().hex}"
        return self._http.request(Request("POST", "setup_sessions", body=body, idempotency_key=key, retryable=True))

    def retrieve(self, id: str) -> Dict[str, Any]:
        """One session as ASVRI has it now. Once "completed", its "payment_method" is the saved card (pm_…)."""
        return self._http.request(Request("GET", "setup_sessions", query={"id": id}, retryable=True))

    def list(self, *, limit: Optional[int] = None, status: Optional[str] = None, customer: Optional[str] = None,
             starting_after: Optional[str] = None) -> Dict[str, Any]:
        """Sessions made with this key's mode, newest first; customer is cus_… or an email."""
        return self._http.request(Request("GET", "setup_sessions", query=params(dict(limit=limit, status=status, customer=customer, starting_after=starting_after)), retryable=True))

    def cancel(self, id: str) -> Dict[str, Any]:
        """Close an open session so the card can no longer be saved through it. Not retried: after an
        APIConnectionError, retrieve() the session instead."""
        return self._http.request(Request("POST", "setup_sessions", query={"id": id, "action": "cancel"}))


class PaymentMethods:
    """The cards and wallets your customers saved (setup sessions, or checkout sessions with save_payment_method)."""

    def __init__(self, http: _Http) -> None:
        self._http = http

    def retrieve(self, id: str) -> Dict[str, Any]:
        return self._http.request(Request("GET", "payment_methods", query={"id": id}, retryable=True))

    def list(self, *, customer: Optional[str] = None, limit: Optional[int] = None, include_removed: bool = False) -> Dict[str, Any]:
        """A customer's methods (cus_… or an email), or all of them, newest first. Removed ones only with include_removed."""
        return self._http.request(Request("GET", "payment_methods", query=params(dict(customer=customer, limit=limit, include_removed="true" if include_removed else None)), retryable=True))

    def detach(self, id: str) -> Dict[str, Any]:
        """Remove a saved method: it can't be charged again (payment_method.detached is posted). Past charges keep
        their records. Safe to retry: removing a removed method returns it as it is."""
        return self._http.request(Request("DELETE", "payment_methods", query={"id": id}, retryable=True))


class Charges:
    """Cards on file, step two: charge a saved payment method with nobody present (merchant-initiated)."""

    def __init__(self, http: _Http) -> None:
        self._http = http

    def create(self, *, payment_method: str, amount: float, currency: str, description: Optional[str] = None,
               reference: Optional[str] = None, metadata: Optional[Dict[str, str]] = None,
               idempotency_key: Optional[str] = None) -> Dict[str, Any]:
        """Charge a saved method now, through the gateway it was saved on. The answer is final in one call:
        "succeeded", "failed" ("error" says why), "pending" (a webhook settles it) or "requires_action"
        ("next_action"["url"] is a payment page for the customer).

        Always pass an idempotency_key (e.g. "sub-1042-oct"): with one, ASVRI returns the same charge for the same
        key, so the call is retried like a read. Without one the SDK never retries: a second try could charge twice."""
        body = params(dict(payment_method=payment_method, amount=amount, currency=currency, description=description, reference=reference, metadata=metadata))
        return self._http.request(Request("POST", "charges", body=body, idempotency_key=idempotency_key, retryable=bool(idempotency_key)))

    def retrieve(self, id: str) -> Dict[str, Any]:
        """One charge: its status, "payment" (once succeeded) and "next_action" (when the bank wants the customer)."""
        return self._http.request(Request("GET", "charges", query={"id": id}, retryable=True))

    def list(self, *, limit: Optional[int] = None, payment_method: Optional[str] = None, customer: Optional[str] = None,
             starting_after: Optional[str] = None) -> Dict[str, Any]:
        """Charges in this key's mode, newest first; narrow to one payment_method (pm_…) or customer (cus_… or email)."""
        return self._http.request(Request("GET", "charges", query=params(dict(limit=limit, payment_method=payment_method, customer=customer, starting_after=starting_after)), retryable=True))


class Asvri:
    """ASVRI's API. Keep the secret key on your server:

        asvri = Asvri(os.environ["ASVRI_SECRET_KEY"])
        session = asvri.checkout_sessions.create(amount=25, currency="USD", success_url="https://…")

    Cards on file: asvri.setup_sessions (save a card with nothing paid), asvri.payment_methods (what was saved) and
    asvri.charges (charge it later, with nobody present).
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
        self.setup_sessions = SetupSessions(http)
        self.payment_methods = PaymentMethods(http)
        self.charges = Charges(http)
