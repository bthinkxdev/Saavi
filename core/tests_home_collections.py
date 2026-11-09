"""Homepage collections: featured grid, per-collection rails and country availability."""

from decimal import Decimal

from django.test import TestCase

from catalog.models import Category, Collection, Product, ProductImage
from catalog.selectors import get_collection_rails, get_featured_collections
from cms.models import HomepageSection, HomepageSectionType
from core.country import reset_current_country, set_current_country
from core.models import Country, Currency


def _in(code, fn):
    token = set_current_country(code)
    try:
        return fn()
    finally:
        reset_current_country(token)


class FeaturedCollectionTests(TestCase):
    def setUp(self):
        cat = Category.objects.create(name="Sarees", slug="sarees")
        self.p1 = Product.objects.create(
            name="Product 1", slug="product-1", sku="P1", category=cat, base_price=Decimal("999"),
            base_price_ae=Decimal("42"), mrp=Decimal("1500"), purchase_price=Decimal("500"),
        )
        ProductImage.objects.create(product=self.p1, image="products/placeholders/product-1.png", is_primary=True)

        self.wedding = Collection.objects.create(name="Wedding Season", slug="wedding-season", is_featured=True, display_order=2)
        self.silk = Collection.objects.create(name="Royal Heritage Silk", slug="royal-heritage", is_featured=True, display_order=1)
        self.hidden = Collection.objects.create(name="Gifting Edit", slug="gifting-edit", is_featured=False)
        self.empty = Collection.objects.create(name="Empty", slug="empty", is_featured=True, display_order=3)
        self.diwali = Collection.objects.create(name="Diwali Edit", slug="diwali-edit", is_featured=True, display_order=4)
        self.diwali.countries.set([Country.objects.get(code="IN")])
        self.eid = Collection.objects.create(name="Eid Edit", slug="eid-edit", is_featured=True, display_order=5)
        self.eid.countries.set([Country.objects.get(code="AE")])
        for col in (self.wedding, self.silk, self.hidden, self.diwali, self.eid):
            col.products.add(self.p1)

    def test_only_featured_non_empty_collections_in_display_order(self):
        names = [c.name for c in _in("IN", get_featured_collections)]
        self.assertEqual(names, ["Royal Heritage Silk", "Wedding Season", "Diwali Edit"])

    def test_country_specific_collections(self):
        self.assertIn("Eid Edit", [c.name for c in _in("AE", get_featured_collections)])
        self.assertNotIn("Eid Edit", [c.name for c in _in("IN", get_featured_collections)])
        self.assertNotIn("Diwali Edit", [c.name for c in _in("AE", get_featured_collections)])

    def test_cover_uses_the_product_placeholder_image(self):
        cover = _in("IN", get_featured_collections)[0].cover_url
        self.assertTrue(cover.endswith("products/placeholders/product-1.png"))

    def test_rails_follow_requested_order_and_skip_unknown_or_unavailable(self):
        rails = _in("IN", lambda: get_collection_rails(slugs=["wedding-season", "nope", "eid-edit", "royal-heritage"]))
        self.assertEqual([r["collection"].slug for r in rails], ["wedding-season", "royal-heritage"])
        self.assertEqual(rails[0]["products"][0].name, "Product 1")

    def test_rail_prices_follow_market(self):
        india = _in("IN", lambda: get_collection_rails(slugs=["wedding-season"]))[0]["products"][0]
        uae = _in("AE", lambda: get_collection_rails(slugs=["wedding-season"]))[0]["products"][0]
        self.assertEqual(india.display_price, Decimal("999"))
        self.assertEqual(uae.display_price, Decimal("42"))


class HomepageRenderTests(TestCase):
    def setUp(self):
        Currency.objects.update_or_create(code="INR", defaults={"symbol": "₹", "exchange_rate_to_base": 1, "is_default": True, "is_active": True})
        Currency.objects.update_or_create(code="AED", defaults={"symbol": "AED", "exchange_rate_to_base": 1, "is_active": True})
        cat = Category.objects.create(name="Sarees", slug="sarees")
        p = Product.objects.create(
            name="Product 1", slug="product-1", sku="P1", category=cat, base_price=Decimal("999"),
            base_price_ae=Decimal("42"), mrp=Decimal("1500"), purchase_price=Decimal("500"), stock_quantity=5,
        )
        col = Collection.objects.create(name="Wedding Season", slug="wedding-season", is_featured=True, display_order=1)
        col.products.add(p)
        HomepageSection.objects.update_or_create(
            section_type=HomepageSectionType.FEATURED_COLLECTIONS,
            defaults={"is_active": True, "config": {"collection_slugs": ["wedding-season"]}},
        )

    def test_homepage_shows_collection_grid_rail_and_promise(self):
        resp = self.client.get("/", HTTP_CF_IPCOUNTRY="IN")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Shop by Collection")
        self.assertContains(resp, "sv-coltile")
        self.assertContains(resp, "Why Shop with Sarocchi")
        self.assertContains(resp, "collection=wedding-season")
        self.assertContains(resp, "Product 1")
