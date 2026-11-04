"""Multi-currency helpers: visitor country detection and base-currency conversion.

Prices are stored in the base currency (the one whose exchange_rate_to_base is 1).
A Currency's ``exchange_rate_to_base`` is how many base units one unit of that
currency is worth, so ``display = base / rate``.
"""

from __future__ import annotations

import logging
from decimal import ROUND_HALF_UP, Decimal

import requests
from django.core.cache import cache

logger = logging.getLogger(__name__)

SESSION_KEY = "storefront_currency"
COUNTRY_SESSION_KEY = "visitor_country"

EUROZONE = {
    "AT", "BE", "CY", "DE", "EE", "ES", "FI", "FR", "GR", "HR", "IE", "IT",
    "LT", "LU", "LV", "MT", "NL", "PT", "SI", "SK",
}

# Headers set by Cloudflare, Nginx GeoIP2, CloudFront or Vercel in front of the app.
_COUNTRY_HEADERS = (
    "HTTP_CF_IPCOUNTRY",
    "HTTP_X_COUNTRY_CODE",
    "HTTP_CLOUDFRONT_VIEWER_COUNTRY",
    "HTTP_X_VERCEL_IP_COUNTRY",
)


def currency_code_for_country(country: str) -> str:
    """Map an ISO country code to the storefront currency (India→INR, UAE→AED, EU→EUR, else USD)."""
    country = (country or "").upper()
    if country == "IN":
        return "INR"
    if country == "AE":
        return "AED"
    if country in EUROZONE:
        return "EUR"
    return "USD"


def _client_ip(request) -> str:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def _is_private_ip(ip: str) -> bool:
    import ipaddress

    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True
    return addr.is_private or addr.is_loopback or addr.is_reserved


def lookup_country_by_ip(ip: str) -> str:
    """Resolve an IP to a country code via a free GeoIP API (cached for a day)."""
    if not ip or _is_private_ip(ip):
        return ""
    cache_key = f"geoip:country:{ip}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    country = ""
    try:
        resp = requests.get(f"https://ipapi.co/{ip}/country/", timeout=1.5)
        if resp.ok and len(resp.text.strip()) == 2:
            country = resp.text.strip().upper()
    except requests.RequestException:
        logger.info("GeoIP lookup failed for %s", ip)
    cache.set(cache_key, country, 60 * 60 * 24)
    return country


def detect_country(request) -> str:
    """Best-effort visitor country: proxy/CDN headers first, then GeoIP lookup."""
    for header in _COUNTRY_HEADERS:
        value = (request.META.get(header) or "").strip().upper()
        if len(value) == 2 and value not in ("XX", "T1"):
            return value
    return lookup_country_by_ip(_client_ip(request))


def convert_from_base(amount, currency) -> Decimal:
    """Convert a base-currency amount into ``currency`` (2dp, half-up)."""
    value = Decimal(str(amount or 0))
    if currency is None:
        return value.quantize(Decimal("0.01"), ROUND_HALF_UP)
    rate = Decimal(str(currency.exchange_rate_to_base or 0))
    if rate <= 0:
        return value.quantize(Decimal("0.01"), ROUND_HALF_UP)
    return (value / rate).quantize(Decimal("0.01"), ROUND_HALF_UP)


def update_exchange_rates() -> dict[str, str]:
    """Refresh exchange_rate_to_base for every auto-updating currency from open.er-api.com."""
    from django.utils import timezone

    from core.models import Currency

    base = Currency.objects.filter(is_default=True).first()
    if base is None:
        logger.warning("No default (base) currency configured; skipping exchange-rate update.")
        return {}
    try:
        resp = requests.get(f"https://open.er-api.com/v6/latest/{base.code}", timeout=10)
        resp.raise_for_status()
        rates = resp.json().get("rates") or {}
    except (requests.RequestException, ValueError):
        logger.exception("Exchange-rate fetch failed")
        return {}

    updated: dict[str, str] = {}
    for currency in Currency.objects.filter(auto_update_rate=True).exclude(pk=base.pk):
        per_base = rates.get(currency.code)
        if not per_base:
            continue
        currency.exchange_rate_to_base = (Decimal("1") / Decimal(str(per_base))).quantize(Decimal("0.00000001"))
        currency.rate_updated_at = timezone.now()
        currency.save(update_fields=["exchange_rate_to_base", "rate_updated_at", "updated_at"])
        updated[currency.code] = str(currency.exchange_rate_to_base)
    return updated
