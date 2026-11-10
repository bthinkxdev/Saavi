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
    from catalog.selectors import (
        get_category_tree,
        get_collection_rails,
        get_featured_collections,
        get_products_by_category_slug,
    )

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

    # Collection rails are driven by the "Featured Collections" homepage section's slug list.
    rail_slugs: list[str] = []
    for section in sections:
        if section["section_type"] == "featured_collections":
            slugs = (section.get("config") or {}).get("collection_slugs") or []
            rail_slugs = [s.strip() for s in slugs.split(",")] if isinstance(slugs, str) else list(slugs)
            break
    collection_rails = get_collection_rails(slugs=rail_slugs, per_rail=5)
    featured_collections = get_featured_collections()

    context = seo_context(
        request=request,
        title="Saavi By Neethu | Sarees & Ethnic Wear",
        description="Shop elegant sarees and men's kurtas from Saavi By Neethu. Rooted in tradition, woven with elegance. Delivered to India, the UAE and worldwide.",
    )
    festive_image = ""
    for product in product_rails.get("featured", []) + product_rails.get("bestsellers", []):
        imgs = getattr(product, "primary_images", None) or []
        if imgs and imgs[0].image:
            festive_image = imgs[0].image.url
            break

    active_sections = []
    for s in sections:
        active_sections.append({
            "type": s["section_type"],
            "title": s.get("title", ""),
            "context": get_section_render_context(section=s, product_rails=product_rails),
            "config": s.get("config", {}),
        })

    context.update(
        {
            "active_sections": active_sections,
            "festive_image": festive_image,
            "hero_slides": hero_slides,
            "collections": collections,
            "new_arrival_tabs": _tabs("new_arrivals"),
            "bestseller_tabs": _tabs("bestsellers"),
            "featured_collections": featured_collections,
            "wedding_cover": next((c.cover_url for c in featured_collections if c.slug == "wedding-season"), ""),
            "collection_rails_top": collection_rails[:2],
            "collection_rails_bottom": collection_rails[2:4],
        }
    )
    response = render(request, "cms/homepage.html", context)
    response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response["Pragma"] = "no-cache"
    return response
