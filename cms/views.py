"""HTTP views for the cms app; thin request parsing delegating to selectors/services."""

from __future__ import annotations

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from catalog.selectors import get_homepage_product_rails
from cms.selectors import get_active_homepage_sections
from cms.services import get_section_render_context
from core.seo import seo_context


@require_GET
def homepage_view(request: HttpRequest) -> HttpResponse:
    """Render the Saavi homepage (fixed design layout fed by CMS hero slides and product rails)."""
    from catalog.selectors import get_category_tree, get_products_by_category_slug

    sections = get_active_homepage_sections()
    product_rails = get_homepage_product_rails()

    hero_slides = []
    for section in sections:
        if section["section_type"] == "hero_slider":
            ctx = get_section_render_context(section=section, product_rails=product_rails)
            hero_slides = ctx.get("slides") or []
            break

    def _root_id(product):
        category = getattr(product, "category", None)
        if category is None:
            return None
        return category.parent_id or category.pk

    def _tabs(rail_key: str, limit: int = 5):
        tabs = []
        for cat in collections:
            items = [p for p in product_rails.get(rail_key, []) if _root_id(p) == cat.pk][:limit]
            if not items:
                items = get_products_by_category_slug(cat.slug, limit=limit)
            tabs.append({"category": cat, "products": items})
        return tabs

    collections = list(get_category_tree())[:2]
    for cat in collections:
        sample = get_products_by_category_slug(cat.slug, limit=1)
        image = sample[0].primary_images[0] if sample and getattr(sample[0], "primary_images", None) else None
        cat.banner_image_url = image.image.url if image and image.image else ""

    context = seo_context(
        request=request,
        title="Saavi By Neethu | Sarees & Ethnic Wear",
        description="Shop elegant sarees and men's kurtas from Saavi By Neethu. Rooted in tradition, woven with elegance. Delivered to India, the UAE and worldwide.",
    )
    context.update(
        {
            "hero_slides": hero_slides,
            "collections": collections,
            "new_arrival_tabs": _tabs("new_arrivals"),
            "bestseller_tabs": _tabs("bestsellers"),
        }
    )
    response = render(request, "cms/homepage.html", context)
    response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response["Pragma"] = "no-cache"
    return response
