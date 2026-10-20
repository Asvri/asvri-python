# ASVRI Python SDK

ASVRI's API for Python. Take payments with every gateway you've connected to ASVRI (cards, bank transfer, USSD, mobile money): create a checkout session on your server, send the customer to it, and confirm the payment with ASVRI or its signed webhook. Refund through the gateway that took the payment. Keep cards on file and charge them later.

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

## Cards on file

Save a customer's card now, with nothing paid, and charge it later with nobody present (subscriptions, usage billing, "pay with my saved card"). Only gateways that can keep a card without a payment take part (Stripe, PayPal and others marked "Save & charge later" in your dashboard).

**1. On your server, create a setup session:**

```python
setup = asvri.setup_sessions.create(
    customer={"email": "ada@example.com", "name": "Ada Obi"},
    success_url="https://yourshop.com/account/cards?saved=1",   # ASVRI adds ?setup_session_id=ss_…
    metadata={"account": "42"},
    idempotency_key="cards-42-1",
)
```

**2. Let the customer add the card:** send them to the session's `url`, or hand its `client_secret` to the browser and embed the form in your own page with asvri.js. The gateway's own secure fields collect the card, so neither you nor ASVRI sees the number.

**3. Confirm it was saved** with `retrieve` or the `payment_method.attached` webhook, never from the redirect alone:

```python
setup = asvri.setup_sessions.retrieve(request.GET["setup_session_id"])
if setup["status"] == "completed":
    card = setup["payment_method"]   # {"id": "pm_…", "label": "Visa •••• 4242", …}: store card["id"]
```

**4. Charge it later**, always with an idempotency key so a retry can never charge twice:

```python
charge = asvri.charges.create(
    payment_method="pm_…", amount=49.99, currency="USD",
    description="October subscription", reference="sub-1042-oct",
    idempotency_key="sub-1042-oct",
)
# charge["status"]: succeeded (charge["payment"] is the transaction), failed (charge["error"] says why),
# pending (charge.succeeded / charge.failed follows by webhook) or requires_action (the bank wants the
# customer: send them to charge["next_action"]["url"])
```

Other calls:

```python
asvri.payment_methods.list(customer="ada@example.com")   # a customer's saved cards
asvri.payment_methods.retrieve("pm_…")
asvri.payment_methods.detach("pm_…")                      # it can't be charged again
asvri.charges.retrieve("ch_…")
asvri.charges.list(payment_method="pm_…")
asvri.setup_sessions.list(status="completed")
asvri.setup_sessions.cancel("ss_…")
asvri.refunds.create(payment=charge["payment"]["id"])     # refund a charge
```

The async client has the same methods (`await asvri.charges.create(...)`). Events: `payment_method.attached`, `payment_method.detached`, `charge.succeeded`, `charge.failed`, `charge.requires_action` (the object is in `data.payment_method` / `data.charge`).

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

Reads, session creates (each has an idempotency key; one is made for you), webhook endpoint creates and charges **with** an idempotency key are retried twice on a dropped connection, a 429 or a 5xx. **Refunds, expire, cancel and a charge without an idempotency key are never retried**, so nothing happens twice: after an `APIConnectionError`, retrieve the session (or list the method's charges) to see where it stands.

```python
Asvri(key, timeout=30, max_retries=2)
```

## Links

- API reference: https://www.asvri.com/developers/docs
- Try every call in your browser: https://www.asvri.com/api-playground

MIT licence.
