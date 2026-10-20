"""The asyncio client, on httpx: pip install "asvri[async]"."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, AsyncIterator, Dict, List, Optional

from ._base import DEFAULT_API_BASE, Options, Request, backoff, build, check_key, handle, params, should_retry
from .errors import APIConnectionError
from .webhook import Webhook

try:
    import httpx
except ImportError:  # pragma: no cover - checked when the client is made
    httpx = None  # type: ignore[assignment]


class _AsyncHttp:
    def __init__(self, key: str, opts: Options, client: "Optional[httpx.AsyncClient]") -> None:
        self.key = key
        self.opts = opts
        self._client = client
        self._own = client is None

    def client(self) -> "httpx.AsyncClient":
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.opts.timeout)
        return self._client

    async def request(self, req: Request) -> Dict[str, Any]:
        url, headers, data = build(self.key, self.opts, req)
        attempt = 0
        while True:
            attempt += 1
            status: Optional[int] = None
            raw = ""
            failure: Optional[BaseException] = None
            try:
                res = await self.client().request(req.method, url, headers=headers, content=data, timeout=self.opts.timeout)
                status, raw = res.status_code, res.text
            except httpx.TransportError as e:
                failure = e
            if should_retry(req, attempt, self.opts, status):
                await asyncio.sleep(backoff(attempt))
                continue
            if status is None:
                why = f"no answer within {self.opts.timeout:g} s" if isinstance(failure, httpx.TimeoutException) else (str(failure) or type(failure).__name__)
                raise APIConnectionError(f"Could not reach ASVRI: {why}")
            return handle(status, raw)

    async def aclose(self) -> None:
        if self._own and self._client is not None:
            await self._client.aclose()
            self._client = None


class AsyncCheckoutSessions:
    def __init__(self, http: _AsyncHttp) -> None:
        self._http = http

    async def create(self, *, currency: str, amount: Optional[float] = None, line_items: Optional[List[Dict[str, Any]]] = None,
                     description: Optional[str] = None, reference: Optional[str] = None, customer: Optional[Dict[str, str]] = None,
                     success_url: Optional[str] = None, cancel_url: Optional[str] = None, metadata: Optional[Dict[str, str]] = None,
                     payment_methods: Optional[List[str]] = None, expires_in: Optional[int] = None,
                     idempotency_key: Optional[str] = None) -> Dict[str, Any]:
        body = params(dict(amount=amount, line_items=line_items, currency=currency, description=description, reference=reference,
                           customer=customer, success_url=success_url, cancel_url=cancel_url, metadata=metadata,
                           payment_methods=payment_methods, expires_in=expires_in))
        key = idempotency_key or f"asvri-python-{uuid.uuid4().hex}"
        return await self._http.request(Request("POST", "checkout/sessions", body=body, idempotency_key=key, retryable=True))

    async def retrieve(self, id: str) -> Dict[str, Any]:
        return await self._http.request(Request("GET", "checkout/sessions", query={"id": id}, retryable=True))

    async def list(self, *, limit: Optional[int] = None, status: Optional[str] = None, starting_after: Optional[str] = None) -> Dict[str, Any]:
        return await self._http.request(Request("GET", "checkout/sessions", query=params(dict(limit=limit, status=status, starting_after=starting_after)), retryable=True))

    async def list_all(self, *, status: Optional[str] = None, limit: int = 100) -> AsyncIterator[Dict[str, Any]]:
        after = None
        while True:
            page = await self.list(limit=limit, status=status, starting_after=after)
            for s in page["data"]:
                yield s
            if not page.get("has_more") or not page["data"]:
                return
            after = page["data"][-1]["id"]

    async def expire(self, id: str) -> Dict[str, Any]:
        return await self._http.request(Request("POST", "checkout/sessions", query={"id": id, "action": "expire"}))


class AsyncRefunds:
    def __init__(self, http: _AsyncHttp) -> None:
        self._http = http

    async def create(self, *, session: Optional[str] = None, payment: Optional[str] = None, amount: Optional[float] = None,
                     reason: Optional[str] = None) -> Dict[str, Any]:
        return await self._http.request(Request("POST", "refunds", body=params(dict(session=session, payment=payment, amount=amount, reason=reason))))


class AsyncWebhookEndpoints:
    def __init__(self, http: _AsyncHttp) -> None:
        self._http = http

    async def create(self, *, url: str, events: Optional[List[str]] = None, description: Optional[str] = None) -> Dict[str, Any]:
        return await self._http.request(Request("POST", "webhooks", body=params(dict(url=url, events=events, description=description)), retryable=True))

    async def list(self) -> Dict[str, Any]:
        return await self._http.request(Request("GET", "webhooks", retryable=True))

    async def delete(self, id: str) -> Dict[str, Any]:
        return await self._http.request(Request("DELETE", "webhooks", query={"id": id}))


class AsyncSetupSessions:
    def __init__(self, http: _AsyncHttp) -> None:
        self._http = http

    async def create(self, *, customer: Optional[Dict[str, str]] = None, customer_id: Optional[str] = None, gateway: Optional[str] = None,
                     payment_methods: Optional[List[str]] = None, success_url: Optional[str] = None, cancel_url: Optional[str] = None,
                     metadata: Optional[Dict[str, str]] = None, expires_in: Optional[int] = None,
                     idempotency_key: Optional[str] = None) -> Dict[str, Any]:
        body = params(dict(customer=customer, customer_id=customer_id, gateway=gateway, payment_methods=payment_methods,
                           success_url=success_url, cancel_url=cancel_url, metadata=metadata, expires_in=expires_in))
        key = idempotency_key or f"asvri-python-{uuid.uuid4().hex}"
        return await self._http.request(Request("POST", "setup_sessions", body=body, idempotency_key=key, retryable=True))

    async def retrieve(self, id: str) -> Dict[str, Any]:
        return await self._http.request(Request("GET", "setup_sessions", query={"id": id}, retryable=True))

    async def list(self, *, limit: Optional[int] = None, status: Optional[str] = None, customer: Optional[str] = None,
                   starting_after: Optional[str] = None) -> Dict[str, Any]:
        return await self._http.request(Request("GET", "setup_sessions", query=params(dict(limit=limit, status=status, customer=customer, starting_after=starting_after)), retryable=True))

    async def cancel(self, id: str) -> Dict[str, Any]:
        return await self._http.request(Request("POST", "setup_sessions", query={"id": id, "action": "cancel"}))


class AsyncPaymentMethods:
    def __init__(self, http: _AsyncHttp) -> None:
        self._http = http

    async def retrieve(self, id: str) -> Dict[str, Any]:
        return await self._http.request(Request("GET", "payment_methods", query={"id": id}, retryable=True))

    async def list(self, *, customer: Optional[str] = None, limit: Optional[int] = None, include_removed: bool = False) -> Dict[str, Any]:
        return await self._http.request(Request("GET", "payment_methods", query=params(dict(customer=customer, limit=limit, include_removed="true" if include_removed else None)), retryable=True))

    async def detach(self, id: str) -> Dict[str, Any]:
        return await self._http.request(Request("DELETE", "payment_methods", query={"id": id}, retryable=True))


class AsyncCharges:
    def __init__(self, http: _AsyncHttp) -> None:
        self._http = http

    async def create(self, *, payment_method: str, amount: float, currency: str, description: Optional[str] = None,
                     reference: Optional[str] = None, metadata: Optional[Dict[str, str]] = None,
                     idempotency_key: Optional[str] = None) -> Dict[str, Any]:
        # retried only with an idempotency key: without one, a second try could charge twice
        body = params(dict(payment_method=payment_method, amount=amount, currency=currency, description=description, reference=reference, metadata=metadata))
        return await self._http.request(Request("POST", "charges", body=body, idempotency_key=idempotency_key, retryable=bool(idempotency_key)))

    async def retrieve(self, id: str) -> Dict[str, Any]:
        return await self._http.request(Request("GET", "charges", query={"id": id}, retryable=True))

    async def list(self, *, limit: Optional[int] = None, payment_method: Optional[str] = None, customer: Optional[str] = None,
                   starting_after: Optional[str] = None) -> Dict[str, Any]:
        return await self._http.request(Request("GET", "charges", query=params(dict(limit=limit, payment_method=payment_method, customer=customer, starting_after=starting_after)), retryable=True))


class AsyncAsvri:
    """The same API for asyncio:

        async with AsyncAsvri(os.environ["ASVRI_SECRET_KEY"]) as asvri:
            session = await asvri.checkout_sessions.create(amount=25, currency="USD")
    """

    DEFAULT_API_BASE = DEFAULT_API_BASE
    webhook = Webhook

    def __init__(self, secret_key: Optional[str], *, api_base: str = DEFAULT_API_BASE, api_ext: str = "", timeout: float = 30,
                 max_retries: int = 2, http_client: "Optional[httpx.AsyncClient]" = None) -> None:
        if httpx is None:
            raise ImportError('AsyncAsvri needs httpx: pip install "asvri[async]"')
        key = check_key(secret_key)
        self.mode = "test" if key.startswith("sk_test_") else "live"
        self._http = _AsyncHttp(key, Options(api_base=api_base, api_ext=api_ext, timeout=timeout, max_retries=max(0, max_retries)), http_client)
        self.checkout_sessions = AsyncCheckoutSessions(self._http)
        self.refunds = AsyncRefunds(self._http)
        self.webhook_endpoints = AsyncWebhookEndpoints(self._http)
        self.setup_sessions = AsyncSetupSessions(self._http)
        self.payment_methods = AsyncPaymentMethods(self._http)
        self.charges = AsyncCharges(self._http)

    async def aclose(self) -> None:
        """Close the connection pool (not one you passed in)."""
        await self._http.aclose()

    async def __aenter__(self) -> "AsyncAsvri":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()
