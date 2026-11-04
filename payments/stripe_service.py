"""
Stripe reconciliation — the single place a Stripe PaymentIntent / Charge is
turned into PaymentTransaction + Order state.

Both the signed webhook and the customer's browser return funnel through
``reconcile_payment_intent``, and neither ever trusts query-string data: the
intent is always either signature-verified (webhook) or fetched from Stripe with
our secret key (browser return). A payment is only confirmed when Stripe says the
intent ``succeeded`` AND its id, currency and amount match what we recorded.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import stripe
from django.db import transaction

from payments.adapters.stripe import (
    from_stripe_amount,
    retrieve_payment_intent,
    to_stripe_amount,
)
from payments.models import PaymentStatus, PaymentTransaction
from payments.services import confirm_payment_failed, confirm_payment_success

logger = logging.getLogger(__name__)

GATEWAY_KEY = "stripe"


@dataclass(frozen=True)
class ReconcileResult:
    """Outcome of reconciling one Stripe object. ``outcome`` is a stable string."""

    outcome: str
    payment_transaction: PaymentTransaction | None = None


def _find_transaction(*, intent_id: str) -> PaymentTransaction | None:
    if not intent_id:
        return None
    return (
        PaymentTransaction.objects.select_related("order", "currency")
        .filter(gateway_key=GATEWAY_KEY, external_intent_id=intent_id)
        .last()
    )


def _record_anomaly(payment_tx: PaymentTransaction, reason: str) -> None:
    """Persist why a Stripe-succeeded payment was NOT confirmed, for manual review."""
    metadata = dict(payment_tx.metadata or {})
    metadata["stripe_anomaly"] = reason
    payment_tx.metadata = metadata
    payment_tx.save(update_fields=["metadata", "updated_at"])


def _mismatch_reason(intent: dict[str, Any], payment_tx: PaymentTransaction) -> str:
    """Return why ``intent`` cannot settle ``payment_tx`` ('' when it can)."""
    if intent.get("id") != payment_tx.external_intent_id:
        return f"intent id {intent.get('id')} != recorded {payment_tx.external_intent_id}"

    code = payment_tx.currency.code
    if (intent.get("currency") or "").upper() != code.upper():
        return f"currency {intent.get('currency')} != {code}"

    expected = to_stripe_amount(payment_tx.amount, code)
    paid = intent.get("amount_received") or intent.get("amount")
    if paid != expected:
        return f"amount {paid} != expected {expected}"

    order = payment_tx.order
    if order is not None and (
        order.total_amount != payment_tx.amount
        or (order.currency_id and order.currency_id != payment_tx.currency_id)
    ):
        return "order total/currency changed after the payment was initiated"

    meta_order_id = (intent.get("metadata") or {}).get("order_id")
    if meta_order_id and order is not None and str(order.pk) != str(meta_order_id):
        return f"metadata order_id {meta_order_id} != order {order.pk}"

    return ""


def reconcile_payment_intent(intent: dict[str, Any]) -> ReconcileResult:
    """
    Apply the state of a (trusted) PaymentIntent dict to our records. Idempotent.

    Outcomes: ``confirmed``, ``already_confirmed``, ``mismatch`` (succeeded at Stripe
    but not confirmed here), ``failed``, ``retry_allowed``, ``processing``,
    ``unmatched`` (no transaction for this intent), ``ignored``.
    """
    intent_id = intent.get("id", "")
    status = intent.get("status", "")
    payment_tx = _find_transaction(intent_id=intent_id)
    if payment_tx is None:
        logger.warning("Stripe intent %s (status=%s) matches no PaymentTransaction", intent_id, status)
        return ReconcileResult("unmatched")

    if status == "succeeded":
        if payment_tx.status == PaymentStatus.SUCCESS:
            return ReconcileResult("already_confirmed", payment_tx)
        reason = _mismatch_reason(intent, payment_tx)
        if reason:
            logger.error(
                "Stripe intent %s succeeded but NOT confirmed for tx=%s: %s",
                intent_id, payment_tx.pk, reason,
            )
            _record_anomaly(payment_tx, reason)
            return ReconcileResult("mismatch", payment_tx)
        confirm_payment_success(payment_transaction=payment_tx, external_transaction_id=intent_id)
        logger.info("Stripe intent %s confirmed order %s (tx=%s)", intent_id, payment_tx.order_id, payment_tx.pk)
        return ReconcileResult("confirmed", payment_tx)

    if status == "canceled":
        if payment_tx.status == PaymentStatus.PENDING:
            confirm_payment_failed(payment_transaction=payment_tx)
        return ReconcileResult("failed", payment_tx)

    if status == "requires_payment_method" and intent.get("last_payment_error"):
        # A declined attempt is not terminal: the same intent can be retried with
        # another card, so the transaction stays PENDING. Keep the reason for support.
        error = intent["last_payment_error"]
        metadata = dict(payment_tx.metadata or {})
        metadata["last_payment_error"] = {
            "code": error.get("code", ""),
            "decline_code": error.get("decline_code", ""),
            "message": error.get("message", ""),
        }
        payment_tx.metadata = metadata
        payment_tx.save(update_fields=["metadata", "updated_at"])
        return ReconcileResult("retry_allowed", payment_tx)

    if status in ("processing", "requires_action", "requires_confirmation", "requires_capture"):
        return ReconcileResult("processing", payment_tx)

    return ReconcileResult("ignored", payment_tx)


def sync_order_payment_from_stripe(*, order, payment_intent_id: str = "") -> ReconcileResult | None:
    """
    Browser-return path: ask Stripe (never the URL) what happened to this order's
    payment and reconcile. Returns None when there is nothing to check or Stripe
    cannot be reached — the webhook will still settle the order.

    ``payment_intent_id`` (from the redirect URL) is used only to choose among this
    order's own Stripe transactions, never as proof of payment.
    """
    candidates = PaymentTransaction.objects.filter(order=order, gateway_key=GATEWAY_KEY).exclude(
        external_intent_id=""
    )
    payment_tx = None
    if payment_intent_id:
        payment_tx = candidates.filter(external_intent_id=payment_intent_id).last()
    if payment_tx is None:
        payment_tx = candidates.last()
    if payment_tx is None:
        return None
    if payment_tx.status == PaymentStatus.SUCCESS:
        return ReconcileResult("already_confirmed", payment_tx)

    try:
        intent = retrieve_payment_intent(payment_tx.external_intent_id)
    except (stripe.StripeError, ValueError):
        logger.exception("Could not fetch Stripe intent %s for order %s", payment_tx.external_intent_id, order.pk)
        return None
    return reconcile_payment_intent(intent)


@transaction.atomic
def handle_charge_refunded(charge: dict[str, Any]) -> ReconcileResult:
    """
    Mirror a Stripe-side refund (dashboard or API) onto our records.

    A full refund marks the transaction REFUNDED and moves the order to REFUNDED;
    a partial refund is recorded in the transaction metadata only.
    """
    intent_id = charge.get("payment_intent") or ""
    payment_tx = _find_transaction(intent_id=intent_id)
    if payment_tx is None:
        logger.warning("Stripe charge.refunded for unknown intent %s", intent_id)
        return ReconcileResult("unmatched")

    payment_tx = PaymentTransaction.objects.select_for_update().get(pk=payment_tx.pk)
    refunded_minor = charge.get("amount_refunded", 0)
    metadata = dict(payment_tx.metadata or {})
    metadata["amount_refunded"] = str(from_stripe_amount(refunded_minor, payment_tx.currency.code))
    payment_tx.metadata = metadata

    fully_refunded = bool(charge.get("refunded")) or refunded_minor >= to_stripe_amount(
        payment_tx.amount, payment_tx.currency.code
    )
    if not fully_refunded:
        payment_tx.save(update_fields=["metadata", "updated_at"])
        return ReconcileResult("partial_refund", payment_tx)

    payment_tx.status = PaymentStatus.REFUNDED
    payment_tx.save(update_fields=["status", "metadata", "updated_at"])

    from orders.models import OrderStatus
    from orders.services import transition_order_status

    order = payment_tx.order
    if order.order_status != OrderStatus.REFUNDED:
        transition_order_status(
            order=order,
            new_status=OrderStatus.REFUNDED,
            note="Refunded via Stripe",
            force=True,
        )
    return ReconcileResult("refunded", payment_tx)
