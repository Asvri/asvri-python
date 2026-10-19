"""A Django view for ASVRI's webhook.

    # urls.py
    from asvri.contrib.django import webhook_view

    def handle(event):
        if event["type"] == "checkout.session.completed":
            Order.objects.filter(pk=event["data"]["checkout_session"]["metadata"]["order_id"]).update(paid=True)

    urlpatterns = [path("asvri/webhook", webhook_view(handle))]

The secret comes from settings.ASVRI_WEBHOOK_SECRET or the ASVRI_WEBHOOK_SECRET environment variable. A bad signature
gets 400; a handler that raises gets 500, so ASVRI retries it (with the same event id: make the handler idempotent).
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable, Dict, Optional

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from ..errors import SignatureVerificationError
from ..webhook import Webhook

log = logging.getLogger("asvri")


def webhook_view(handler: Callable[[Dict[str, Any]], Any], *, secret: Optional[str] = None, tolerance: int = Webhook.DEFAULT_TOLERANCE):
    @csrf_exempt  # the signature proves the request, not a CSRF token
    @require_POST
    def view(request: HttpRequest) -> HttpResponse:
        key = secret or getattr(settings, "ASVRI_WEBHOOK_SECRET", None) or os.environ.get("ASVRI_WEBHOOK_SECRET", "")
        if not key:
            log.error("ASVRI webhook received but ASVRI_WEBHOOK_SECRET is not set")
            return HttpResponse("Webhook secret not configured.", status=500)
        try:
            event = Webhook.construct_event(request.body, request.headers.get("Asvri-Signature"), key, tolerance)
        except SignatureVerificationError as e:
            return HttpResponse(str(e), status=400)
        try:
            handler(event)
        except Exception:
            log.exception("ASVRI webhook handler for %s failed", event.get("type"))
            return HttpResponse("Handler failed; ASVRI will retry.", status=500)
        return HttpResponse("ok")

    return view
