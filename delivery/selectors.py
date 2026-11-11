"""Read-only query functions for the delivery app; views must not call the ORM directly."""

from __future__ import annotations

from decimal import Decimal


def get_delivery_charge(*, subtotal: Decimal, address=None, city=None, is_cod: bool = False) -> Decimal:
    """
    Return delivery charge based on SiteSettings and City overrides.
    """
    from core.models import SiteSettings
    from delivery.models import City

    if subtotal <= 0:
        return Decimal("0.00")

    settings = SiteSettings.objects.first()
    if not settings:
        return Decimal("0.00")

    from core.country import get_current_country
    from core.services import market_setting

    free_threshold = market_setting(settings, "free_shipping_threshold")
    if free_threshold is not None and free_threshold > 0 and subtotal >= free_threshold:
        return Decimal("0.00")

    target_city_name = None
    if isinstance(city, City):
        target_city_name = city.name
    elif isinstance(city, str) and city.strip():
        target_city_name = city.strip()
    elif address:
        if isinstance(address, str):
            target_city_name = address.strip()
        elif isinstance(address, dict):
            target_city_name = address.get("city")
        elif hasattr(address, "city") and address.city:
            target_city_name = address.city

    charge = market_setting(settings, "default_shipping_charge") or Decimal("0.00")

    # City overrides match the current market's country
    if target_city_name:
        current_code = get_current_country()
        city_obj = City.objects.filter(
            name__iexact=target_city_name,
            country__code=current_code,
            is_active=True,
        ).first()
        if city_obj:
            charge = city_obj.delivery_charge_base

    if is_cod and getattr(settings, "enable_cod", True):
        charge += settings.cod_delivery_charge

    return charge

