"""Tests for served-country detection (India / UAE) and per-country catalog availability."""

from decimal import Decimal

from django.test import TestCase

from catalog.models import Category, Collection, Product
from catalog.selectors import get_category_tree, get_plp_products
from core.country import available_in_country, normalize_country, reset_current_country, set_current_country
from core.models import Country, Currency


def _product(category, sku, **extra):
    return Product.objects.create(
        name=sku, slug=sku.lower(), sku=sku, category=category,
        base_price=Decimal("100"), base_price_ae=Decimal("10"), mrp=Decimal("100"),
        purchase_price=Decimal("50"), **extra,
    )


class CountryDetectionTests(TestCase):
    def setUp(self):
        Currency.objects.update_or_create(code="INR", defaults={"symbol": "₹", "exchange_rate_to_base": 1, "is_default": True, "is_active": True})
        Currency.objects.update_or_create(code="AED", defaults={"symbol": "AED", "exchange_rate_to_base": Decimal("23.9"), "is_active": True})

    def test_normalize_country(self):
        self.assertEqual(normalize_country("ae"), "AE")
        self.assertEqual(normalize_country("US"), "IN")
        self.assertEqual(normalize_country(""), "IN")
        self.assertEqual(normalize_country(None), "IN")

    def test_seeded_countries(self):
        self.assertEqual(set(Country.objects.values_list("code", flat=True)), {"IN", "AE"})

    def test_request_country_detected_and_manual_switch_wins(self):
        self.client.get("/about-us/", HTTP_CF_IPCOUNTRY="AE")
        self.assertEqual(self.client.session["visitor_country"], "AE")
        self.assertEqual(self.client.session["storefront_currency"], "AED")

        self.client.post("/preferences/country/", {"country": "IN"})
        self.client.get("/about-us/", HTTP_CF_IPCOUNTRY="AE")
        self.assertEqual(self.client.session["visitor_country"], "IN")
        self.assertEqual(self.client.session["storefront_currency"], "INR")

    def test_unserved_country_choice_is_ignored(self):
        self.client.get("/about-us/", HTTP_CF_IPCOUNTRY="AE")
        self.client.post("/preferences/country/", {"country": "US"})
        self.assertEqual(self.client.session["visitor_country"], "AE")


class CountryAvailabilityTests(TestCase):
    def setUp(self):
        self.india = Country.objects.get(code="IN")
        self.uae = Country.objects.get(code="AE")
        self.cat = Category.objects.create(name="Sarees", slug="sarees")
        self.everywhere = _product(self.cat, "ALL")
        self.in_only = _product(self.cat, "INONLY")
        self.in_only.countries.add(self.india)
        self.ae_only = _product(self.cat, "AEONLY")
        self.ae_only.countries.add(self.uae)

    def _skus(self, country):
        return set(available_in_country(Product.objects.all(), country).values_list("sku", flat=True))

    def test_empty_countries_means_available_everywhere(self):
        self.assertEqual(self._skus("IN"), {"ALL", "INONLY"})
        self.assertEqual(self._skus("AE"), {"ALL", "AEONLY"})

    def test_product_in_both_countries_is_not_duplicated(self):
        self.in_only.countries.add(self.uae)
        rows = list(available_in_country(Product.objects.filter(sku="INONLY"), "AE"))
        self.assertEqual(len(rows), 1)

    def test_plp_is_filtered_by_current_country(self):
        token = set_current_country("AE")
        try:
            skus = {p.sku for p in get_plp_products()["results"]}
        finally:
            reset_current_country(token)
        self.assertEqual(skus, {"ALL", "AEONLY"})

    def test_category_tree_and_collections_respect_country(self):
        ae_cat = Category.objects.create(name="Abayas", slug="abayas")
        ae_cat.countries.add(self.uae)
        Collection.objects.create(name="Ramadan", slug="ramadan").countries.add(self.uae)

        for code, expect_abayas in (("AE", True), ("IN", False)):
            token = set_current_country(code)
            try:
                names = {c.name for c in get_category_tree()}
                cols = set(available_in_country(Collection.objects.all()).values_list("slug", flat=True))
            finally:
                reset_current_country(token)
            self.assertEqual("Abayas" in names, expect_abayas, code)
            self.assertEqual("ramadan" in cols, expect_abayas, code)
            self.assertIn("Sarees", names)
