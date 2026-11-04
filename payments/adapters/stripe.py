"""Stripe payment gateway adapter implementation."""

from __future__ import annotations

import json
import logging
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import stripe

from payments.adapters.base import (
    PaymentCaptureResult,
    PaymentGatewayAdapter,
    PaymentIntentResult,
)

logger = logging.getLogger(__name__)

# Currencies where Stripe uses zero decimal places (e.g., 100 JPY = 100, not 10000)
ZERO_DECIMAL_CURRENCIES = {
    "BIF", "CLP", "DJF", "GNF", "JPY", "KMF", "KRW", "MGA",
    "PYG", "RWF", "UGX", "VND", "VUV", "XAF", "XOF", "XPF",
}

# Three-decimal currencies: Stripe expects the amount in thousandths, but it must be
# a multiple of 10 (i.e. effectively two-decimal precision).
THREE_DECIMAL_CURRENCIES = {"BHD", "JOD", "KWD", "OMR", "TND"}


def to_stripe_amount(amount: Decimal, currency: str) -> int:
    """Convert a Decimal amount to Stripe's smallest currency unit, rounding half-up."""
    curr = (currency or "USD").upper()
    value = Decimal(str(amount))
    if curr in ZERO_DECIMAL_CURRENCIES:
        return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if curr in THREE_DECIMAL_CURRENCIES:
        tens = (value * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        return int(tens) * 10
    return int((value * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def from_stripe_amount(amount_int: int, currency: str) -> Decimal:
    """Convert Stripe's smallest currency unit back to Decimal."""
    curr = (currency or "USD").upper()
    if curr in ZERO_DECIMAL_CURRENCIES:
        return Decimal(amount_int)
    if curr in THREE_DECIMAL_CURRENCIES:
        return Decimal(amount_int) / Decimal(1000)
    return Decimal(amount_int) / Decimal(100)


def _get_stripe_credentials() -> tuple[str, str, str]:
    """
    Retrieve Stripe credentials.
    Priority: SiteSettings database model -> django.conf.settings -> defaults.
    Returns: (publishable_key, secret_key, webhook_secret)
    """
    pub_key = ""
    sec_key = ""
    wh_secret = ""
    try:
        from core.services import get_site_settings
        site_settings = get_site_settings()
        pub_key = getattr(site_settings, "stripe_publishable_key", "") or ""
        sec_key = getattr(site_settings, "stripe_secret_key", "") or ""
        wh_secret = getattr(site_settings, "stripe_webhook_secret", "") or ""
    except Exception:
        pass

    from django.conf import settings
    if not pub_key:
        pub_key = getattr(settings, "STRIPE_PUBLIC_KEY", "")
    if not sec_key:
        sec_key = getattr(settings, "STRIPE_SECRET_KEY", "")
    if not wh_secret:
        wh_secret = getattr(settings, "STRIPE_WEBHOOK_SECRET", "")

    return pub_key.strip(), sec_key.strip(), wh_secret.strip()


def validate_stripe_keys(*, publishable_key: str, secret_key: str, webhook_secret: str) -> list[str]:
    """
    Return human-readable problems with a Stripe key set (empty list when valid).

    Checks key shape and that the publishable and secret keys belong to the same
    mode (test/live) — a mismatch makes Elements load but every payment fail.
    """
    problems: list[str] = []
    pub_mode = sec_mode = ""

    if not publishable_key.startswith(("pk_test_", "pk_live_")):
        problems.append("Publishable key must start with pk_test_ or pk_live_.")
    else:
        pub_mode = publishable_key.split("_")[1]

    if not secret_key.startswith(("sk_test_", "sk_live_", "rk_test_", "rk_live_")):
        problems.append("Secret key must start with sk_test_/sk_live_ (or rk_ for a restricted key).")
    else:
        sec_mode = secret_key.split("_")[1]

    if pub_mode and sec_mode and pub_mode != sec_mode:
        problems.append(f"Publishable key is {pub_mode} mode but secret key is {sec_mode} mode.")

    if not webhook_secret.startswith("whsec_"):
        problems.append("Webhook signing secret must start with whsec_.")

    return problems


def stripe_is_configured() -> bool:
    """True only when all three credentials are present, well-formed and mode-consistent."""
    pub_key, sec_key, wh_secret = _get_stripe_credentials()
    if not (pub_key and sec_key and wh_secret):
        return False
    return not validate_stripe_keys(
        publishable_key=pub_key, secret_key=sec_key, webhook_secret=wh_secret
    )


def retrieve_payment_intent(intent_id: str) -> dict[str, Any]:
    """Fetch a PaymentIntent from Stripe as a plain dict. Raises stripe.StripeError."""
    _, sec_key, _ = _get_stripe_credentials()
    if not sec_key:
        raise ValueError("Stripe Secret Key is not configured.")
    return stripe.PaymentIntent.retrieve(intent_id, api_key=sec_key).to_dict()


class StripePaymentAdapter(PaymentGatewayAdapter):
    """
    Modern Stripe Payment Intent adapter.
    Supports Credit/Debit Cards, Apple Pay, Google Pay, and asynchronous 3D-Secure.

    The PaymentIntent ``client_secret`` is a browser-only credential: it is returned
    in the in-memory result but never persisted in the returned ``metadata``; the pay
    page re-fetches it from Stripe on render.
    """

    key = "stripe"
    display_name = "Credit / Debit Card"
    is_async = True

    def create_payment_intent(
        self,
        *,
        amount: Decimal,
        currency: str,
        metadata: dict[str, Any] | None = None,
    ) -> PaymentIntentResult:
        """Create a Stripe PaymentIntent with automatic payment methods enabled."""
        _, sec_key, _ = _get_stripe_credentials()
        if not sec_key:
            raise ValueError("Stripe Secret Key is not configured. Please set it in Site Settings or .env.")

        metadata = dict(metadata or {})
        currency_code = (currency or "USD").lower()
        stripe_amount = to_stripe_amount(amount, currency_code)
        transaction_id = str(metadata.get("payment_transaction_id", ""))

        intent_params: dict[str, Any] = {
            "amount": stripe_amount,
            "currency": currency_code,
            "metadata": {
                "order_id": str(metadata.get("order_id", "")),
                "order_number": str(metadata.get("order_number", "")),
                "payment_transaction_id": transaction_id,
            },
            "automatic_payment_methods": {"enabled": True},
        }

        customer_email = metadata.get("customer_email") or metadata.get("email")
        if customer_email:
            intent_params["receipt_email"] = str(customer_email)

        # One PaymentTransaction == one PaymentIntent: a retried request (network
        # timeout, double submit) returns the same intent instead of creating a second.
        request_options: dict[str, Any] = {"api_key": sec_key}
        if transaction_id:
            request_options["idempotency_key"] = f"sarocchi-pi-tx-{transaction_id}"

        try:
            intent = stripe.PaymentIntent.create(**intent_params, **request_options)
        except stripe.StripeError as e:
            logger.exception("Stripe create_payment_intent failed: %s", str(e))
            raise ValueError(f"Stripe payment initiation error: {str(e)}") from e

        return PaymentIntentResult(
            intent_id=intent.id,
            client_secret=intent.client_secret or "",
            requires_webhook=True,
            metadata={
                "amount": str(amount),
                "currency": currency_code.upper(),
                **metadata,
            },
        )

    def cancel_payment_intent(self, *, intent_id: str) -> None:
        """
        Cancel an abandoned PaymentIntent so it can no longer be paid.

        Best-effort: if Stripe refuses (already succeeded/cancelled) the webhook
        remains the source of truth and reconciles the transaction.
        """
        _, sec_key, _ = _get_stripe_credentials()
        if not sec_key or not intent_id:
            return
        try:
            stripe.PaymentIntent.cancel(intent_id, api_key=sec_key)
        except stripe.InvalidRequestError as e:
            logger.warning("Stripe intent %s could not be cancelled (%s)", intent_id, str(e))
        except stripe.StripeError:
            logger.exception("Stripe cancel failed for intent %s", intent_id)

    def verify_webhook(self, *, payload: bytes, signature: str) -> dict[str, Any]:
        """
        Verify the webhook signature with the configured signing secret and return
        the parsed event as a plain dict.
        """
        _, _, wh_secret = _get_stripe_credentials()
        if not wh_secret:
            raise ValueError("Stripe Webhook Secret is not configured.")

        try:
            stripe.Webhook.construct_event(
                payload=payload,
                sig_header=signature,
                secret=wh_secret,
            )
        except stripe.SignatureVerificationError as e:
            logger.warning("Stripe webhook signature verification failed: %s", str(e))
            raise ValueError("Invalid Stripe webhook signature.") from e
        except ValueError as e:
            logger.warning("Malformed Stripe webhook payload: %s", str(e))
            raise ValueError(f"Malformed Stripe webhook: {str(e)}") from e

        # Signature verified over these exact bytes; parse them directly rather than
        # depending on the SDK's event object shape.
        return json.loads(payload.decode("utf-8"))

    def capture(self, *, intent_id: str) -> PaymentCaptureResult:
        """Capture or verify an existing PaymentIntent."""
        _, sec_key, _ = _get_stripe_credentials()
        try:
            intent = stripe.PaymentIntent.retrieve(intent_id, api_key=sec_key)
            if intent.status == "requires_capture":
                intent = stripe.PaymentIntent.capture(intent_id, api_key=sec_key)

            success = intent.status in ("succeeded", "processing")
            return PaymentCaptureResult(
                success=success,
                transaction_id=intent.id,
                metadata={"status": intent.status, "currency": intent.currency},
            )
        except stripe.StripeError as e:
            logger.exception("Stripe capture failed for intent %s: %s", intent_id, str(e))
            return PaymentCaptureResult(
                success=False,
                transaction_id=intent_id,
                metadata={"error": str(e)},
            )

    def refund(
        self,
        *,
        transaction_id: str,
        amount: Decimal,
        idempotency_key: str = "",
    ) -> PaymentCaptureResult:
        """
        Refund part of a captured PaymentIntent.

        ``amount`` must be explicit and positive (a zero/omitted amount would make
        Stripe refund the *entire* charge). ``idempotency_key`` is required and must
        be stable per logical refund request so a retry can never refund twice.
        """
        if amount is None or Decimal(str(amount)) <= Decimal("0"):
            raise ValueError("Refund amount must be greater than zero.")
        if not idempotency_key:
            raise ValueError("A stable idempotency_key is required for Stripe refunds.")

        _, sec_key, _ = _get_stripe_credentials()
        try:
            # transaction_id is the payment_intent id (pi_...)
            intent = stripe.PaymentIntent.retrieve(transaction_id, api_key=sec_key)
            refund_obj = stripe.Refund.create(
                payment_intent=transaction_id,
                amount=to_stripe_amount(amount, intent.currency),
                api_key=sec_key,
                idempotency_key=idempotency_key,
            )
            success = refund_obj.status in ("succeeded", "pending")
            return PaymentCaptureResult(
                success=success,
                transaction_id=refund_obj.id,
                metadata={"refund_status": refund_obj.status},
            )
        except stripe.StripeError as e:
            logger.exception("Stripe refund failed for %s: %s", transaction_id, str(e))
            return PaymentCaptureResult(
                success=False,
                transaction_id=transaction_id,
                metadata={"error": str(e)},
            )
