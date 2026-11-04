"""Storefront template helpers for currency display."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from django import template

register = template.Library()


def _format_money_amount(value: Decimal) -> str:
    """Format money without trailing .00; keep decimals only when needed."""
    quantized = value.quantize(Decimal("0.01"), ROUND_HALF_UP)
    if quantized == quantized.to_integral_value():
        return f"{int(quantized)}"
    text = f"{quantized:.2f}".rstrip("0").rstrip(".")
    return text


@register.filter
def in_display_currency(amount, currency) -> str:
    """Convert a base-currency amount into the active display currency."""
    if amount is None or amount == "":
        return ""
    if currency is None:
        try:
            return _format_money_amount(Decimal(str(amount)))
        except Exception:
            return str(amount)
    base = Decimal(str(amount))
    rate = Decimal(str(currency.exchange_rate_to_base))
    if rate <= 0:
        return _format_money_amount(base)
    converted = (base / rate).quantize(Decimal("0.01"), ROUND_HALF_UP)
    return _format_money_amount(converted)


@register.simple_tag
def money_label(amount, currency) -> str:
    """Format amount with currency symbol for templates."""
    symbol = getattr(currency, "symbol", "")
    value = in_display_currency(amount, currency)
    return f"{symbol} {value}".strip()
