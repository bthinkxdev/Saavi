"""Served-country resolution: which market (India / UAE) the current request belongs to.

The middleware stores the resolved code in a context variable so selectors can
filter catalog data without every caller threading ``request`` through.
"""

from __future__ import annotations

from contextvars import ContextVar

from django.core.cache import cache

SUPPORTED_COUNTRIES = ("IN", "AE")
DEFAULT_COUNTRY = "IN"
COUNTRIES_CACHE_KEY = "core:active_countries:v1"
COUNTRIES_TTL = 300

_current_country: ContextVar[str] = ContextVar("current_country", default=DEFAULT_COUNTRY)


def normalize_country(code: str | None) -> str:
    """Return ``code`` when it is a served country, else the default country."""
    code = (code or "").strip().upper()
    return code if code in SUPPORTED_COUNTRIES else DEFAULT_COUNTRY


def get_current_country() -> str:
    return _current_country.get()


def set_current_country(code: str):
    """Bind the country for this request; returns a token for ``reset_current_country``."""
    return _current_country.set(normalize_country(code))


def reset_current_country(token) -> None:
    _current_country.reset(token)


def price_attr(name: str, country: str | None = None) -> str:
    """Model field holding ``name`` (e.g. base_price) for the market: UAE uses the ``_ae`` twin."""
    country = normalize_country(country) if country else get_current_country()
    return f"{name}_ae" if country == "AE" else name


def market_value(obj, name: str, country: str | None = None):
    """Value of a per-market price field for ``country`` (None when the UAE price isn't set)."""
    return getattr(obj, price_attr(name, country))


def get_active_countries() -> list:
    """Active Country rows, cached briefly (header selector, validation)."""
    from core.models import Country

    cached = cache.get(COUNTRIES_CACHE_KEY)
    if cached is None:
        cached = list(Country.objects.filter(is_active=True).select_related("currency"))
        cache.set(COUNTRIES_CACHE_KEY, cached, COUNTRIES_TTL)
    return cached


def invalidate_countries_cache() -> None:
    cache.delete(COUNTRIES_CACHE_KEY)


def available_in_country(queryset, country: str | None = None):
    """Limit a Product/Category/Collection queryset to rows sold in ``country``.

    A row with no countries set is available everywhere. Uses subqueries rather
    than joins so existing aggregates/annotations on the queryset are unaffected.
    """
    from django.db.models import Q

    model = queryset.model
    country = normalize_country(country) if country else get_current_country()
    # Built from the model (not the auto-created M2M through class) so the
    # queryset stays picklable for cached results such as the category tree.
    restricted = model._base_manager.filter(countries__isnull=False).values("pk")
    sold_here = model._base_manager.filter(countries__code=country).values("pk")
    return queryset.filter(~Q(pk__in=restricted) | Q(pk__in=sold_here))
