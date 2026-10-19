# ASVRI Python SDK

ASVRI's API for Python. Take payments with every gateway you've connected to ASVRI (cards, bank transfer, USSD, mobile money): create a checkout session on your server, send the customer to it, and confirm the payment with ASVRI or its signed webhook. Refund through the gateway that took the payment.

Python 3.10+. No dependencies for the sync client; `asvri[async]` adds the asyncio client (httpx). Helpers for Django and FastAPI. Typed.

## Install

```bash
pip install asvri                 # sync client
pip install "asvri[async]"        # + AsyncAsvri
```

Until it is on PyPI: `pip install git+https://github.com/asvri/asvri-python`.

## Keys

Use your **secret key** (`sk_test_…` or `sk_live_…`) from ASVRI → Settings → API access, on your server only. Test keys use only test gateways, so no real money moves.

```python
import os
from asvri import Asvri

asvri = Asvri(os.environ["ASVRI_SECRET_KEY"])
```

## Take a payment

```python
session = asvri.checkout_sessions.create(
    amount=25,                        # major units; or line_items=[{"name": …, "quantity": 1, "amount": …}]
    currency="USD",
    description="Order #1042",
    reference="1042",
    customer={"name": "Ada Obi", "email": "ada@example.com"},
    success_url="https://yourshop.com/thanks",   # ASVRI adds ?session_id=cs_…
    cancel_url="https://yourshop.com/cart",
    metadata={"order_id": "1042"},
    idempotency_key="order-1042",     # optional: one session per order, however often you retry
)
return redirect(session["url"])
```

When the customer comes back, **ask ASVRI**. Never trust the redirect alone:

```python
session = asvri.checkout_sessions.retrieve(request.GET["session_id"])
if session["status"] == "paid":
    ...  # session["payment"]: gateway, gateway_name, gateway_reference, method, amount, fee
```

Other calls:

```python
asvri.checkout_sessions.list(status="paid", limit=20)        # one page: {"data": [...], "has_more": bool}
for s in asvri.checkout_sessions.list_all(status="paid"):    # every page
    ...
asvri.checkout_sessions.expire(session_id)                   # close an open session
```

## Async

```python
from asvri import AsyncAsvri

async with AsyncAsvri(os.environ["ASVRI_SECRET_KEY"]) as asvri:
    session = await asvri.checkout_sessions.create(amount=25, currency="USD")
    async for s in asvri.checkout_sessions.list_all(status="paid"):
        ...
```

Same methods and errors as the sync client.

## Webhooks

Register your endpoint once and keep its signing secret. The same URL again returns the existing endpoint:

```python
endpoint = asvri.webhook_endpoints.create(url="https://yourshop.com/asvri/webhook")
# store endpoint["secret"] (whsec_…) as ASVRI_WEBHOOK_SECRET
```

Verify every event against the **raw** body:

```python
from asvri import Webhook, SignatureVerificationError

event = Webhook.construct_event(raw_body, signature_header, os.environ["ASVRI_WEBHOOK_SECRET"])
if event["type"] == "checkout.session.completed":
    session = event["data"]["checkout_session"]   # mark session["metadata"]["order_id"] paid, once per event["id"]
```

Events older than 5 minutes are refused as possible replays (`tolerance=` seconds; `0` turns the check off). `event["test"]` is `True` for test-mode events.

**Django**:

```python
# urls.py
from asvri.contrib.django import webhook_view

def handle(event):
    if event["type"] == "checkout.session.completed":
        ...

urlpatterns = [path("asvri/webhook", webhook_view(handle))]   # secret: settings.ASVRI_WEBHOOK_SECRET or the env var
```

**FastAPI**:

```python
from fastapi import Depends, FastAPI
from asvri.contrib.fastapi import AsvriWebhook

app = FastAPI()

@app.post("/asvri/webhook")
async def asvri_webhook(event: dict = Depends(AsvriWebhook())):
    ...
    return {"ok": True}
```

How both helpers answer:

- **Bad signature:** 400, before your code runs.
- **Your code raises:** 500, so ASVRI retries later with the same event id. Make handlers safe to run twice.

## Refunds

```python
asvri.refunds.create(session="cs_live_…", amount=1000, reason="Damaged item")   # part
asvri.refunds.create(payment="txn_…")                                           # the rest
```

## Errors

Everything raised is an `AsvriError`:

| Class | When |
| --- | --- |
| `AuthenticationError` | 401: the key is wrong, revoked or expired |
| `InvalidRequestError` | 4xx: `e.param` names the field; 404 for an unknown id; 409 when a session is already expired |
| `RateLimitError` | 429 |
| `ServerError` | 5xx |
| `APIConnectionError` | no answer (network, timeout) |
| `SignatureVerificationError` | a webhook that fails its check |

API errors carry `status`, `type`, `param` and `body`.

## Retries and timeouts

Reads, session creates (each has an idempotency key; one is made for you) and webhook endpoint creates are retried twice on a dropped connection, a 429 or a 5xx. **Refunds and expire are never retried**, so nothing happens twice: after an `APIConnectionError`, retrieve the session to see where it stands.

```python
Asvri(key, timeout=30, max_retries=2)
```

## Links

- API reference: https://www.asvri.com/developers/docs
- Try every call in your browser: https://www.asvri.com/api-playground

MIT licence.
