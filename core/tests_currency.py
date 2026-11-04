"""Tests for Saavi multi-currency: country mapping, conversion, geo middleware."""

from decimal import Decimal

from django.test import TestCase

from core.currency import convert_from_base, currency_code_for_country
from core.models import Currency


class CurrencyHelpersTests(TestCase):
    def test_country_mapping(self):
        self.assertEqual(currency_code_for_country("IN"), "INR")
        self.assertEqual(currency_code_for_country("AE"), "AED")
        self.assertEqual(currency_code_for_country("FR"), "EUR")
        self.assertEqual(currency_code_for_country("US"), "USD")
        self.assertEqual(currency_code_for_country(""), "USD")

    def test_convert_from_base(self):
        aed = Currency(code="AED", symbol="AED", exchange_rate_to_base=Decimal("23.9"))
        self.assertEqual(convert_from_base(Decimal("2390"), aed), Decimal("100.00"))
        self.assertEqual(convert_from_base(Decimal("999"), None), Decimal("999.00"))


class GeoCurrencyMiddlewareTests(TestCase):
    def setUp(self):
        Currency.objects.update(is_active=False, is_default=False)
        Currency.objects.update_or_create(code="INR", defaults={"symbol": "₹", "exchange_rate_to_base": 1, "is_default": True, "is_active": True})
        Currency.objects.update_or_create(code="AED", defaults={"symbol": "AED", "exchange_rate_to_base": Decimal("23.9"), "is_active": True})

    def test_uae_visitor_gets_aed_and_switch_overrides(self):
        self.client.get("/about-us/", HTTP_CF_IPCOUNTRY="AE")
        self.assertEqual(self.client.session.get("storefront_currency"), "AED")
        self.client.post("/preferences/currency/", {"currency": "INR"})
        self.client.get("/about-us/", HTTP_CF_IPCOUNTRY="AE")
        self.assertEqual(self.client.session.get("storefront_currency"), "INR")

    def test_unsupported_currency_is_not_forced(self):
        self.client.get("/about-us/", HTTP_CF_IPCOUNTRY="US")  # USD not active here
        self.assertIsNone(self.client.session.get("storefront_currency"))
