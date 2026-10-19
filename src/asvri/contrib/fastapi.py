"""A FastAPI dependency that hands your route a verified ASVRI event.

    from fastapi import Depends, FastAPI
    from asvri.contrib.fastapi import AsvriWebhook

    app = FastAPI()
    verified = AsvriWebhook()                      # secret from ASVRI_WEBHOOK_SECRET

    @app.post("/asvri/webhook")
    async def asvri_webhook(event: dict = Depends(verified)):
        if event["type"] == "checkout.session.completed":
            ...                                    # mark the order paid; handle each event["id"] once
        return {"ok": True}

A bad signature answers 400 before your route runs. If your route raises, FastAPI answers 500 and ASVRI retries.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from fastapi import HTTPException, Request

from ..errors import SignatureVerificationError
from ..webhook import Webhook


class AsvriWebhook:
    def __init__(self, secret: Optional[str] = None, tolerance: int = Webhook.DEFAULT_TOLERANCE) -> None:
        self.secret = secret
        self.tolerance = tolerance

    async def __call__(self, request: Request) -> Dict[str, Any]:
        secret = self.secret or os.environ.get("ASVRI_WEBHOOK_SECRET", "")
        if not secret:
            raise HTTPException(status_code=500, detail="Webhook secret not configured.")
        payload = await request.body()
        try:
            return Webhook.construct_event(payload, request.headers.get("asvri-signature"), secret, self.tolerance)
        except SignatureVerificationError as e:
            raise HTTPException(status_code=400, detail=str(e)) from None
