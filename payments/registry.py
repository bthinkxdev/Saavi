"""Payment gateway registry — checkout selects by string key only."""

from __future__ import annotations

from typing import TYPE_CHECKING

from payments.adapters.concrete import CashOnDeliveryAdapter
from payments.adapters.stripe import StripePaymentAdapter

if TYPE_CHECKING:
    from payments.adapters.base import PaymentGatewayAdapter

PAYMENT_GATEWAYS: dict[str, PaymentGatewayAdapter] = {
    StripePaymentAdapter.key: StripePaymentAdapter(),
    CashOnDeliveryAdapter.key: CashOnDeliveryAdapter(),
}

# Saavi sells internationally (India, UAE, Europe, USA): Stripe is the only
# gateway offered at checkout. COD stays registered for manual admin orders.
CHECKOUT_GATEWAY_KEYS: frozenset[str] = frozenset({"stripe"})


def get_payment_adapter(*, gateway_key: str) -> PaymentGatewayAdapter:
    """Look up a registered adapter by key."""
    adapter = PAYMENT_GATEWAYS.get(gateway_key)
    if adapter is None:
        raise KeyError(f"Unknown payment gateway: {gateway_key}")
    return adapter


def register_payment_adapter(*, adapter: PaymentGatewayAdapter) -> None:
    """Register an adapter at runtime (used by tests and future plugins)."""
    PAYMENT_GATEWAYS[adapter.key] = adapter
