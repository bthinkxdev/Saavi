"""HTTP views for the payments app."""

from __future__ import annotations

import json
import logging

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from payments.services import handle_payment_webhook

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def payment_webhook_view(request: HttpRequest, gateway_key: str) -> HttpResponse:
    """CSRF-exempt webhook receiver — signature verified per adapter."""
    signature = request.headers.get("X-Payment-Signature", "")
    payment_tx = handle_payment_webhook(
        gateway_key=gateway_key,
        payload=request.body,
        signature=signature,
    )
    if payment_tx is None:
        return JsonResponse({"status": "ignored"}, status=404)
    return JsonResponse({"status": payment_tx.status})


@csrf_exempt
@require_POST
def stripe_webhook_view(request: HttpRequest) -> HttpResponse:
    """
    Handle server-to-server Event Notifications from Stripe.

    Authenticated purely by the Stripe signature. This is the authoritative path
    for payment success / failure / refund; every handler is idempotent, so
    Stripe's retries and duplicate deliveries are safe.
    """
    from payments.adapters.stripe import StripePaymentAdapter
    from payments.stripe_service import handle_charge_refunded, reconcile_payment_intent

    signature = request.headers.get("Stripe-Signature", "")
    try:
        event = StripePaymentAdapter().verify_webhook(payload=request.body, signature=signature)
    except ValueError as e:
        logger.warning("Rejected Stripe webhook: %s", str(e))
        return JsonResponse({"status": "invalid_signature"}, status=400)

    event_id = event.get("id", "")
    event_type = event.get("type", "")
    data_object = (event.get("data") or {}).get("object") or {}

    if event_type.startswith("payment_intent."):
        result = reconcile_payment_intent(data_object)
    elif event_type == "charge.refunded":
        result = handle_charge_refunded(data_object)
    else:
        logger.debug("Ignoring Stripe webhook event %s (%s)", event_id, event_type)
        return JsonResponse({"status": "ignored", "event": event_type}, status=200)

    logger.info("Stripe webhook %s (%s) -> %s", event_id, event_type, result.outcome)
    return JsonResponse({"status": result.outcome, "event": event_type}, status=200)
