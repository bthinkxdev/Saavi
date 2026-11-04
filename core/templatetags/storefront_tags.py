"""Storefront template helpers for currency display."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from django import template

register = template.Library()


def _format_money_amount(value: Decimal) -> str:
    """Format money without trailing .00; keep decimals only when needed."""
    quantized = value.quantize(Decimal("0.01"), ROUND_HALF_UP)
    if quantized == quantized.to_integral_value():
        return f"{int(quantized):,}"
    return f"{quantized:,.2f}"


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
    sep = " " if symbol[-1:].isalpha() else ""
    return f"{symbol}{sep}{value}".strip()


@register.filter
def discount_percent(price, mrp) -> int:
    """Whole-number % saved going from ``mrp`` down to ``price`` (0 when no discount)."""
    try:
        price, mrp = Decimal(str(price)), Decimal(str(mrp))
    except Exception:
        return 0
    if not mrp or mrp <= price:
        return 0
    return int(((mrp - price) / mrp * 100).quantize(Decimal("1"), ROUND_HALF_UP))


@register.filter
def times(value, factor):
    """Multiply two numbers (Decimal-safe) for line totals in templates."""
    try:
        return Decimal(str(value)) * Decimal(str(factor))
    except Exception:
        return value


@register.filter
def charged_amount(amount, currency) -> str:
    """Plain numeric amount in ``currency`` (no symbol/commas) — safe for JS/analytics."""
    from core.currency import convert_from_base

    return str(convert_from_base(amount, currency))


@register.filter
def plus_days(value, days):
    """Date ``days`` after ``value`` (for estimated-delivery ranges)."""
    from datetime import timedelta

    try:
        return value + timedelta(days=int(days))
    except Exception:
        return value
