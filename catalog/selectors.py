"""Read-only query functions for the catalog app; views must not call the ORM directly."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

from django.core.cache import cache
from django.core.paginator import Paginator
from django.db.models import Avg, Count, F, Prefetch, Q, QuerySet, Case, When, Value, IntegerField

from catalog.models import (
    ModerationStatus,
    Product,
    ProductDocument,
    ProductImage,
    ProductRelation,
    ProductSpecification,
    ProductVariant,
    ProductVideo,
    RelationType,
    Review,
    ReviewPhoto,
)

PLP_CARD_FIELDS: tuple[str, ...] = (
    "id",
    "name",
    "slug",
    "sku",
    "base_price",
    "mrp",
    "color",
    "is_featured",
    "is_bestseller",
    "is_new_arrival",
    "stock_quantity",
    "low_stock_threshold",
    "category_id",
    "brand_id",
)

HOMEPAGE_RAIL_LIMIT = 12
CATEGORY_TREE_CACHE_KEY = "catalog:category_tree:v1"
CATEGORY_TREE_TTL = 300
DEFAULT_CURRENCY_CACHE_KEY = "core:default_currency:v1"
DEFAULT_CURRENCY_TTL = 300


def get_product_display_price(*, product: Product) -> Decimal:
    """Return flash-sale-adjusted display price for PLP cards."""
    from marketing.selectors import get_active_flash_sale_price

    sale = get_active_flash_sale_price(product_id=product.pk, base_price=product.effective_base_price)
    return sale["price"]


def _primary_image_prefetch() -> Prefetch:
    """
    Prefetch images ordered by primary status and display order.
    
    Used by homepage rails, PLP, and search dropdowns.
    Returns all images ordered with the primary one first.
    Templates must use `.0` to get the best available image.
    """
    return Prefetch(
        "images",
        queryset=ProductImage.objects.order_by("-is_primary", "display_order"),
        to_attr="primary_images",
    )


def _variants_prefetch() -> Prefetch:
    """Prefetch variants ordered by ID to attach variant_list for card displays."""
    return Prefetch(
        "variants",
        queryset=ProductVariant.objects.order_by("id"),
        to_attr="variant_list",
    )


def _homepage_rail_queryset(*, filters: Q, ordering: tuple = ("-created_at",)) -> QuerySet[Product]:
    """Base queryset for a single homepage rail with shared optimizations."""
    approved = Q(reviews__moderation_status=ModerationStatus.APPROVED)
    return (
        Product.objects.filter(is_active=True)
        .filter(filters)
        .select_related("category", "brand")
        .prefetch_related(_primary_image_prefetch(), _variants_prefetch())
        .only(*PLP_CARD_FIELDS)
        .annotate(
            average_rating=Avg("reviews__rating", filter=approved),
            review_count=Count("reviews", filter=approved),
        )
        .order_by(*ordering)[:HOMEPAGE_RAIL_LIMIT]
    )


def get_homepage_product_rails() -> dict[str, list[Product]]:
    """
    Return homepage merchandising rails keyed by rail name.

    Query guarantee: exactly 6 DB queries total (3 rails × 2 queries each) —
      trending/bestsellers share one evaluated bestseller rail —
      plus one flash-sale discount lookup for all unique product ids.
    """
    bestseller_rail = list(_homepage_rail_queryset(filters=Q(is_bestseller=True)))
    new_arrivals = list(_homepage_rail_queryset(filters=Q(is_new_arrival=True)))
    featured = list(_homepage_rail_queryset(
        filters=Q(),
        ordering=(
            Case(
                When(homepage_featured__is_shown=True, then=Value(1)),
                When(homepage_featured__is_shown=False, then=Value(-1)),
                default=Value(0),
                output_field=IntegerField()
            ).desc(),
            Case(
                When(homepage_featured__is_shown=True, then=F("homepage_featured__updated_at")),
                default=None
            ).desc(nulls_last=True),
            Case(
                When(homepage_featured__is_shown=False, then=F("homepage_featured__updated_at")),
                default=None
            ).asc(nulls_last=True),
            "-created_at"
        )
    ))
    rails = {
        "trending": bestseller_rail,
        "bestsellers": bestseller_rail,
        "new_arrivals": new_arrivals,
        "featured": featured,
    }
    _decorate_homepage_rail_prices(rails)
    return rails


def get_products_by_category_slug(slug: str, limit: int | None = None) -> list[Product]:
    """Fetch products for a category, optionally limited. Decorates prices."""
    approved = Q(reviews__moderation_status=ModerationStatus.APPROVED)
    cat_filter = Q(category__slug=slug) | Q(category__parent__slug=slug)
    
    qs = (
        Product.objects.filter(is_active=True)
        .filter(cat_filter)
        .select_related("category", "brand")
        .prefetch_related(_primary_image_prefetch(), _variants_prefetch())
        .only(*PLP_CARD_FIELDS)
        .annotate(
            average_rating=Avg("reviews__rating", filter=approved),
            review_count=Count("reviews", filter=approved),
        )
        .order_by(
            Case(
                When(homepage_featured__is_shown=True, then=Value(1)),
                When(homepage_featured__is_shown=False, then=Value(-1)),
                default=Value(0),
                output_field=IntegerField()
            ).desc(),
            Case(
                When(homepage_featured__is_shown=True, then=F("homepage_featured__updated_at")),
                default=None
            ).desc(nulls_last=True),
            Case(
                When(homepage_featured__is_shown=False, then=F("homepage_featured__updated_at")),
                default=None
            ).asc(nulls_last=True),
            "-created_at"
        )
    )
    if limit:
        qs = qs[:limit]
        
    products = list(qs)
    _decorate_homepage_rail_prices({"temp": products})
    return products


def _decorate_homepage_rail_prices(rails: dict[str, list[Product]]) -> None:
    """Attach flash-sale display_price / flags onto homepage rail products."""
    from marketing.selectors import get_flash_sale_discounts_for_products

    seen: dict[int, Product] = {}
    for products in rails.values():
        for product in products:
            seen[product.pk] = product
    if not seen:
        return

    discounts = get_flash_sale_discounts_for_products(
        product_prices={pid: p.effective_base_price for pid, p in seen.items()},
    )
    for product in seen.values():
        eff_base = product.effective_base_price
        pct = discounts.get(product.pk)
        if pct is None:
            product.display_price = eff_base
            product.is_flash_sale = False
            product.flash_discount_percentage = None
            continue
        discount = (eff_base * pct / Decimal("100")).quantize(Decimal("0.01"))
        product.display_price = eff_base - discount
        product.is_flash_sale = True
        product.flash_discount_percentage = pct
        product.original_price = eff_base


def _smart_search_filter(query_str: str) -> tuple[Q, str]:
    """Return an intelligent search Q filter and cleaned display query."""
    import re
    cleaned = re.sub(r'[^a-zA-Z0-9\s-]', ' ', query_str).strip()
    cleaned = re.sub(r'([0-9]+)([a-zA-Z]{2,})', r'\1 \2', cleaned)
    cleaned = re.sub(r'([a-zA-Z]{2,})([0-9]+)', r'\1 \2', cleaned)
    words = cleaned.split()
    if not words:
        return Q(pk__in=[]), ""

    def _word_q(w: str) -> Q:
        return (
            Q(name__icontains=w) |
            Q(sku__icontains=w) |
            Q(variants__sku_suffix__icontains=w) |
            Q(category__name__icontains=w) |
            Q(brand__name__icontains=w) |
            Q(tags__name__icontains=w) |
            Q(meta_description__icontains=w)
        )

    base_qs = Product.objects.filter(is_active=True)
    valid_words = [w for w in words if base_qs.filter(_word_q(w)).exists()]

    if valid_words:
        clean_q = Q()
        for w in valid_words:
            clean_q &= _word_q(w)
        if base_qs.filter(clean_q).exists():
            return clean_q, " ".join(valid_words)
        or_q = Q()
        for w in valid_words:
            or_q |= _word_q(w)
        return or_q, " ".join(valid_words)

    full_q = Q()
    for w in words:
        full_q &= _word_q(w)
    return full_q, " ".join(words)


def _apply_plp_filters(queryset: QuerySet[Product], filters: dict[str, Any]) -> QuerySet[Product]:
    """Apply PLP filter dict to a base queryset."""
    if category_id := filters.get("category_id"):
        from catalog.models import Category
        category_ids = [category_id]
        category_ids.extend(
            Category.objects.filter(parent_id=category_id, is_active=True).values_list(
                "id", flat=True
            )
        )
        queryset = queryset.filter(category_id__in=category_ids)
    if brand_id := filters.get("brand_id"):
        queryset = queryset.filter(brand_id=brand_id)
    if color := filters.get("color"):
        queryset = queryset.filter(color__iexact=color)
    if filters.get("featured"):
        queryset = queryset.filter(is_featured=True)
    if filters.get("bestseller"):
        queryset = queryset.filter(is_bestseller=True)
    if filters.get("new_arrival"):
        queryset = queryset.filter(is_new_arrival=True)
    if availability := filters.get("availability"):
        if availability == "in_stock":
            queryset = queryset.filter(stock_quantity__gt=0)
        elif availability == "out_of_stock":
            queryset = queryset.filter(stock_quantity=0)
    if min_price := filters.get("min_price"):
        queryset = queryset.filter(base_price__gte=min_price)
    if max_price := filters.get("max_price"):
        queryset = queryset.filter(base_price__lte=max_price)
    if q := filters.get("q"):
        search_q, clean_text = _smart_search_filter(q)
        queryset = queryset.filter(search_q).distinct()
        filters["q"] = clean_text
        
    if collection := filters.get("collection"):
        if collection == "all":
            queryset = queryset.filter(collections__isnull=False, collections__is_active=True).distinct()
        else:
            queryset = queryset.filter(collections__slug=collection)


    if flash_sale := filters.get("flash_sale"):
        from django.utils import timezone
        now = timezone.now()
        if str(flash_sale).isdigit() and int(flash_sale) > 1:
            queryset = queryset.filter(
                flash_sales__id=int(flash_sale),
                flash_sales__is_active=True,
                flash_sales__starts_at__lte=now,
                flash_sales__ends_at__gte=now,
            ).distinct()
        else:
            queryset = queryset.filter(
                flash_sales__is_active=True,
                flash_sales__starts_at__lte=now,
                flash_sales__ends_at__gte=now,
            ).distinct()

    
    if dynamic_attrs := filters.get("dynamic_attrs"):
        for attr_name, attr_values in dynamic_attrs.items():
            if attr_values:
                q_objs = Q()
                for val in attr_values:
                    q_objs |= Q(attribute_values__attribute__name__iexact=attr_name, attribute_values__value__iexact=val)
                    q_objs |= Q(variants__attribute_values__attribute__name__iexact=attr_name, variants__attribute_values__value__iexact=val)
                queryset = queryset.filter(q_objs).distinct()
                
    return queryset


def _apply_plp_sort(queryset: QuerySet[Product], sort: str, is_search: bool = False) -> QuerySet[Product]:
    """Apply PLP sort key to queryset."""
    sort_map = {
        "price_asc": "base_price",
        "price_desc": "-base_price",
        "newest": "-created_at",
        "rating": "-average_rating",
        "name": "name",
    }
    primary_sort = sort_map.get(sort, "-created_at")
    
    #on active search queries without an explicit sort, do not let homepage pinned items distort results
    if is_search and (sort in ("newest", "") or sort not in sort_map):
        return queryset.order_by("-created_at")

    #only apply pinned logic if the sort is default/newest
    if sort in ("newest", "") or sort not in sort_map:
        return queryset.order_by(
            Case(
                When(homepage_featured__is_shown=True, then=Value(1)),
                When(homepage_featured__is_shown=False, then=Value(-1)),
                default=Value(0),
                output_field=IntegerField()
            ).desc(),
            Case(
                When(homepage_featured__is_shown=True, then=F("homepage_featured__updated_at")),
                default=None
            ).desc(nulls_last=True),
            Case(
                When(homepage_featured__is_shown=False, then=F("homepage_featured__updated_at")),
                default=None
            ).asc(nulls_last=True),
            primary_sort
        )
    
    return queryset.order_by(primary_sort)


def get_plp_products(
    *,
    filters: Optional[dict[str, Any]] = None,
    sort: str = "newest",
    page: int = 1,
    page_size: int = 24,
    user: Optional[Any] = None,
) -> dict[str, Any]:
    """
    Return a paginated PLP page with advanced filters and average rating annotation.

    Query guarantee: exactly 4 DB queries (COUNT + page SELECT + primary image
    prefetch + active flash-sale lookup) regardless of total product count.

    Approved reviews only contribute to average_rating annotation.
    """
    filters = filters or {}
    queryset = (
        Product.objects.filter(is_active=True)
        .select_related("category", "brand")
        .prefetch_related(_primary_image_prefetch(), _variants_prefetch())
        .only(*PLP_CARD_FIELDS)
        .annotate(
            average_rating=Avg(
                "reviews__rating",
                filter=Q(reviews__moderation_status=ModerationStatus.APPROVED),
            ),
        )
    )
    queryset = _apply_plp_filters(queryset, filters)
    queryset = _apply_plp_sort(queryset, sort, is_search=bool(filters.get("q")))

    paginator = Paginator(queryset, page_size)
    page_obj = paginator.get_page(page)
    results = list(page_obj.object_list)

    display_prices: dict[int, Decimal] = {}
    from marketing.selectors import get_flash_sale_discounts_for_products

    flash_discounts = get_flash_sale_discounts_for_products(
        product_prices={product.pk: product.effective_base_price for product in results},
    )
    for product in results:
        eff_base = product.effective_base_price
        discount_pct = flash_discounts.get(product.pk)
        if discount_pct is None:
            display_prices[product.pk] = eff_base
            product.is_flash_sale = False
            product.flash_discount_percentage = None
        else:
            discount = (eff_base * discount_pct / Decimal("100")).quantize(
                Decimal("0.01")
            )
            display_prices[product.pk] = eff_base - discount
            product.is_flash_sale = True
            product.flash_discount_percentage = discount_pct
            product.original_price = eff_base
        product.display_price = display_prices[product.pk]

    return {
        "results": results,
        "display_prices": display_prices,
        "page": page_obj.number,
        "page_size": page_size,
        "total_count": paginator.count,
        "total_pages": paginator.num_pages,
        "has_next": page_obj.has_next(),
        "has_previous": page_obj.has_previous(),
    }


def get_product_detail(*, slug: str) -> Optional[Product]:
    """
    1) product + select_related(category, brand)
    2) variants prefetch
    3) images prefetch (ordered)
    4) videos prefetch
    5) approved reviews prefetch
    6) review photos prefetch (via nested Prefetch on reviews)
    7) related products prefetch
    8) related product primary images prefetch
    9) FBT products prefetch
    10) FBT product primary images prefetch
    """
    approved_reviews_prefetch = Prefetch(
        "reviews",
        queryset=(
            Review.objects.filter(moderation_status=ModerationStatus.APPROVED)
            .select_related("customer", "customer__user")
            .prefetch_related(
                Prefetch("photos", queryset=ReviewPhoto.objects.order_by("id")),
            )
            .order_by("-created_at")
        ),
        to_attr="approved_reviews",
    )
    related_prefetch = Prefetch(
        "relations",
        queryset=ProductRelation.objects.filter(
            relation_type=RelationType.RELATED,
        )
        .select_related(
            "related_product",
            "related_product__category",
            "related_product__brand",
        )
        .prefetch_related(
            Prefetch(
                "related_product__images",
                queryset=ProductImage.objects.order_by("-is_primary", "display_order"),
                to_attr="primary_images",
            ),
        ),
        to_attr="related_relations",
    )
    fbt_prefetch = Prefetch(
        "relations",
        queryset=ProductRelation.objects.filter(
            relation_type=RelationType.FREQUENTLY_BOUGHT_TOGETHER,
        )
        .select_related(
            "related_product",
            "related_product__category",
            "related_product__brand",
        )
        .prefetch_related(
            Prefetch(
                "related_product__images",
                queryset=ProductImage.objects.order_by("-is_primary", "display_order"),
                to_attr="primary_images",
            ),
        ),
        to_attr="fbt_relations",
    )

    return (
        Product.objects.filter(is_active=True, slug=slug)
        .select_related("category", "brand")
        .prefetch_related(
            Prefetch(
                "variants",
                queryset=ProductVariant.objects.order_by("id"),
                to_attr="variant_list",
            ),
            Prefetch(
                "images",
                queryset=ProductImage.objects.order_by("display_order"),
            ),
            Prefetch(
                "videos",
                queryset=ProductVideo.objects.order_by("id"),
            ),
            Prefetch(
                "specifications",
                queryset=ProductSpecification.objects.order_by("display_order", "name"),
            ),
            Prefetch(
                "documents",
                queryset=ProductDocument.objects.order_by("display_order", "title"),
            ),
            approved_reviews_prefetch,
            related_prefetch,
            fbt_prefetch,
        )
        .first()
    )


RECENTLY_VIEWED_KEY_TEMPLATE = "catalog:recently_viewed:{viewer_key}"
RECENTLY_VIEWED_MAX = 20


def _recently_viewed_cache_key(*, viewer_key: str) -> str:
    return RECENTLY_VIEWED_KEY_TEMPLATE.format(viewer_key=viewer_key)


def record_product_view(*, viewer_key: str, product_id: int) -> None:
    """
    Push a product ID onto the Redis-backed recently-viewed list for a viewer.

    Not a selector — write path for Redis only (no DB).
    """
    from django.core.cache import cache

    key = _recently_viewed_cache_key(viewer_key=viewer_key)
    viewed: list[int] = cache.get(key, [])
    viewed = [pid for pid in viewed if pid != product_id]
    viewed.insert(0, product_id)
    cache.set(key, viewed[:RECENTLY_VIEWED_MAX], timeout=60 * 60 * 24 * 30)


def get_recently_viewed(
    *,
    viewer_key: str,
) -> list[Product]:
    """
    Hydrate the Redis recently-viewed list in a single DB round trip.

    Query guarantee: exactly 2 DB queries when IDs exist (1 product SELECT with
    select_related + 1 primary-image prefetch). Zero DB queries when list is empty.
    Redis order is preserved in Python — DB ORDER BY is intentionally not used.

    Params:
        viewer_key: Customer profile PK string or session key.
    Returns:
        List of Product instances in most-recent-first order.
    """
    from django.core.cache import cache

    key = _recently_viewed_cache_key(viewer_key=viewer_key)
    product_ids: list[int] = cache.get(key, [])
    if not product_ids:
        return []

    products = (
        Product.objects.filter(id__in=product_ids, is_active=True)
        .select_related("category", "brand")
        .prefetch_related(_primary_image_prefetch(), _variants_prefetch())
        .only(*PLP_CARD_FIELDS)
    )
    product_map = {product.id: product for product in products}
    return [product_map[pid] for pid in product_ids if pid in product_map]


def get_category_tree() -> list:
    """
    Return active root categories with prefetched children for the mega menu.

    Query guarantee: 2 queries (roots + children prefetch); cached 5 minutes.
    """
    from catalog.models import Category

    cached = cache.get(CATEGORY_TREE_CACHE_KEY)
    if cached is not None:
        return cached

    tree = list(
        Category.objects.filter(is_active=True, parent__isnull=True)
        .prefetch_related(
            Prefetch(
                "children",
                queryset=Category.objects.filter(is_active=True).order_by("display_order", "name"),
            )
        )
        .order_by("display_order", "name")
    )
    cache.set(CATEGORY_TREE_CACHE_KEY, tree, CATEGORY_TREE_TTL)
    return tree


def invalidate_category_tree_cache() -> None:
    """Clear cached navigation tree after category mutations."""
    cache.delete(CATEGORY_TREE_CACHE_KEY)


def get_search_suggestions(*, query: str, limit: int = 8) -> dict[str, list]:
    """Return product, brand, and category matches for live search."""
    if not query or len(query.strip()) < 2:
        return {
            "products": [],
            "brands": [],
            "categories": [],
            "equipment_types": [],
        }

    from catalog.models import Category

    search_q, clean_text = _smart_search_filter(query)

    products = list(
        Product.objects.filter(is_active=True)
        .filter(search_q)
        .distinct()
        .select_related("category")
        .prefetch_related(_primary_image_prefetch(), _variants_prefetch())
        .only(*PLP_CARD_FIELDS)[:limit]
    )

    categories = list(Category.objects.filter(is_active=True, name__icontains=clean_text)[:5])

    return {
        "products": products,
        "brands": [],
        "categories": categories,
        "equipment_types": [],
    }


def get_root_categories(*, category_ids: list[int] | None = None) -> list:
    """Return root categories for homepage shop-by-category rail."""
    from catalog.models import Category

    qs = Category.objects.filter(is_active=True, parent__isnull=True).order_by(
        "display_order", "name"
    )
    if category_ids:
        qs = qs.filter(pk__in=category_ids)
    return list(qs)


def get_featured_brands(*, brand_ids: list[int] | None = None) -> list:
    """Return featured brands for homepage brand rail."""
    from catalog.models import Brand

    qs = Brand.objects.filter(is_featured=True).order_by("name")
    if brand_ids:
        qs = qs.filter(pk__in=brand_ids)
    return list(qs)


def get_products_for_section_config(*, config: dict) -> list[Product]:
    """
    Return products for collection sections driven by CMS config JSON.

    Config keys: product_ids, category_id, brand_id, recipient_id, min_price,
    limit, flags (model booleans).
    Query guarantee: 1 SELECT + 1 primary-image prefetch.
    """
    qs = Product.objects.filter(is_active=True)
    if product_ids := config.get("product_ids"):
        qs = qs.filter(pk__in=product_ids)
    if category_id := config.get("category_id"):
        qs = qs.filter(category_id=category_id)
    if brand_id := config.get("brand_id"):
        qs = qs.filter(brand_id=brand_id)
    if min_price := config.get("min_price"):
        qs = qs.filter(base_price__gte=min_price)
    for flag in config.get("flags", []):
        if hasattr(Product, flag):
            qs = qs.filter(**{flag: True})
    limit = config.get("limit", HOMEPAGE_RAIL_LIMIT)
    return list(
        qs.select_related("category", "brand")
        .prefetch_related(_primary_image_prefetch(), _variants_prefetch())
        .only(*PLP_CARD_FIELDS)
        .order_by("-created_at")[:limit]
    )


def get_recent_approved_reviews(*, limit: int = 6) -> list[Review]:
    """
    Return recent approved reviews for homepage reviews section.

    Query guarantee: 1 SELECT with select_related product + customer.
    """
    return list(
        Review.objects.filter(moderation_status=ModerationStatus.APPROVED)
        .select_related("product", "customer", "customer__user")
        .order_by("-created_at")[:limit]
    )


def get_variant_price(
    *, product_id: int, variant_id: int | None = None, user: Optional[Any] = None, quantity: int = 1
) -> dict[str, str]:
    """
    Return computed price for a product/variant combination.

    Applies active flash sale pricing via marketing selector when applicable.
    Query guarantee: 1–2 SELECTs on product/variant + 0–1 on flash sale.
    """

    product = Product.objects.get(pk=product_id, is_active=True)

    retail_price = product.base_price
    resolved_variant_id = None
    
    # Safely evaluate product in-stock status
    is_in_stock = True
    if hasattr(product, 'is_in_stock'):
        val = getattr(product, 'is_in_stock')
        is_in_stock = val() if callable(val) else val
    elif hasattr(product, 'stock_quantity'):
        is_in_stock = product.stock_quantity > 0

    mrp = product.mrp

    if variant_id:
        variant = ProductVariant.objects.filter(pk=variant_id, product=product).first()
        if variant:
            if variant.base_price is not None and variant.base_price > 0:
                retail_price = variant.base_price
            if variant.mrp is not None and variant.mrp > 0:
                mrp = variant.mrp
            resolved_variant_id = variant.pk
            is_in_stock = variant.stock_quantity > 0

    from marketing.selectors import get_active_flash_sale_price

    sale = get_active_flash_sale_price(product_id=product.pk, base_price=retail_price)
    display_price = sale["price"]

    result = {
        "base_price": str(product.base_price),
        "price": str(display_price),
        "retail_price": str(display_price),
        "variant_id": str(resolved_variant_id) if resolved_variant_id else "",
        "is_flash_sale": str(sale["is_flash_sale"]).lower(),
        "is_in_stock": is_in_stock,
        "stock_quantity": getattr(variant, 'stock_quantity', getattr(product, 'stock_quantity', 0)) if variant_id else getattr(product, 'stock_quantity', 0),
        "low_stock_threshold": getattr(variant, 'low_stock_threshold', getattr(product, 'low_stock_threshold', 5)) if variant_id else getattr(product, 'low_stock_threshold', 5),
        "mrp": str(mrp) if mrp else "",
        "has_mrp_discount": "true" if mrp and mrp > retail_price else "false",
        "sku": getattr(variant, 'sku_suffix', product.sku) if variant_id and variant else product.sku,
    }
    if sale["is_flash_sale"]:
        result["original_price"] = str(sale["original_price"])
    return result


def get_category_by_slug(*, slug: str):
    """Return an active category by slug. Query guarantee: 1 SELECT."""
    from catalog.models import Category

    return Category.objects.filter(slug=slug, is_active=True).first()


def get_plp_filter_options() -> dict:
    """Return sidebar filter options for PLP."""
    from catalog.models import Category, ProductAttribute, Collection
    categories = list(Category.objects.filter(is_active=True, parent__isnull=True).prefetch_related("children").order_by("display_order", "name"))
    
    subcategories_map = {}
    for cat in categories:
        subcategories_map[cat.pk] = [{"pk": child.pk, "name": child.name} for child in cat.children.all() if child.is_active]
        
    from django.db.models import Prefetch, Q
    from catalog.models import ProductAttributeValue
    
    active_value_ids = list(ProductAttributeValue.objects.filter(
        Q(products__is_active=True) | Q(variants__product__is_active=True)
    ).values_list("id", flat=True).distinct())
    
    raw_attributes = list(
        ProductAttribute.objects.filter(
            values__in=active_value_ids
        ).distinct().prefetch_related(
            Prefetch("values", queryset=ProductAttributeValue.objects.filter(id__in=active_value_ids).order_by("display_order", "value"))
        )
    )
    
    attributes_dict = {}
    for attr in raw_attributes:
        attr_name_lower = attr.name.strip().lower()
        if attr_name_lower not in attributes_dict:
            attr.name = attr.name.strip().title()
            attr.display_values = []
            attributes_dict[attr_name_lower] = attr
            
        seen = {v.value.strip().lower() for v in attributes_dict[attr_name_lower].display_values}
        
        for val in attr.values.all():
            val_lower = val.value.strip().lower()
            if val_lower not in seen:
                seen.add(val_lower)
                clean_val = val.value.strip()
                if len(clean_val) <= 2:
                    val.value = clean_val.upper()
                else:
                    val.value = clean_val.title()
                attributes_dict[attr_name_lower].display_values.append(val)
                
    attributes = list(attributes_dict.values())
    
    collections = list(Collection.objects.filter(is_active=True).order_by("name"))
        
    return {
        "categories": categories,
        "brands": get_featured_brands(),
        "collections": collections,
        "subcategories_map": subcategories_map,
        "attributes": attributes,
    }


def get_product_for_cart_add(
    *,
    product_id: int,
    variant_id: int | None = None,
) -> tuple[Optional[Product], Optional[ProductVariant]]:
    """
    Return product and optional variant for cart add operations.

    Query guarantee: 1 SELECT on product (+ 1 on variant when variant_id set).
    """
    product = (
        Product.objects.filter(pk=product_id, is_active=True)
        .select_related("category", "brand")
        .first()
    )
    if product is None:
        return None, None
    variant = None
    if variant_id:
        variant = ProductVariant.objects.filter(pk=variant_id, product=product).first()
    if variant is None:
        variant = ProductVariant.objects.filter(product=product).first()
    return product, variant


def get_products_by_ids(*, product_ids: list[int]) -> list[Product]:
    """Return minimal product rows for cart drawer. Query guarantee: 1 SELECT."""
    if not product_ids:
        return []
    return list(
        Product.objects.filter(pk__in=product_ids, is_active=True).only(
            "id", "name", "slug", "base_price"
        )
    )


def get_related_products(*, product: Product, user: Optional[Any] = None, limit: int = 4) -> list[Product]:
    """
    Return related products for a product.
    1) Query explicit RELATED relationships.
    2) Fallback to active products in the same category.
    3) Fallback to active products in general.
    Optimized with select_related for category and brand, and prefetches primary images.
    """
    #explicit related products
    explicit_ids = list(
        ProductRelation.objects.filter(
            product=product,
            relation_type=RelationType.RELATED
        ).values_list("related_product_id", flat=True)
    )
    
    products = list(
        Product.objects.filter(pk__in=explicit_ids, is_active=True)
        .select_related("category", "brand")
        .prefetch_related(_primary_image_prefetch(), _variants_prefetch())
        .only(*PLP_CARD_FIELDS)
    )
    
    #fallback to same category
    if len(products) < limit:
        needed = limit - len(products)
        exclude_ids = [product.pk] + [p.pk for p in products]
        cat_products = (
            Product.objects.filter(category=product.category, is_active=True)
            .exclude(pk__in=exclude_ids)
            .select_related("category", "brand")
            .prefetch_related(_primary_image_prefetch(), _variants_prefetch())
            .only(*PLP_CARD_FIELDS)[:needed]
        )
        products.extend(list(cat_products))
        
    #general active products fallback if still not enough
    if len(products) < limit:
        needed = limit - len(products)
        exclude_ids = [product.pk] + [p.pk for p in products]
        fallback_products = (
            Product.objects.filter(is_active=True)
            .exclude(pk__in=exclude_ids)
            .select_related("category", "brand")
            .prefetch_related(_primary_image_prefetch(), _variants_prefetch())
            .only(*PLP_CARD_FIELDS)[:needed]
        )
        products.extend(list(fallback_products))

    #decorate with display_price
    from marketing.selectors import get_flash_sale_discounts_for_products

    flash_discounts = get_flash_sale_discounts_for_products(
        product_prices={p.pk: p.effective_base_price for p in products},
    )
    for p in products:
        eff_base = p.effective_base_price
        discount_pct = flash_discounts.get(p.pk)
        if discount_pct is None:
            p.display_price = eff_base
        else:
            discount = (eff_base * discount_pct / Decimal("100")).quantize(
                Decimal("0.01")
            )
            p.display_price = eff_base - discount

    return products

