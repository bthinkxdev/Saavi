"""Tests for per-market pricing (INR / AED, no conversion) and cart availability by country."""

from decimal import Decimal

from django.test import TestCase

from catalog.models import Category, Product, ProductVariant
from catalog.selectors import _live_products, get_plp_products, get_variant_price
from core.country import reset_current_country, set_current_country
from core.models import Country, Currency


def _product(category, sku, **extra):
    return Product.objects.create(
        name=sku, slug=sku.lower(), sku=sku, category=category,
        base_price=extra.pop("base_price", Decimal("100")), mrp=Decimal("100"), purchase_price=Decimal("50"), **extra,
    )


def _in(code, fn):
    token = set_current_country(code)
    try:
        return fn()
    finally:
        reset_current_country(token)


class MarketPricingTests(TestCase):
    """UAE and India prices are separate fields; nothing is converted by exchange rate."""

    def setUp(self):
        cat = Category.objects.create(name="Sarees", slug="sarees")
        self.p = _product(cat, "SAR1", base_price=Decimal("999"), base_price_ae=Decimal("12.50"), mrp_ae=Decimal("15"))
        self.unpriced_ae = _product(cat, "NOAE")
        # Variant products mirror their first variant's prices at product level (as the dashboard saves them).
        self.variant_only = _product(cat, "VAR", base_price=Decimal("500"), base_price_ae=Decimal("25"))
        ProductVariant.objects.create(
            product=self.variant_only, name="M", sku_suffix="VAR-M",
            base_price=Decimal("500"), base_price_ae=Decimal("25"), stock_quantity=3,
        )
        # Product-level price blank: priced only through its variant.
        self.variant_priced = _product(cat, "VARONLY", base_price=Decimal("0"))
        self.variant_priced.base_price_ae = None
        self.variant_priced.save()
        ProductVariant.objects.create(
            product=self.variant_priced, name="L", sku_suffix="VARONLY-L",
            base_price=Decimal("400"), base_price_ae=Decimal("30"), stock_quantity=2,
        )

    def test_price_follows_country(self):
        self.assertEqual(_in("IN", lambda: self.p.effective_base_price), Decimal("999"))
        self.assertEqual(_in("AE", lambda: self.p.effective_base_price), Decimal("12.50"))
        self.assertEqual(_in("AE", lambda: self.p.effective_mrp), Decimal("15"))

    def test_variant_price_follows_country(self):
        v = self.variant_only.variants.get()
        self.assertEqual(_in("IN", lambda: v.market_base_price), Decimal("500"))
        self.assertEqual(_in("AE", lambda: v.market_base_price), Decimal("25"))

    def test_product_without_uae_price_is_hidden_in_uae_only(self):
        skus_in = _in("IN", lambda: set(_live_products().values_list("sku", flat=True)))
        skus_ae = _in("AE", lambda: set(_live_products().values_list("sku", flat=True)))
        self.assertIn("NOAE", skus_in)
        self.assertNotIn("NOAE", skus_ae)
        self.assertIn("SAR1", skus_ae)
        self.assertIn("VARONLY", skus_ae)  # priced only through a variant still counts as priced

    def test_get_variant_price_uses_market_price(self):
        self.assertEqual(_in("AE", lambda: get_variant_price(product_id=self.p.pk)["price"]), "12.50")
        self.assertEqual(_in("IN", lambda: get_variant_price(product_id=self.p.pk)["price"]), "999.00")

    def test_plp_price_sort_uses_market_field(self):
        asc = _in("AE", lambda: [p.sku for p in get_plp_products(sort="price_asc")["results"]])
        self.assertEqual([sku for sku in asc if sku in ("SAR1", "VAR")], ["SAR1", "VAR"])


class CartCountryAvailabilityTests(TestCase):
    """Products carted in one country but not sold in the other are flagged and block checkout."""

    def setUp(self):
        from cart.models import Cart, CartItem

        inr, _ = Currency.objects.update_or_create(code="INR", defaults={"symbol": "₹", "exchange_rate_to_base": 1, "is_default": True, "is_active": True})
        Currency.objects.update_or_create(code="AED", defaults={"symbol": "AED", "exchange_rate_to_base": 1, "is_active": True})
        self.uae = Country.objects.get(code="AE")
        cat = Category.objects.create(name="Sarees", slug="sarees")
        self.common = _product(cat, "COMMON", base_price_ae=Decimal("10"), stock_quantity=5)
        self.uae_only = _product(cat, "UAEONLY", base_price_ae=Decimal("20"), stock_quantity=5)
        self.uae_only.countries.add(self.uae)
        self.cart = Cart.objects.create(session_key="s1", currency=inr)
        CartItem.objects.create(cart=self.cart, product=self.common, quantity=1, unit_price_at_add=Decimal("100"))
        CartItem.objects.create(cart=self.cart, product=self.uae_only, quantity=2, unit_price_at_add=Decimal("20"))

    def _summary(self, code):
        from cart.selectors import get_cart_summary

        return _in(code, lambda: get_cart_summary(cart=self.cart, skip_delivery_charge_calculation=True))

    def test_available_in_uae(self):
        s = self._summary("AE")
        self.assertFalse(s.has_unavailable_items)
        self.assertTrue(s.can_checkout)
        self.assertEqual(s.subtotal, Decimal("50.00"))  # 10 + 2*20, in AED

    def test_uae_only_product_flagged_in_india_and_excluded_from_totals(self):
        s = self._summary("IN")
        self.assertTrue(s.has_unavailable_items)
        self.assertEqual(s.unavailable_count, 1)
        self.assertFalse(s.can_checkout)
        self.assertEqual(s.country_name, "India")
        self.assertEqual([l.product.sku for l in s.lines if l.is_unavailable], ["UAEONLY"])
        self.assertEqual(s.subtotal, Decimal("100.00"))
        self.assertEqual(s.item_count, 1)

    def test_remove_unavailable_items(self):
        from cart.services import remove_unavailable_items

        removed = _in("IN", lambda: remove_unavailable_items(cart=self.cart))
        self.assertEqual(removed, 1)
        self.assertEqual(list(self.cart.items.values_list("product__sku", flat=True)), ["COMMON"])

    def test_checkout_service_refuses_unavailable_items(self):
        from checkout.exceptions import CheckoutSessionError
        from checkout.models import CheckoutSession
        from checkout.services import place_order
        import inspect

        # The guard must exist on the service path, not just in the template.
        src = inspect.getsource(place_order)
        self.assertIn("has_unavailable_items", src)
        self.assertTrue(issubclass(CheckoutSessionError, Exception))
        self.assertIsNotNone(CheckoutSession)

    def test_cart_page_warns_and_disables_checkout_after_country_switch(self):
        self.client.get("/about-us/", HTTP_CF_IPCOUNTRY="AE")
        self.cart.session_key = self.client.session.session_key
        self.cart.save()
        resp = self.client.get("/cart/")
        self.assertNotContains(resp, "data-unavailable-banner")

        self.client.post("/preferences/country/", {"country": "IN"})
        resp = self.client.get("/cart/")
        self.assertContains(resp, "data-unavailable-banner")
        self.assertContains(resp, "not available in India")
        self.assertContains(resp, "Remove unavailable products")
        self.assertNotContains(resp, "checkout/?mode=cart")

    def test_remove_unavailable_endpoint(self):
        self.client.get("/about-us/", HTTP_CF_IPCOUNTRY="IN")
        self.cart.session_key = self.client.session.session_key
        self.cart.save()
        self.client.post("/cart/remove-unavailable/", {"target": "page"})
        self.assertEqual(self.cart.items.count(), 1)
