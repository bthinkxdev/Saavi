"""Simple, clean inventory management view with variant product dropdowns and simple products."""

from __future__ import annotations

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Case, F, IntegerField, Q, Value, When
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from catalog.models import Category, Product, ProductVariant
from dashboard.access import dashboard_required


@dashboard_required
def inventory_list(request: HttpRequest) -> HttpResponse:
    """View products with variant dropdown on product name side and simple product stock."""
    search_query = request.GET.get("q", "").strip()
    category_id = request.GET.get("category", "").strip()
    status_filter = request.GET.get("status", "").strip()
    type_filter = request.GET.get("type", "").strip()

    qs = (
        Product.objects.all()
        .select_related("category", "homepage_featured")
        .prefetch_related(
            "variants__attribute_values__attribute",
            "images",
        )
        .order_by(
            Case(
                When(homepage_featured__is_shown=True, then=Value(1)),
                When(homepage_featured__is_shown=False, then=Value(-1)),
                default=Value(0),
                output_field=IntegerField(),
            ).desc(),
            Case(
                When(homepage_featured__is_shown=True, then=F("homepage_featured__updated_at")),
                default=None,
            ).desc(nulls_last=True),
            Case(
                When(homepage_featured__is_shown=False, then=F("homepage_featured__updated_at")),
                default=None,
            ).asc(nulls_last=True),
            "-created_at",
        )
    )

    if search_query:
        qs = qs.filter(
            Q(name__icontains=search_query)
            | Q(sku__icontains=search_query)
            | Q(variants__name__icontains=search_query)
            | Q(variants__sku_suffix__icontains=search_query)
        ).distinct()

    if category_id.isdigit():
        cat_id = int(category_id)
        subcat_ids = list(Category.objects.filter(parent_id=cat_id).values_list("id", flat=True))
        all_cat_ids = [cat_id] + subcat_ids
        qs = qs.filter(category_id__in=all_cat_ids)

    if type_filter == "variant":
        qs = qs.filter(variants__isnull=False).distinct()
    elif type_filter == "simple":
        qs = qs.filter(variants__isnull=True)

    if status_filter == "out":
        qs = qs.filter(
            Q(variants__stock_quantity=0)
            | Q(variants__isnull=True, stock_quantity=0)
        ).distinct()
    elif status_filter == "low":
        qs = qs.filter(
            Q(variants__stock_quantity__lte=F("variants__low_stock_threshold"), variants__stock_quantity__gt=0)
            | Q(variants__isnull=True, stock_quantity__lte=F("low_stock_threshold"), stock_quantity__gt=0)
        ).distinct()
    elif status_filter == "in":
        qs = qs.filter(
            Q(variants__stock_quantity__gt=F("variants__low_stock_threshold"))
            | Q(variants__isnull=True, stock_quantity__gt=F("low_stock_threshold"))
        ).distinct()

    paginator = Paginator(qs, 25)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    for product in page_obj:
        variants = list(product.variants.all())
        product.is_variant_product = bool(variants)

        if product.is_variant_product:
            if status_filter == "in":
                variants.sort(key=lambda v: (0 if v.stock_quantity > v.low_stock_threshold else 1, v.display_order, v.id))
            elif status_filter == "low":
                variants.sort(key=lambda v: (0 if 0 < v.stock_quantity <= v.low_stock_threshold else 1, v.display_order, v.id))
            elif status_filter == "out":
                variants.sort(key=lambda v: (0 if v.stock_quantity == 0 else 1, v.display_order, v.id))

            for v in variants:
                if v.stock_quantity == 0:
                    v.status_label = "Out of stock"
                    v.status_pill = "pill-red"
                elif v.stock_quantity <= v.low_stock_threshold:
                    v.status_label = f"{v.stock_quantity} left"
                    v.status_pill = "pill-amber"
                else:
                    v.status_label = f"{v.stock_quantity} in stock"
                    v.status_pill = "pill-green"

            product.variant_list = variants

            #overall product status indicator: when filtered, highlight the matching status first
            if status_filter == "in" and any(v.stock_quantity > v.low_stock_threshold for v in variants):
                product.status_label = f"{product.stock_quantity} in stock"
                product.status_pill = "pill-green"
            elif status_filter == "low" and any(0 < v.stock_quantity <= v.low_stock_threshold for v in variants):
                product.status_label = "Low stock"
                product.status_pill = "pill-amber"
            elif status_filter == "out" and any(v.stock_quantity == 0 for v in variants):
                if all(v.stock_quantity == 0 for v in variants):
                    product.status_label = "Out of stock"
                else:
                    product.status_label = "Some out of stock"
                product.status_pill = "pill-red"
            elif any(v.stock_quantity == 0 for v in variants):
                if all(v.stock_quantity == 0 for v in variants):
                    product.status_label = "Out of stock"
                    product.status_pill = "pill-red"
                else:
                    product.status_label = "Some out of stock"
                    product.status_pill = "pill-red"
            elif any(v.stock_quantity <= v.low_stock_threshold for v in variants):
                product.status_label = "Low stock"
                product.status_pill = "pill-amber"
            else:
                product.status_label = f"{product.stock_quantity} in stock"
                product.status_pill = "pill-green"
        else:
            product.variant_list = []
            if product.stock_quantity == 0:
                product.status_label = "Out of stock"
                product.status_pill = "pill-red"
            elif product.stock_quantity <= product.low_stock_threshold:
                product.status_label = f"{product.stock_quantity} left"
                product.status_pill = "pill-amber"
            else:
                product.status_label = f"{product.stock_quantity} in stock"
                product.status_pill = "pill-green"

    categories = Category.objects.order_by("name")

    context = {
        "nav_section": "inventory",
        "page_title": "Inventory",
        "page_obj": page_obj,
        "paginator": paginator,
        "categories": categories,
        "search_query": search_query,
        "category_filter": category_id,
        "status_filter": status_filter,
        "type_filter": type_filter,
    }
    return render(request, "dashboard/inventory/inventory_list.html", context)


@dashboard_required
@require_POST
def inventory_adjust_stock(request: HttpRequest) -> HttpResponse:
    """Inline stock adjustment for a variant or standalone simple product."""
    item_type = request.POST.get("item_type", "").strip()
    item_id = request.POST.get("item_id", "").strip()
    stock_str = request.POST.get("stock_quantity", "").strip()

    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    if not item_id.isdigit() or not stock_str.isdigit():
        if is_ajax:
            return JsonResponse({"success": False, "error": "Invalid input."}, status=400)
        messages.error(request, "Invalid stock value.")
        return redirect("dashboard:inventory-list")

    new_stock = int(stock_str)
    item_pk = int(item_id)

    if item_type == "variant":
        variant = get_object_or_404(ProductVariant.objects.select_related("product"), pk=item_pk)
        variant.stock_quantity = new_stock
        variant.save()
        sku = variant.sku_suffix or variant.product.sku
        threshold = variant.low_stock_threshold
        variant.product.refresh_from_db(fields=["stock_quantity"])
        parent_stock = variant.product.stock_quantity

        variants = list(variant.product.variants.all())
        if any(v.stock_quantity == 0 for v in variants):
            if all(v.stock_quantity == 0 for v in variants):
                parent_status_label = "Out of stock"
                parent_status_pill = "pill-red"
            else:
                parent_status_label = "Some out of stock"
                parent_status_pill = "pill-red"
        elif any(v.stock_quantity <= v.low_stock_threshold for v in variants):
            parent_status_label = "Low stock"
            parent_status_pill = "pill-amber"
        else:
            parent_status_label = f"{parent_stock} in stock"
            parent_status_pill = "pill-green"
    elif item_type == "product":
        product = get_object_or_404(Product, pk=item_pk)
        product.stock_quantity = new_stock
        product.save()
        sku = product.sku
        threshold = product.low_stock_threshold
        parent_stock = product.stock_quantity
        parent_status_label = None
        parent_status_pill = None
    else:
        if is_ajax:
            return JsonResponse({"success": False, "error": "Invalid item type."}, status=400)
        messages.error(request, "Invalid item type.")
        return redirect("dashboard:inventory-list")

    if new_stock == 0:
        status_label = "Out of stock"
        status_pill = "pill-red"
    elif new_stock <= threshold:
        status_label = f"{new_stock} left"
        status_pill = "pill-amber"
    else:
        status_label = f"{new_stock} in stock"
        status_pill = "pill-green"

    if item_type == "product":
        parent_status_label = status_label
        parent_status_pill = status_pill

    low_stock_count = (
        Product.objects.filter(is_active=True)
        .filter(
            Q(variants__stock_quantity__lte=F("variants__low_stock_threshold"))
            | Q(variants__isnull=True, stock_quantity__lte=F("low_stock_threshold"))
        )
        .distinct()
        .count()
    )

    msg = f"Stock updated for {sku} to {new_stock}."
    if is_ajax:
        return JsonResponse({
            "success": True,
            "new_stock": new_stock,
            "status_label": status_label,
            "status_pill": status_pill,
            "parent_stock": parent_stock,
            "parent_status_label": parent_status_label,
            "parent_status_pill": parent_status_pill,
            "low_stock_count": low_stock_count,
            "message": msg,
        })

    messages.success(request, msg)
    return redirect(request.META.get("HTTP_REFERER") or "dashboard:inventory-list")
