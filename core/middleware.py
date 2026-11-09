"""Storefront middleware."""

from __future__ import annotations

from core.country import normalize_country, reset_current_country, set_current_country
from core.currency import COUNTRY_SESSION_KEY, SESSION_KEY, currency_code_for_country, detect_country

_SKIP_PREFIXES = ("/static/", "/media/", "/dashboard/", "/admin/", "/payments/webhooks/")


class GeoCurrencyMiddleware:
    """Resolve the visitor's served country (India / UAE) and its currency.

    On a visitor's first request the country is detected from the request (CDN
    header, then GeoIP) and stored in the session along with that country's
    currency. A country the store doesn't serve falls back to the default. The
    header country switcher (core.views) can override it, the currency always
    follows the country, and the resolved country is bound for the request so catalog selectors can
    filter by it (see core.country.available_in_country).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        session = getattr(request, "session", None)
        if session is None or request.path.startswith(_SKIP_PREFIXES):
            return self.get_response(request)

        if COUNTRY_SESSION_KEY not in session:
            session[COUNTRY_SESSION_KEY] = normalize_country(detect_country(request))
        request.country = normalize_country(session.get(COUNTRY_SESSION_KEY))

        # Currency is never chosen on its own: it always follows the country.
        code = _currency_code(request.country)
        if code and session.get(SESSION_KEY) != code:
            session[SESSION_KEY] = code

        token = set_current_country(request.country)
        try:
            return self.get_response(request)
        finally:
            reset_current_country(token)


def _currency_code(country: str) -> str:
    """Currency for ``country``: the Country row's currency, else the static mapping."""
    from core.country import get_active_countries
    from core.selectors import get_currency_by_code

    for row in get_active_countries():
        if row.code == country and row.currency_id and row.currency.is_active:
            return row.currency.code
    currency = get_currency_by_code(code=currency_code_for_country(country))
    return currency.code if currency is not None and currency.is_active else ""
