"""Homepage section context builders — delegates to catalog selectors, never ORM."""

from __future__ import annotations

from typing import Any

from catalog.selectors import (
    get_featured_brands,
    get_homepage_product_rails,
    get_products_for_section_config,
    get_recent_approved_reviews,
    get_root_categories,
)
from cms.selectors import get_hero_slides


def build_section_context(
    *,
    section: dict[str, Any],
    product_rails: dict[str, list] | None = None,
) -> dict[str, Any]:
    """
    Dispatch section_type to the appropriate data source.

    Every section pulls live catalog/cms config data — nothing is hardcoded in templates.
    """
    section_type = section["section_type"]
    config = section.get("config") or {}
    base = {
        "section": section,
        "title": section.get("title", ""),
        "config": config,
    }

    builders = {
        "hero_slider": _hero_slider,
        "shop_by_occasion": _empty,
        "shop_by_recipient": _empty,
        "shop_by_category": _shop_by_category,
        "featured_products": _featured,
        "new_arrivals": _new_arrivals,
        "best_sellers": _best_sellers,
        "featured_brands": _featured_brands,
        "corporate_gifts_banner": _empty,
        "subscription_banner": _banner,
        "marketing_features": _marketing_features,
        "reviews": _reviews,
        "instagram_gallery": _instagram,
        "newsletter": _newsletter,
        "category_products": _category_products,
        "featured_collections": _featured_collections,
    }
    builder = builders.get(section_type, _empty)
    if section_type in ("featured_products", "best_sellers", "new_arrivals"):
        base.update(builder(config, product_rails=product_rails))
    else:
        base.update(builder(config))
    return base


def _rails(product_rails: dict[str, list] | None, key: str) -> list:
    if product_rails is not None:
        return product_rails.get(key, [])
    return get_homepage_product_rails().get(key, [])


def _category_products(config: dict[str, Any]) -> dict[str, Any]:
    from catalog.models import Category
    from catalog.selectors import get_products_by_category_slug
    
    slug_val = config.get("category_slug", "all")
    sections = []
    
    if slug_val == "all":
        roots = Category.objects.filter(is_active=True, parent__isnull=True).order_by("display_order")
        for cat in roots:
            prods = get_products_by_category_slug(cat.slug, limit=100) # fetch effectively all products
            if prods:
                sections.append({"category": cat, "products": prods})
    else:
        if isinstance(slug_val, str):
            slugs = [s.strip() for s in slug_val.split(",") if s.strip()]
        else:
            slugs = slug_val

        for s in slugs:
            cat = Category.objects.filter(slug=s, is_active=True).first()
            if cat:
                prods = get_products_by_category_slug(s, limit=100)
                if prods:
                    sections.append({"category": cat, "products": prods})
                
    return {"category_sections": sections}


def _hero_slider(config: dict[str, Any]) -> dict[str, Any]:
    """Prefer uploaded photo/video slides; fall back to legacy URL-based config."""
    slides = get_hero_slides()
    if slides:
        return {"slides": slides}

    legacy_slides = config.get("slides") or []
    fallback = [
        {
            "type": "image",
            "src": slide.get("image") or slide.get("src") or "",
            "poster": slide.get("poster") or "",
            "title": slide.get("title") or "",
        }
        for slide in legacy_slides
        if isinstance(slide, dict) and (slide.get("image") or slide.get("src"))
    ]
    return {"slides": fallback}


def _shop_by_occasion(config: dict[str, Any]) -> dict[str, Any]:
    return {}


def _shop_by_recipient(config: dict[str, Any]) -> dict[str, Any]:
    return {}


def _shop_by_category(config: dict[str, Any]) -> dict[str, Any]:
    return {"categories": get_root_categories(category_ids=None)}


def _featured(
    config: dict[str, Any], product_rails: dict[str, list] | None = None
) -> dict[str, Any]:
    return {"products": _rails(product_rails, "featured")}


def _new_arrivals(
    config: dict[str, Any], product_rails: dict[str, list] | None = None
) -> dict[str, Any]:
    return {"products": _rails(product_rails, "new_arrivals")}


def _best_sellers(
    config: dict[str, Any], product_rails: dict[str, list] | None = None
) -> dict[str, Any]:
    return {"products": _rails(product_rails, "bestsellers")}


def _featured_brands(config: dict[str, Any]) -> dict[str, Any]:
    brand_ids = config.get("brand_ids")
    return {"brands": get_featured_brands(brand_ids=brand_ids)}


def _banner(config: dict[str, Any]) -> dict[str, Any]:
    return {"banner": config}


def _marketing_features(config: dict[str, Any]) -> dict[str, Any]:
    destination = config.get("destination", "")
    target = config.get("target", "")

    #fallback if destination not yet in config
    if not destination:
        lt = config.get("link_type", "category")
        destination = "collections" if lt == "collection" else ("flash_sales" if lt == "flash_sale" else lt)
        if destination == "category":
            cslug = config.get("category_slug")
            target = f"category:{cslug}" if cslug else "category:all"
        elif destination == "collections":
            cslug = config.get("collection_slug")
            target = f"collections:{cslug}" if cslug else "collections:all"
        elif destination == "flash_sales":
            target = "flash_sales:all"
        else:
            destination = "products"
            target = "products:all"

    target_url = "/shop/"
    target_label = ""

    #parse target prefix and slug (e.g. 'category:t-shirts' or 'collections:bride')
    target_dest = destination
    target_key = "all"
    if ":" in target:
        parts = target.split(":", 1)
        target_dest = parts[0]
        target_key = parts[1]

    if target_dest == "products":
        if target_key and target_key != "all":
            target_url = f"/shop/products/{target_key}/"
            try:
                from catalog.models import Product

                prod = Product.objects.filter(slug=target_key).first()
                if prod:
                    target_label = prod.name
            except Exception:
                pass
        else:
            target_url = "/shop/"
            target_label = "All Products"
    elif target_dest == "category":
        if target_key and target_key != "all":
            target_url = f"/shop/category/{target_key}/"
            try:
                from catalog.models import Category

                cat = Category.objects.filter(slug=target_key).first()
                if cat:
                    target_label = cat.name
            except Exception:
                pass
        else:
            target_url = "/shop/"
            target_label = "All Categories"
    elif target_dest == "collections":
        if target_key and target_key != "all":
            target_url = f"/shop/?collection={target_key}"
            try:
                from catalog.models import Collection

                col = Collection.objects.filter(slug=target_key).first()
                if col:
                    target_label = col.name
            except Exception:
                pass
        else:
            target_url = "/shop/?collection=all"
            target_label = "All Collections"

    elif target_dest == "flash_sales":
        if target_key and target_key != "all":
            target_url = f"/shop/?flash_sale={target_key}"
            try:
                from marketing.models import FlashSale

                fs = FlashSale.objects.filter(pk=target_key).first()
                if fs:
                    target_label = fs.name
            except Exception:
                pass
        else:
            target_url = "/shop/?flash_sale=1"
            target_label = "Flash Sales & Offers"
    elif target_dest == "coupons":
        if target_key and target_key != "all":
            target_url = f"/cart/?coupon={target_key}"
            target_label = f"Coupon {target_key}"
        else:
            target_url = "/cart/"
            target_label = "Coupons & Discounts"
    else:
        target_url = "/shop/"
        target_label = "All Products"


    image_url = config.get("image_url", "")
    if not image_url:
        try:
            from catalog.models import ProductImage

            sample_img = (
                ProductImage.objects.filter(is_primary=True).values_list("image", flat=True).first()
            )
            if sample_img:
                image_url = f"/media/{sample_img}"
        except Exception:
            pass
        if not image_url:
            image_url = "/static/img/wholesale_banner.png"

    return {
        "badge": config.get("badge", "SPECIAL PROMOTION"),
        "subtitle": config.get(
            "subtitle",
            "Discover luxury handloom sarees and handcrafted jewellery for your special celebrations.",
        ),
        "button_text": config.get("button_text") or "Shop Now",
        "image_url": image_url,
        "target_url": target_url,
        "target_label": target_label,
        "destination": target_dest,
    }


def _reviews(config: dict[str, Any]) -> dict[str, Any]:
    limit = config.get("limit", 6)
    return {"reviews": get_recent_approved_reviews(limit=limit)}


def _instagram(config: dict[str, Any]) -> dict[str, Any]:
    handle = config.get("instagram_handle", "")
    if handle:
        handle = handle.strip().lstrip("@")
    return {
        "images": config.get("images", []),
        "instagram_handle": handle,
    }


def _newsletter(config: dict[str, Any]) -> dict[str, Any]:
    return {"placeholder": config.get("placeholder", "")}


def _empty(config: dict[str, Any]) -> dict[str, Any]:
    return {}


def _featured_collections(config: dict[str, Any]) -> dict[str, Any]:
    from django.db.models import Avg, Count, Prefetch, Q
    from catalog.models import Collection, ModerationStatus, Product
    from catalog.selectors import (
        _decorate_homepage_rail_prices,
        _primary_image_prefetch,
        _variants_prefetch,
    )

    slugs = config.get("collection_slugs", [])
    approved = Q(reviews__moderation_status=ModerationStatus.APPROVED)
    product_qs = (
        Product.objects.filter(is_active=True)
        .select_related("category", "brand")
        .prefetch_related(_primary_image_prefetch(), _variants_prefetch(), "labels")
        .annotate(
            average_rating=Avg("reviews__rating", filter=approved),
            review_count=Count("reviews", filter=approved),
        )
    )

    base_qs = Collection.objects.filter(is_active=True).prefetch_related(
        Prefetch("products", queryset=product_qs)
    )
    if slugs:
        if isinstance(slugs, str):
            slugs = [s.strip() for s in slugs.split(",") if s.strip()]
        collections = list(base_qs.filter(slug__in=slugs))
    else:
        collections = list(base_qs)

    all_products = []
    for col in collections:
        all_products.extend(col.products.all())
    if all_products:
        _decorate_homepage_rail_prices({"collections": all_products})

    return {"collections": collections}
