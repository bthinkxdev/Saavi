"""Payment gateway registry — checkout selects by string key only."""

from __future__ import annotations

from typing import TYPE_CHECKING

from payments.adapters.concrete import (
    ApplePayAdapter,
    CardGatewayAdapter,
    GooglePayAdapter,
    CashOnDeliveryAdapter,
    RazorpayAdapter,
    RazorpayUPIAdapter,
    RazorpayCardAdapter,
    RazorpayNetbankingAdapter,
    RazorpayWalletAdapter,
    AfterpayAdapter,
)
from payments.adapters.cybersource import CyberSourceCardAdapter
from payments.adapters.stripe import StripePaymentAdapter

if TYPE_CHECKING:
    from payments.adapters.base import PaymentGatewayAdapter

PAYMENT_GATEWAYS: dict[str, PaymentGatewayAdapter] = {
    StripePaymentAdapter.key: StripePaymentAdapter(),
    RazorpayUPIAdapter.key: RazorpayUPIAdapter(),
    RazorpayCardAdapter.key: RazorpayCardAdapter(),
    RazorpayNetbankingAdapter.key: RazorpayNetbankingAdapter(),
    RazorpayWalletAdapter.key: RazorpayWalletAdapter(),
    CyberSourceCardAdapter.key: CyberSourceCardAdapter(),
    AfterpayAdapter.key: AfterpayAdapter(),
    CashOnDeliveryAdapter.key: CashOnDeliveryAdapter(),
}

# Gateways offered to customers at checkout. Razorpay and CyberSource adapters stay
# registered (and their webhooks live) so orders already in flight still settle, but
# they can no longer be selected for a new order.
CHECKOUT_GATEWAY_KEYS: frozenset[str] = frozenset({"stripe", "afterpay", "cod"})


def get_payment_adapter(*, gateway_key: str) -> PaymentGatewayAdapter:
    """Look up a registered adapter by key."""
    adapter = PAYMENT_GATEWAYS.get(gateway_key)
    if adapter is None:
        raise KeyError(f"Unknown payment gateway: {gateway_key}")
    return adapter


def register_payment_adapter(*, adapter: PaymentGatewayAdapter) -> None:
    """
    Register an adapter at runtime (used by tests and future plugins).

    Adding a gateway requires only registry registration — zero checkout view edits.
    """
    PAYMENT_GATEWAYS[adapter.key] = adapter
