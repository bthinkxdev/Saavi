"""HTTP views for the payments app."""

from __future__ import annotations

import json
import logging

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from payments.services import (
    handle_payment_webhook,
    handle_razorpay_webhook_event,
    verify_razorpay_webhook_signature,
)

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
def cybersource_webhook_view(request: HttpRequest) -> HttpResponse:
    """
    Handle server-to-server Event Notifications from CyberSource.
    This is the authoritative source for payment success/failure.
    """
    try:
        from payments.services import verify_cybersource_webhook_signature
        signature = request.headers.get("V-C-Signature", "")
        payload = request.body
        
        if not verify_cybersource_webhook_signature(payload=payload, signature_header=signature):
            logger.warning("Rejected CyberSource webhook: invalid or missing V-C-Signature.")
            return JsonResponse({"status": "invalid_signature"}, status=400)
            
        data = json.loads(payload.decode('utf-8'))
        
        #cyberSource webhooks typically have a 'state' or 'status' field in the payload
        #e.g., {'id': '...', 'status': 'AUTHORIZED', 'clientReferenceInformation': {'code': 'order_id'}}
        order_id = None
        if 'clientReferenceInformation' in data and 'code' in data['clientReferenceInformation']:
            order_id = data['clientReferenceInformation']['code']
            
        status = data.get('status', '').upper()
        
        if order_id and status in ['AUTHORIZED', 'SETTLED', 'COMPLETED']:
            from payments.models import PaymentTransaction, PaymentStatus
            tx = PaymentTransaction.objects.filter(order_id=order_id).last()
            if tx and tx.status != PaymentStatus.SUCCESS:
                from payments.services import confirm_payment_success
                tx.external_transaction_id = data.get('id', '')
                tx.save(update_fields=["external_transaction_id"])
                confirm_payment_success(payment_transaction=tx)
                logger.info("CyberSource Webhook: Order %s marked as SUCCESS", order_id)
                
        elif order_id and status in ['DECLINED', 'FAILED', 'REJECTED']:
            from payments.models import PaymentTransaction, PaymentStatus
            tx = PaymentTransaction.objects.filter(order_id=order_id).last()
            if tx and tx.status != PaymentStatus.FAILED:
                from payments.services import confirm_payment_failed
                confirm_payment_failed(payment_transaction=tx)
                logger.info("CyberSource Webhook: Order %s marked as FAILED", order_id)
                
        return HttpResponse("Webhook received", status=200)
    except Exception:
        logger.exception("Failed to process CyberSource webhook")
        return HttpResponse(status=400)


@csrf_exempt
@require_POST
def razorpay_webhook_view(request: HttpRequest) -> HttpResponse:
    """
    Real, signature-verified Razorpay webhook — server-to-server confirmation
    path independent of the browser checkout.js redirect callback.

    Authenticated purely by the Razorpay signature (never by session/CSRF —
    this is a server-to-server call), computed over the raw request body.
    """
    signature = request.headers.get("X-Razorpay-Signature", "")
    if not verify_razorpay_webhook_signature(payload=request.body, signature=signature):
        logger.warning("Rejected Razorpay webhook: invalid or missing signature.")
        return JsonResponse({"status": "invalid_signature"}, status=400)

    event_id = request.headers.get("X-Razorpay-Event-Id", "")
    if not event_id:
        logger.warning("Rejected Razorpay webhook: missing X-Razorpay-Event-Id header.")
        return JsonResponse({"status": "missing_event_id"}, status=400)

    try:
        event_data = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        logger.warning("Rejected Razorpay webhook: malformed JSON body. event_id=%s", event_id)
        return JsonResponse({"status": "malformed_payload"}, status=400)

    event_type = event_data.get("event", "") if isinstance(event_data, dict) else ""
    event, created = handle_razorpay_webhook_event(
        event_id=event_id,
        event_type=event_type,
        event_data=event_data,
    )
    return JsonResponse({"status": event.status, "duplicate": not created}, status=200)


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
