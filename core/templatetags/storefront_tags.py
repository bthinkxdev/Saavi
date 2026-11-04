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


_SWATCHES = {
    "purple": "#6B1F6E", "wine": "#6E1F35", "magenta": "#A3195B", "maroon": "#7A1F2B", "red": "#B01E23",
    "pink": "#D9708A", "rose": "#C9607A", "peach": "#F2B8A0", "orange": "#E2762A", "mustard": "#D9A21B",
    "yellow": "#E6B422", "gold": "#C9A04C", "golden": "#C9A04C", "cream": "#F6E8CC", "ivory": "#F8F1DF",
    "beige": "#E8D8B9", "off white": "#F4EEDF", "white": "#FFFFFF", "silver": "#C0C0C0", "grey": "#8C8C8C",
    "gray": "#8C8C8C", "black": "#1E1E1E", "navy": "#1F2E5A", "blue": "#2D5DA8", "royal blue": "#2B4FB0",
    "sky blue": "#7DB7E0", "teal": "#1C7A7A", "turquoise": "#2AA7A0", "green": "#1F6B45", "emerald": "#0F6B4E",
    "bottle green": "#0E4A33", "olive": "#6B7A2F", "mint": "#9FD8C2", "lime": "#A8C83A", "lavender": "#B8A3D6",
    "lilac": "#C3A6D8", "violet": "#6A3FA0", "brown": "#6B4226", "copper": "#B0663C", "rust": "#A34A28",
    "coffee": "#5B3A29", "multicolor": "linear-gradient(135deg,#B01E23,#E6B422,#1F6B45,#2D5DA8)",
}


@register.filter
def swatch_color(name) -> str:
    """CSS colour for a colour name (longest matching keyword wins); beige when unknown."""
    text = str(name or "").strip().lower()
    if text.startswith("#"):
        return text
    best = ""
    for key in _SWATCHES:
        if key in text and len(key) > len(best):
            best = key
    return _SWATCHES.get(best, "#E8D8B9")


@register.filter
def is_colour_name(name) -> bool:
    text = str(name or "").strip().lower()
    return text.startswith("#") or any(key in text for key in _SWATCHES)
