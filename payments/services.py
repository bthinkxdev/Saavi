"""Write operations and business rules for the payments app."""

from __future__ import annotations

import hashlib
import hmac
import logging
from decimal import InvalidOperation
from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.db import transaction

from payments.models import (
    PaymentStatus,
    PaymentTransaction,
)
from payments.registry import get_payment_adapter

if TYPE_CHECKING:
    from orders.models import Order

logger = logging.getLogger(__name__)


@transaction.atomic
def confirm_payment_success(
    *,
    payment_transaction: PaymentTransaction,
    external_transaction_id: str = "",
) -> PaymentTransaction:
    """
    Single convergence point for successful payment — sync or async, browser
    callback or webhook.

    Idempotent and concurrency-safe: reloads the row under select_for_update so
    concurrent callers (browser callback racing the Razorpay webhook, or two
    webhook deliveries) serialize on it. Whichever acquires the lock second sees
    status already SUCCESS and returns without repeating the order transition,
    cart clearing, or confirmation email.

    ``external_transaction_id``, if given, is recorded as part of this exact
    confirmation only — never applied once the transaction is already SUCCESS,
    so a late or duplicate event carrying a *different* payment id (e.g. a
    stale retry, or a second attempt against the same Razorpay order) can't
    silently overwrite the id that actually triggered confirmation.
    """
    payment_transaction = PaymentTransaction.objects.select_for_update().get(pk=payment_transaction.pk)
    if payment_transaction.status == PaymentStatus.SUCCESS:
        return payment_transaction

    update_fields = ["status", "updated_at"]
    payment_transaction.status = PaymentStatus.SUCCESS
    if external_transaction_id:
        payment_transaction.external_transaction_id = external_transaction_id
        update_fields.append("external_transaction_id")
    payment_transaction.save(update_fields=update_fields)

    #empty and deactivate the cart now that payment is confirmed
    order = payment_transaction.order
    if order:
        from checkout.models import CheckoutSession, CheckoutSessionStatus
        session = CheckoutSession.objects.filter(order=order).first()
        if session:
            session.status = CheckoutSessionStatus.COMPLETED
            session.save(update_fields=["status", "updated_at"])

        if order.cart:
            cart = order.cart
            from cart.models import CartItem
            CartItem.objects.filter(cart=cart).delete()

        # auto confirm order once online payment succeeds (COD is confirmed manually by an admin)
        from orders.models import OrderStatus
        from orders.services import transition_order_status
        if payment_transaction.gateway_key != "cod" and order.order_status == OrderStatus.CHECKOUT_PENDING:
            transition_order_status(order=order, new_status=OrderStatus.CONFIRMED, note="Payment successful", force=True)

        #send order placement confirmation email
        from notifications.tasks import dispatch_order_confirmation_notification
        transaction.on_commit(
            lambda: dispatch_order_confirmation_notification.delay(order_id=order.pk)
        )

    return payment_transaction


@transaction.atomic
def confirm_payment_failed(*, payment_transaction: PaymentTransaction) -> PaymentTransaction:
    """
    Mark a payment transaction as failed.

    Idempotent and concurrency-safe like confirm_payment_success. Never
    downgrades an already-SUCCESS transaction — a late or stale payment.failed
    event must not undo a payment that already succeeded.
    """
    payment_transaction = PaymentTransaction.objects.select_for_update().get(pk=payment_transaction.pk)
    if payment_transaction.status in (PaymentStatus.SUCCESS, PaymentStatus.FAILED):
        return payment_transaction

    payment_transaction.status = PaymentStatus.FAILED
    payment_transaction.save(update_fields=["status", "updated_at"])
    return payment_transaction


@transaction.atomic
def process_payment(
    *,
    order: Order,
    gateway_key: str,
    payment_data: dict[str, Any],
) -> PaymentTransaction:
    """
    Process payment via registry-selected adapter.

    Writes PaymentTransaction as PENDING immediately. Sync gateways capture
    inline; async gateways complete via webhook → confirm_payment_success.
    """
    adapter = get_payment_adapter(gateway_key=gateway_key)

    #retire previous abandoned attempts: mark them failed and, where the processor
    #keeps an intent payable after we abandon it, cancel it there too so a stale
    #intent can never be paid in parallel with the new one
    superseded = list(
        PaymentTransaction.objects.filter(order=order, status=PaymentStatus.PENDING)
    )
    for previous in superseded:
        previous.status = PaymentStatus.FAILED
        previous.save(update_fields=["status", "updated_at"])
        if previous.external_intent_id:
            try:
                get_payment_adapter(gateway_key=previous.gateway_key).cancel_payment_intent(
                    intent_id=previous.external_intent_id
                )
            except KeyError:
                pass

    from core.currency import convert_from_base

    # Orders store base-currency amounts; charge in the customer's currency.
    charge_amount = convert_from_base(order.total_amount, order.currency)

    payment_tx = PaymentTransaction.objects.create(
        order=order,
        gateway_key=gateway_key,
        amount=charge_amount,
        currency=order.currency,
        status=PaymentStatus.PENDING,
        metadata={"order_id": order.pk, "order_number": order.order_number, **payment_data},
    )
    metadata = {
        "order_id": order.pk,
        "order_number": order.order_number,
        "payment_transaction_id": payment_tx.pk,
        **payment_data,
    }

    intent = adapter.create_payment_intent(
        amount=charge_amount,
        currency=order.currency.code,
        metadata=metadata,
    )
    payment_tx.external_intent_id = intent.intent_id
    payment_tx.metadata = intent.metadata
    payment_tx.save(update_fields=["external_intent_id", "metadata", "updated_at"])

    if adapter.is_async:
        return payment_tx

    capture = adapter.capture(intent_id=intent.intent_id)

    payment_tx.external_transaction_id = capture.transaction_id
    payment_tx.metadata.update(capture.metadata)
    payment_tx.save(update_fields=["external_transaction_id", "metadata", "updated_at"])

    if capture.success:
        confirm_payment_success(payment_transaction=payment_tx)
        #COD checkouts are successful, but the payment itself should remain Pending until the admin manually collects the cash and marks it as Success.
        if gateway_key == "cod":
            payment_tx.status = PaymentStatus.PENDING
            payment_tx.save(update_fields=["status", "updated_at"])
    else:
        confirm_payment_failed(payment_transaction=payment_tx)

    return payment_tx


@transaction.atomic
def handle_payment_webhook(
    *,
    gateway_key: str,
    payload: bytes,
    signature: str,
) -> PaymentTransaction | None:
    """
    Verify webhook via adapter and converge on confirm_payment_success/failed.
    """
    adapter = get_payment_adapter(gateway_key=gateway_key)
    event = adapter.verify_webhook(payload=payload, signature=signature)

    intent_id = event.get("intent_id", "")
    payment_tx = PaymentTransaction.objects.filter(
        external_intent_id=intent_id,
        gateway_key=gateway_key,
    ).first()
    if payment_tx is None:
        return None

    if event.get("status") == "success":
        return confirm_payment_success(
            payment_transaction=payment_tx,
            external_transaction_id=event.get("transaction_id", ""),
        )

    return confirm_payment_failed(payment_transaction=payment_tx)


