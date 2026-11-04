"""Storefront middleware."""

from __future__ import annotations

from core.currency import COUNTRY_SESSION_KEY, SESSION_KEY, currency_code_for_country, detect_country


class GeoCurrencyMiddleware:
    """On a visitor's first request, pick their currency from their country.

    The choice is stored in the session, so the header currency switcher
    (core.views.set_currency_view) can override it at any time.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        session = getattr(request, "session", None)
        if session is not None and SESSION_KEY not in session and not request.path.startswith(
            ("/static/", "/media/", "/dashboard/", "/admin/", "/payments/webhooks/")
        ):
            from core.selectors import get_currency_by_code

            country = detect_country(request)
            session[COUNTRY_SESSION_KEY] = country
            currency = get_currency_by_code(code=currency_code_for_country(country)) if country else None
            if currency is not None and currency.is_active:
                session[SESSION_KEY] = currency.code
        return self.get_response(request)
