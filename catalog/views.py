"""HTTP views for the catalog app; thin request parsing delegating to selectors/services."""

from __future__ import annotations

import json

from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_GET, require_POST
from django.contrib.auth.decorators import login_required
from django.contrib import messages

from catalog.models import Product
from catalog.forms import ReviewSubmissionForm
from catalog.services import submit_review

from catalog.selectors import (
    get_category_by_slug,
    get_plp_filter_options,
    get_plp_products,
    get_product_detail,
    get_related_products,
    get_search_suggestions,
    get_variant_price,
    record_product_view,
)
from core.seo import build_plp_canonical_url, build_product_json_ld, resolve_meta_title, seo_context


def _parse_plp_filters(request: HttpRequest) -> dict:
    """Parse shareable PLP filter query params into a selector filter dict."""
    filters: dict = {}
    category_id = request.GET.get("category")
    subcategory_id = request.GET.get("subcategory")
    if subcategory_id:
        filters["category_id"] = int(subcategory_id)
        filters["subcategory_id"] = int(subcategory_id)
        if category_id:
            filters["parent_category_id"] = int(category_id)
    elif category_id:
        filters["category_id"] = int(category_id)

    if occasion_id := request.GET.get("occasion"):
        filters["occasion_id"] = int(occasion_id)
    if brand_id := request.GET.get("brand"):
        filters["brand_id"] = int(brand_id)
    if recipient_id := request.GET.get("recipient"):
        filters["recipient_id"] = int(recipient_id)
    if color := request.GET.get("color"):
        filters["color"] = color
    if request.GET.get("featured") == "1":
        filters["featured"] = True
    if request.GET.get("bestseller") == "1":
        filters["bestseller"] = True
    if request.GET.get("new_arrival") == "1":
        filters["new_arrival"] = True
    if availability := request.GET.get("availability"):
        filters["availability"] = availability
    
    try:
        from catalog.models import ProductAttribute
        valid_attrs = set(ProductAttribute.objects.values_list("name", flat=True))
        dynamic_attrs = {}
        selected_attr_values = []
        for attr_name in valid_attrs:
            values = request.GET.getlist(attr_name)
            if values:
                dynamic_attrs[attr_name] = values
                for v in values:
                    selected_attr_values.append(f"{attr_name}:{v}")
        if dynamic_attrs:
            filters["dynamic_attrs"] = dynamic_attrs
            filters["selected_attr_values"] = selected_attr_values
    except Exception:
        pass
    if min_price := request.GET.get("min_price"):
        filters["min_price"] = min_price
    if max_price := request.GET.get("max_price"):
        filters["max_price"] = max_price
    if q := request.GET.get("q"):
        filters["q"] = q
    if collection := request.GET.get("collection"):
        filters["collection"] = collection
    if flash_sale := request.GET.get("flash_sale"):
        filters["flash_sale"] = flash_sale
    return filters



@require_GET
def plp_view(request: HttpRequest, category_slug: str | None = None) -> HttpResponse:
    """Product listing page with HTMX partial support for the product grid."""
    filters = _parse_plp_filters(request)
    category = None
    if category_slug:
        category = get_category_by_slug(slug=category_slug)
        if category is None:
            raise Http404("Category not found")

        if not filters.get("subcategory_id"):
            filters["category_id"] = category.pk

    resolved_cat = category
    if not resolved_cat and (cat_id := filters.get("category_id")):
        from catalog.models import Category

        resolved_cat = Category.objects.filter(pk=cat_id, is_active=True).first()

    subcategories = []
    if resolved_cat:
        if resolved_cat.parent_id:
            subcategories = list(resolved_cat.parent.children.filter(is_active=True))
            filters["subcategory_id"] = resolved_cat.pk
            filters["parent_category_id"] = resolved_cat.parent_id
        else:
            subcategories = list(resolved_cat.children.filter(is_active=True))
            filters["parent_category_id"] = resolved_cat.pk

    sort = request.GET.get("sort", "newest")
    page = int(request.GET.get("page", 1))
    plp_data = get_plp_products(filters=filters, sort=sort, page=page, user=request.user)
    filter_options = get_plp_filter_options()

    active_cat = resolved_cat if resolved_cat else None
    
    active_collection = None
    if col_slug := filters.get("collection"):
        if col_slug == "all":
            active_collection = {"name": "All Collections", "slug": "all"}
            title = "All Collections"
            description = "Browse all curated saree and fine jewellery collections."
        else:
            from catalog.models import Collection

            c = Collection.objects.filter(slug=col_slug, is_active=True).first()
            if c:
                active_collection = c
                title = f"{c.name} Collection"
                description = c.description or f"Shop the {c.name} collection."
            else:
                title = "Collection"
                description = "Shop our curated collections."
    elif q := filters.get("q"):
        title = f'Search Results for "{q}"'
        description = f'Products matching "{q}"'
    elif filters.get("flash_sale"):
        title = "Festive Sales & Offers"
        description = "Shop limited-time festive offers and exclusive discounts on luxury sarees and jewellery."
    else:
        title = (
            resolve_meta_title(obj=active_cat, fallback="Shop All | Sarocchi Luxe Designs")
            if active_cat
            else "Shop All | Sarocchi Luxe Designs"
        )
        description = (
            f"Browse {active_cat.name} — luxury sarees and handcrafted jewellery."
            if active_cat
            else "Browse Premium Sarees & Handcrafted Jewellery - Sarocchi Luxe Designs."
        )



    context = seo_context(
        request=request,
        obj=active_cat,
        title=f"{title} | Sarocchi Luxe Designs",
        description=description,
        canonical_url=build_plp_canonical_url(request=request, category_slug=category_slug),
    )
    context.update(
        {
            "plp": plp_data,
            "filters": filters,
            "sort": sort,
            "categories": filter_options["categories"],
            "brands": filter_options["brands"],
            "collections": filter_options.get("collections", []),
            "subcategories": subcategories,
            "subcategories_map": filter_options.get("subcategories_map", {}),
            "attributes": filter_options.get("attributes", []),
            "active_category": active_cat,
            "active_collection": active_collection,
            "search_query": filters.get("q", ""),
        }
    )


    if request.headers.get("HX-Request") and not request.headers.get("HX-History-Restore-Request"):
        response = render(request, "catalog/partials/product_grid.html", context)
        response["HX-Push-Url"] = request.get_full_path()
    else:
        response = render(request, "catalog/plp.html", context)
    response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response["Pragma"] = "no-cache"
    return response


@require_GET
def pdp_view(request: HttpRequest, slug: str) -> HttpResponse:
    """Product detail page with gallery, variants, reviews, and delivery estimate."""
    product = get_product_detail(slug=slug)
    if product is None:
        raise Http404("Product not found")

    viewer_key = str(request.session.session_key or request.user.pk or "anon")
    record_product_view(viewer_key=viewer_key, product_id=product.pk)


    from core.services import get_site_settings

    site_settings = get_site_settings()

    from cart.models import CartItem
    from cart.selectors import get_cart_for_request

    cart = get_cart_for_request(request=request)
    variant_id = request.GET.get("variant_id")
    target_variant = None
    if variant_id and variant_id.isdigit():
        target_variant = product.variants.filter(pk=int(variant_id)).first()
    else:
        target_variant = product.display_variant

    cart_item = None
    if cart:
        if target_variant:
            cart_item = CartItem.objects.filter(cart=cart, product=product, variant=target_variant).first()
        else:
            cart_item = CartItem.objects.filter(cart=cart, product=product, variant__isnull=True).first()
    is_in_cart = cart_item is not None

    quantity = cart_item.quantity if cart_item else 1
    price_data = get_variant_price(product_id=product.pk, variant_id=target_variant.pk if target_variant else None, user=request.user, quantity=quantity)

    reviews = getattr(product, "approved_reviews", [])
    review_count = len(reviews)
    average_rating = None
    if review_count:
        average_rating = sum(r.rating for r in reviews) / review_count

    product.review_count = review_count
    product.average_rating = average_rating

    from accounts.models import WishlistItem
    from accounts.subscription_services import get_or_create_wishlist

    wishlist = get_or_create_wishlist(request=request)
    is_in_wishlist = WishlistItem.objects.filter(wishlist=wishlist, product_id=product.pk).exists()


    has_delivered_order = False
    if request.user.is_authenticated and hasattr(request.user, "customer_profile"):
        from orders.models import OrderItem, OrderStatus
        has_delivered_order = OrderItem.objects.filter(
            product=product,
            order__customer_profile=request.user.customer_profile,
            order__order_status=OrderStatus.DELIVERED
        ).exists()

    context = seo_context(
        request=request,
        obj=product,
        title=f"{product.name} | Sarocchi Luxe Designs",
        description=f"{product.name} — Luxury Sarees & Fine Jewellery from Sarocchi Luxe Designs",
    )
    context.update(
        {
            "product": product,
            "price_data": price_data,

            "whatsapp_number": site_settings.whatsapp_number,
            "is_in_cart": is_in_cart,
            "cart_item": cart_item,
            "selected_variant_id": target_variant.pk if target_variant else "",
            "target_variant": target_variant,
            "is_in_wishlist": is_in_wishlist,
            "related_products": get_related_products(product=product, user=request.user),
            "has_delivered_order": has_delivered_order,
            "cities": __import__('delivery.models', fromlist=['City']).City.objects.filter(is_active=True).order_by('name'),
            "default_estimated_delivery_text": site_settings.default_estimated_delivery_text,
            "product_json_ld": json.dumps(
                build_product_json_ld(
                    product=product,
                    price=price_data["price"],
                    request=request,
                    average_rating=average_rating,
                    review_count=review_count,
                )
            ),
        }
    )
    response = render(request, "catalog/pdp.html", context)
    response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response["Pragma"] = "no-cache"
    return response


@require_GET
def search_suggestions_view(request: HttpRequest) -> HttpResponse:
    """HTMX live search suggestions partial."""
    query = request.GET.get("q", "").strip()
    if len(query) < 2:
        response = render(
            request,
            "catalog/partials/search_suggestions.html",
            {
                "products": [],
                "brands": [],
                "categories": [],
                "equipment_types": [],
                "query": "",
            },
        )
        response.content = response.content.strip()
        return response
    suggestions = get_search_suggestions(query=query)
    context = {
        "products": suggestions.get("products", []),
        "brands": suggestions.get("brands", []),
        "categories": suggestions.get("categories", []),
        "equipment_types": suggestions.get("equipment_types", []),
        "query": query,
    }
    response = render(
        request,
        "catalog/partials/search_suggestions.html",
        context,
    )
    response.content = response.content.strip()
    return response


@require_GET
def variant_price_view(request: HttpRequest, product_id: int) -> JsonResponse:
    """JSON endpoint for variant price updates on PDP."""
    variant_id = request.GET.get("variant_id")
    quantity_str = request.GET.get("quantity", "1")
    try:
        quantity = int(quantity_str)
    except ValueError:
        quantity = 1
    parsed_variant = int(variant_id) if variant_id else None
    data = get_variant_price(product_id=product_id, variant_id=parsed_variant, user=request.user, quantity=quantity)
    
    from cart.models import CartItem
    from cart.selectors import get_cart_for_request
    
    cart = get_cart_for_request(request=request)
    cart_item = None
    if cart:
        if parsed_variant:
            cart_item = CartItem.objects.filter(cart=cart, product_id=product_id, variant_id=parsed_variant).first()
        else:
            cart_item = CartItem.objects.filter(cart=cart, product_id=product_id, variant__isnull=True).first()
    data["is_in_cart"] = cart_item is not None

    from core.selectors import get_currency_by_code, get_default_currency
    from core.templatetags.storefront_tags import money_label

    session_currency = request.session.get("storefront_currency", "")
    display_currency = (
        get_currency_by_code(code=session_currency) if session_currency else get_default_currency()
    )
    if "price" in data:
        data["formatted_price"] = money_label(data["price"], display_currency)
    if data.get("mrp"):
        data["formatted_mrp"] = money_label(data["mrp"], display_currency)
    if data.get("original_price"):
        data["formatted_original_price"] = money_label(data["original_price"], display_currency)

    return JsonResponse(data)


@require_GET


@require_GET
def rental_list_view(request: HttpRequest) -> HttpResponse:
    from catalog.selectors import _primary_image_prefetch, PLP_CARD_FIELDS
    products = (
        Product.objects.filter(is_active=True, is_rental=True, show_rental_storefront=True)
        .select_related("category", "brand")
        .prefetch_related(_primary_image_prefetch())
        .only(*PLP_CARD_FIELDS)
    )
    return render(request, "catalog/rentals.html", {"products": list(products)})

@require_POST
@login_required
def submit_review_view(request, product_id: int):
    """Handle product review submission from the customer order details page."""
    product = get_object_or_404(Product, pk=product_id, is_active=True)
    from catalog.forms import ReviewSubmissionForm
    form = ReviewSubmissionForm(request.POST)
    
    if not hasattr(request.user, "customer_profile"):
        messages.error(request, "Only customers can submit reviews.")
        return redirect(request.META.get('HTTP_REFERER', '/'))
        
    if form.is_valid():
        from catalog.services import submit_review
        submit_review(
            product=product,
            customer=request.user.customer_profile,
            rating=form.cleaned_data["rating"],
            title=form.cleaned_data["title"],
            body=form.cleaned_data["body"],
            is_verified_purchase=True,
        )
        messages.success(request, "Thank you for your valuable review!")
    else:
        messages.error(request, "There was an error with your review submission. Please check your inputs.")
        
    return redirect(request.META.get('HTTP_REFERER', '/'))
