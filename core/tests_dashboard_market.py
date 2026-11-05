"""Dashboard product form: UAE price and country availability."""

from django.contrib.auth import get_user_model
from django.test import TestCase

from catalog.models import Category, Product
from core.models import Country

MGMT = {f"{p}-{k}": v for p in ("images", "videos", "specifications")
        for k, v in (("TOTAL_FORMS", "0"), ("INITIAL_FORMS", "0"), ("MIN_NUM_FORMS", "0"), ("MAX_NUM_FORMS", "1000"))}


class DashboardMarketFieldsTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_superuser("smoke", "s@example.com", "pw12345!")
        self.client.force_login(user)
        self.cat = Category.objects.create(name="Sarees", slug="sarees")

    def test_form_renders_with_aed_fields(self):
        resp = self.client.get("/dashboard/product/create/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Base price (AED)")
        self.assertContains(resp, "Available in")

    def test_create_with_uae_price_and_country(self):
        uae = Country.objects.get(code="AE")
        data = {
            "name": "Abaya", "sku": "ABY1", "category": self.cat.pk, "base_price": "0", "mrp": "0",
            "base_price_ae": "99", "mrp_ae": "120", "purchase_price": "10", "stock_quantity": "4",
            "low_stock_threshold": "1", "is_active": "on", "countries": [uae.pk], **MGMT,
        }
        resp = self.client.post("/dashboard/product/create/", data)
        p = Product.objects.filter(sku="ABY1").first()
        self.assertIsNotNone(p, getattr(resp, "context", None) and resp.context["form"].errors)
        self.assertEqual(str(p.base_price_ae), "99.00")
        self.assertEqual(list(p.countries.values_list("code", flat=True)), ["AE"])

    def test_uae_country_requires_uae_price(self):
        uae = Country.objects.get(code="AE")
        data = {
            "name": "Abaya", "sku": "ABY2", "category": self.cat.pk, "base_price": "50", "mrp": "60",
            "purchase_price": "10", "stock_quantity": "4", "low_stock_threshold": "1", "is_active": "on",
            "countries": [uae.pk], **MGMT,
        }
        self.client.post("/dashboard/product/create/", data)
        self.assertFalse(Product.objects.filter(sku="ABY2").exists())
