# A complete checkout with Flask: create a session, send the customer to ASVRI, confirm on return, verify webhooks.
#   pip install asvri flask
#   ASVRI_SECRET_KEY=sk_test_... ASVRI_WEBHOOK_SECRET=whsec_... flask --app examples/flask_app run
import os

from flask import Flask, abort, redirect, request

from asvri import Asvri, SignatureVerificationError, Webhook

asvri = Asvri(os.environ["ASVRI_SECRET_KEY"])
app = Flask(__name__)
BASE = os.environ.get("BASE_URL", "http://127.0.0.1:5000")


@app.post("/checkout")
def checkout():
    order_id = "1042"  # your order
    session = asvri.checkout_sessions.create(amount=25, currency="USD", reference=order_id, success_url=f"{BASE}/thanks",
                                             cancel_url=f"{BASE}/cart", metadata={"order_id": order_id},
                                             idempotency_key=f"order-{order_id}")
    return redirect(session["url"], code=303)


@app.get("/thanks")
def thanks():
    session = asvri.checkout_sessions.retrieve(request.args.get("session_id", ""))
    return "Paid. Thank you!" if session["status"] == "paid" else "Payment not confirmed yet."


@app.post("/asvri/webhook")
def asvri_webhook():
    try:
        event = Webhook.construct_event(request.get_data(), request.headers.get("Asvri-Signature"), os.environ["ASVRI_WEBHOOK_SECRET"])
    except SignatureVerificationError:
        abort(400)
    if event["type"] == "checkout.session.completed":
        print("paid:", event["data"]["checkout_session"]["metadata"].get("order_id"))
    return "ok"
