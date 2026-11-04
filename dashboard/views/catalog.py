"""Catalog management views: products, categories, occasions, brands, recipients, reviews."""

from __future__ import annotations

from django.contrib import messages
from django.db.models import F, Case, When, Value, IntegerField
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from catalog.models import Brand, Category, Product, Review, HomePageProduct, SizeChart, Collection
from core.models import Currency
from dashboard import forms
from dashboard.access import dashboard_required
from dashboard.views.base import (
    DashboardCreateView,
    DashboardDeleteView,
    DashboardListView,
    DashboardUpdateView,
)


class ProductListView(DashboardListView):
    model = Product
    template_name = "dashboard/catalog/product_list.html"
    nav_section = "products"
    url_basename = "product"
    singular_name = "Product"
    plural_name = "Products"
    search_fields = ["name", "sku"]
    select_related = ["category", "brand", "homepage_featured"]
    prefetch_related = ["images"]
    paginate_by = 20

    def get_queryset(self):
        qs = super().get_queryset()
        status = self.request.GET.get("status", "")
        top_product_ids = None
        if status == "active":
            qs = qs.filter(is_active=True)
        elif status == "inactive":
            qs = qs.filter(is_active=False)
        elif status == "low":
            qs = qs.filter(stock_quantity__lte=F("low_stock_threshold"), stock_quantity__gt=0)
        elif status == "out":
            qs = qs.filter(stock_quantity=0)
        elif status == "top":
            from django.db.models import Sum
            from orders.models import OrderItem
            from orders.services import REVENUE_ORDER_STATUSES
            top_product_ids = list(
                OrderItem.objects.filter(order__order_status__in=REVENUE_ORDER_STATUSES)
                .values("product_id")
                .annotate(total_revenue=Sum(F("unit_price") * F("quantity")))
                .filter(total_revenue__gt=0)
                .order_by("-total_revenue")
                .values_list("product_id", flat=True)
            )
            if top_product_ids:
                qs = qs.filter(id__in=top_product_ids)
            else:
                qs = qs.none()

        category = self.request.GET.get("category", "")
        if category.isdigit():
            category_id = int(category)
            category_ids = [category_id]
            category_ids.extend(
                Category.objects.filter(parent_id=category_id).values_list("id", flat=True)
            )
            qs = qs.filter(category_id__in=category_ids)
            
        collection = self.request.GET.get("collection", "")
        if collection.isdigit():
            qs = qs.filter(collections__id=int(collection))
            
        if status == "top" and top_product_ids:
            preserved_order = Case(*[When(pk=pk, then=Value(pos)) for pos, pk in enumerate(top_product_ids)], output_field=IntegerField())
            return qs.order_by(preserved_order)
            
        #sort pinned products to the top, toggled-off to the bottom
        qs = qs.order_by(
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
        return qs

    STATUS_FILTER_LABELS = {
        "active": "Active",
        "inactive": "Inactive",
        "low": "Low Stock",
        "out": "Out of Stock",
        "top": "Top Selling",
    }

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        default_currency = Currency.objects.filter(is_default=True).first()
        context["currency_symbol"] = default_currency.symbol if default_currency else ""
        context["categories"] = Category.objects.order_by("name")
        context["collections"] = Collection.objects.order_by("name")
        status_filter = self.request.GET.get("status", "")
        category_filter = self.request.GET.get("category", "")
        collection_filter = self.request.GET.get("collection", "")
        context["status_filter"] = status_filter
        context["category_filter"] = category_filter
        context["collection_filter"] = collection_filter

        active_filters = []
        if status_filter:
            params = self.request.GET.copy()
            params.pop("status", None)
            active_filters.append({
                "label": self.STATUS_FILTER_LABELS.get(status_filter, status_filter),
                "clear_url": f"{self.request.path}?{params.urlencode()}" if params else self.request.path,
            })
        if category_filter:
            category = Category.objects.filter(pk=category_filter).first()
            params = self.request.GET.copy()
            params.pop("category", None)
            active_filters.append({
                "label": category.name if category else "Category",
                "clear_url": f"{self.request.path}?{params.urlencode()}" if params else self.request.path,
            })
        if collection_filter:
            collection = Collection.objects.filter(pk=collection_filter).first()
            params = self.request.GET.copy()
            params.pop("collection", None)
            active_filters.append({
                "label": collection.name if collection else "Collection",
                "clear_url": f"{self.request.path}?{params.urlencode()}" if params else self.request.path,
            })
        context["active_filters"] = active_filters
        return context


class ProductDeleteView(DashboardDeleteView):
    model = Product
    nav_section = "products"
    url_basename = "product"
    singular_name = "Product"


def _render_product_form(request, product, mode):
    from catalog.models import ProductVariant, ProductAttribute, ProductAttributeValue, ProductTag, ProductLabel
    from django.utils.text import slugify
    if request.method == "POST":
        post_data = request.POST.copy()
        
        # handle dynamically created tags
        tag_values = post_data.getlist("tags")
        new_tag_ids = []
        for val in tag_values:
            if val and not val.isdigit():
                tag_name = val.strip()
                tag = ProductTag.objects.filter(name__iexact=tag_name).first()
                if not tag:
                    base_slug = slugify(tag_name) or "tag"
                    unique_slug = base_slug
                    counter = 1
                    while ProductTag.objects.filter(slug=unique_slug).exists():
                        unique_slug = f"{base_slug}-{counter}"
                        counter += 1
                    tag = ProductTag.objects.create(name=tag_name, slug=unique_slug)
                new_tag_ids.append(str(tag.id))
            elif val:
                new_tag_ids.append(val)
        if tag_values:
            post_data.setlist("tags", new_tag_ids)
            
        # handle dynamically created labels
        label_values = post_data.getlist("labels")
        new_label_ids = []
        for val in label_values:
            if val and not val.isdigit():
                label, _ = ProductLabel.objects.get_or_create(name=val.strip(), defaults={"color": "#000000"})
                new_label_ids.append(str(label.id))
            elif val:
                new_label_ids.append(val)
        if label_values:
            post_data.setlist("labels", new_label_ids)

        form = forms.ProductForm(post_data, request.FILES, instance=product)
        images = forms.ProductImageFormSet(
            post_data, request.FILES, instance=product, prefix="images"
        )
        videos = forms.ProductVideoFormSet(
            post_data, request.FILES, instance=product, prefix="videos"
        )
        specifications = forms.ProductSpecificationFormSet(
            post_data, instance=product, prefix="specifications"
        )
        if (
            form.is_valid()
            and images.is_valid()
            and videos.is_valid()
            and specifications.is_valid()
        ):
            has_variants = request.POST.get("has_variants") == "on"
            v_sku_suffixes = []
            
            if has_variants:
                v_sku_suffixes = request.POST.getlist("variant_sku_suffix[]")
                if not any(v.strip() for v in v_sku_suffixes):
                    has_variants = False
            
            variants_valid = True
            
            if has_variants:
                v_stocks = request.POST.getlist("variant_stock_quantity[]")
                v_low_stocks = request.POST.getlist("variant_low_stock_threshold[]")
                v_base_prices = request.POST.getlist("variant_base_price[]")
                v_mrps = request.POST.getlist("variant_mrp[]")
                v_purchase_prices = request.POST.getlist("variant_purchase_price[]")
                v_names = request.POST.getlist("variant_name[]")
                
                for i in range(len(v_sku_suffixes)):
                    suffix_name = v_names[i].strip() if i < len(v_names) and v_names[i].strip() else (v_sku_suffixes[i] if v_sku_suffixes[i] else f"Variant {i+1}")
                    
                    if i >= len(v_base_prices) or not str(v_base_prices[i]).strip():
                        messages.error(request, f"Base price is required for variant '{suffix_name}'.")
                        variants_valid = False
                        break
                        
                    if i >= len(v_stocks) or not str(v_stocks[i]).strip():
                        messages.error(request, f"Stock quantity is required for variant '{suffix_name}'.")
                        variants_valid = False
                        break
                        
                    try:
                        stock = int(v_stocks[i])
                    except ValueError:
                        messages.error(request, f"Invalid stock quantity for variant '{suffix_name}'.")
                        variants_valid = False
                        break
                        
                    try:
                        low_stock = int(v_low_stocks[i]) if i < len(v_low_stocks) and str(v_low_stocks[i]).strip() else 5
                    except ValueError:
                        low_stock = 5
                        
                    try:
                        base_price = float(v_base_prices[i])
                    except ValueError:
                        messages.error(request, f"Invalid base price for variant '{suffix_name}'.")
                        variants_valid = False
                        break
                        
                    try:
                        mrp = float(v_mrps[i]) if i < len(v_mrps) and str(v_mrps[i]).strip() else 0.0
                        purchase_price = float(v_purchase_prices[i]) if i < len(v_purchase_prices) and str(v_purchase_prices[i]).strip() else 0.0
                    except ValueError:
                        mrp = purchase_price = 0.0
                        
                    if stock < 0 or low_stock < 0 or base_price < 0 or mrp < 0 or purchase_price < 0:
                        messages.error(request, f"Variant '{suffix_name}' cannot have negative price or stock values.")
                        variants_valid = False
                        break
            
            if variants_valid:
                product = form.save()
                
                if has_variants:
                    dynamic_attr_names = request.POST.getlist("dynamic_attr_name[]")
                    dynamic_attr_values = request.POST.getlist("dynamic_attr_values[]")
                    
                    product_attr_ids = []
                    for i in range(len(dynamic_attr_names)):
                        attr_name = dynamic_attr_names[i].strip()
                        vals_str = dynamic_attr_values[i].strip()
                        if attr_name and vals_str:
                            attr_obj, _ = ProductAttribute.objects.get_or_create(name=attr_name)
                            vals = [v.strip() for v in vals_str.split(",") if v.strip()]
                            for v in vals:
                                val_obj, _ = ProductAttributeValue.objects.get_or_create(attribute=attr_obj, value=v)
                                product_attr_ids.append(val_obj.id)
                    
                    product.attribute_values.set(product_attr_ids)
                    
                    updated_variant_ids = []
                    
                    v_dynamic_attributes = request.POST.getlist("variant_dynamic_attributes[]")
                    
                    total_stock = 0
                    for i in range(len(v_sku_suffixes)):
                        sku_suffix = v_sku_suffixes[i] if i < len(v_sku_suffixes) else ""
                        try:
                            stock = int(v_stocks[i]) if i < len(v_stocks) and v_stocks[i] else 0
                        except ValueError:
                            stock = 0
                            
                        try:
                            low_stock = int(v_low_stocks[i]) if i < len(v_low_stocks) and v_low_stocks[i] else 5
                        except ValueError:
                            low_stock = 5
                        try:
                            base_price = float(v_base_prices[i]) if i < len(v_base_prices) and v_base_prices[i] else 0.0
                            mrp = float(v_mrps[i]) if i < len(v_mrps) and v_mrps[i] else 0.0
                            purchase_price = float(v_purchase_prices[i]) if i < len(v_purchase_prices) and v_purchase_prices[i] else 0.0
                        except ValueError:
                            base_price = mrp = purchase_price = 0.0
                            
                        dynamic_attrs_str = v_dynamic_attributes[i] if i < len(v_dynamic_attributes) else ""
                        
                        default_name = f"{product.name} - {sku_suffix}" if sku_suffix else product.name
                        variant_name = v_names[i].strip() if i < len(v_names) and v_names[i].strip() else default_name
                        
                        variant = ProductVariant.objects.filter(product=product, sku_suffix=sku_suffix).first()
                        if variant:
                            variant.stock_quantity = stock
                            variant.low_stock_threshold = low_stock
                            variant.base_price = base_price
                            variant.mrp = mrp
                            variant.purchase_price = purchase_price
                            variant.display_order = i
                            variant.name = variant_name
                            variant.save()
                        else:
                            variant = ProductVariant.objects.create(
                                product=product,
                                sku_suffix=sku_suffix,
                                stock_quantity=stock,
                                low_stock_threshold=low_stock,
                                base_price=base_price,
                                mrp=mrp,
                                purchase_price=purchase_price,
                                display_order=i,
                                name=variant_name
                            )
                        updated_variant_ids.append(variant.pk)
                        
                        if dynamic_attrs_str:
                            attr_val_ids = []
                            for pair in dynamic_attrs_str.split("|"):
                                if ":" in pair:
                                    attr_name, val_name = pair.split(":", 1)
                                    attr_name = attr_name.strip()
                                    val_name = val_name.strip()
                                    if attr_name and val_name:
                                        attr_obj, _ = ProductAttribute.objects.get_or_create(name=attr_name)
                                        val_obj, _ = ProductAttributeValue.objects.get_or_create(attribute=attr_obj, value=val_name)
                                        attr_val_ids.append(val_obj.id)
                            if attr_val_ids:
                                variant.attribute_values.set(attr_val_ids)
                                
                        total_stock += stock
                        
                    product.variants.exclude(pk__in=updated_variant_ids).delete()
                    
                    product.stock_quantity = total_stock
                    if v_base_prices and v_base_prices[0]:
                        product.base_price = float(v_base_prices[0])
                        product.mrp = float(v_mrps[0]) if v_mrps[0] else 0.0
                        product.purchase_price = float(v_purchase_prices[0]) if v_purchase_prices[0] else 0.0
                    product.save(update_fields=["stock_quantity", "base_price", "mrp", "purchase_price"])
                else:
                    product.variants.all().delete()
                    product.attribute_values.clear()

                def save_media_formset(formset):
                    formset.instance = product
                    instances = formset.save(commit=False)
                    
                    all_instances = list(instances)
                    for f in formset.initial_forms:
                        if f not in formset.deleted_forms and f.instance not in all_instances:
                            all_instances.append(f.instance)
                            
                    for instance in all_instances:
                        for f in formset.forms:
                            if f.instance == instance:
                                sku = f.cleaned_data.get('variant_sku')
                                if sku and sku != "all":
                                    instance.variant = product.variants.filter(sku_suffix=sku).first()
                                else:
                                    instance.variant = None
                                break
                        instance.save()
                    for obj in formset.deleted_objects:
                        obj.delete()
    
                save_media_formset(images)
                save_media_formset(videos)
                
                specifications.instance = product
                specifications.save()
                
                if product.stock_quantity == 0:
                    messages.warning(request, f"Product '{product.name}' saved with 0 stock. It will appear as 'Sold Out' in the storefront.")
                else:
                    messages.success(request, f"Product '{product.name}' saved successfully.")
                    
                from django.utils.http import url_has_allowed_host_and_scheme
                next_url = request.POST.get("next") or request.GET.get("next")
                if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
                    return redirect(next_url)
                return redirect("dashboard:product-list")

    else:
        form = forms.ProductForm(instance=product)
        images = forms.ProductImageFormSet(instance=product, prefix="images")
        videos = forms.ProductVideoFormSet(instance=product, prefix="videos")
        specifications = forms.ProductSpecificationFormSet(
            instance=product, prefix="specifications"
        )

    for f in [
        form,
        *images.forms,
        images.empty_form,
        *videos.forms,
        videos.empty_form,
        *specifications.forms,
        specifications.empty_form,
    ]:
        _style(f)

    attributes = ProductAttribute.objects.prefetch_related("values").all()
    existing_variants = []
    has_existing_variants = False
    dynamic_options = {}
    
    if request.method == "POST":
        has_existing_variants = request.POST.get("has_variants") == "on"
        if has_existing_variants:
            v_sku_suffixes = request.POST.getlist("variant_sku_suffix[]")
            v_stocks = request.POST.getlist("variant_stock_quantity[]")
            v_low_stocks = request.POST.getlist("variant_low_stock_threshold[]")
            v_base_prices = request.POST.getlist("variant_base_price[]")
            v_mrps = request.POST.getlist("variant_mrp[]")
            v_purchase_prices = request.POST.getlist("variant_purchase_price[]")
            v_dynamic_attributes = request.POST.getlist("variant_dynamic_attributes[]")
            v_names = request.POST.getlist("variant_name[]")
            
            for i in range(len(v_sku_suffixes)):
                dynamic_attrs_str = v_dynamic_attributes[i] if i < len(v_dynamic_attributes) else ""
                name_parts = []
                for pair in dynamic_attrs_str.split("|"):
                    if ":" in pair:
                        attr_name, val_name = pair.split(":", 1)
                        attr_name = attr_name.strip()
                        val_name = val_name.strip()
                        name_parts.append(val_name)
                        
                        if attr_name not in dynamic_options:
                            dynamic_options[attr_name] = []
                        if val_name not in dynamic_options[attr_name]:
                            dynamic_options[attr_name].append(val_name)
                            
                name = v_names[i].strip() if i < len(v_names) and v_names[i].strip() else " - ".join(name_parts)
                if not name:
                    name = v_sku_suffixes[i] if i < len(v_sku_suffixes) and v_sku_suffixes[i] else f"Variant {i+1}"
                
                existing_variants.append({
                    "name": name,
                    "sku_suffix": v_sku_suffixes[i] if i < len(v_sku_suffixes) else "",
                    "stock_quantity": v_stocks[i] if i < len(v_stocks) else "0",
                    "low_stock_threshold": v_low_stocks[i] if i < len(v_low_stocks) else "5",
                    "base_price": v_base_prices[i] if i < len(v_base_prices) else "0.00",
                    "mrp": v_mrps[i] if i < len(v_mrps) else "0.00",
                    "purchase_price": v_purchase_prices[i] if i < len(v_purchase_prices) else "0.00",
                    "post_attr_string": dynamic_attrs_str
                })
    else:
        has_existing_variants = False
        if product:
            has_existing_variants = product.variants.exists() or product.attribute_values.exists()
            
            for av in product.attribute_values.select_related("attribute").all():
                if av.attribute.name not in dynamic_options:
                    dynamic_options[av.attribute.name] = []
                if av.value not in dynamic_options[av.attribute.name]:
                    dynamic_options[av.attribute.name].append(av.value)

        if has_existing_variants:
            for variant in product.variants.prefetch_related("attribute_values").all():
                attr_str = "|".join([f"{av.attribute.name}:{av.value}" for av in variant.attribute_values.all()])
                
                attr_vals = [av.value for av in variant.attribute_values.all()]
                if variant.name:
                    prefix = f"{product.name} - "
                    if variant.name.startswith(prefix) and attr_vals:
                        display_name = " - ".join(attr_vals)
                    else:
                        display_name = variant.name
                elif attr_vals:
                    display_name = " - ".join(attr_vals)
                else:
                    display_name = variant.sku_suffix or f"Variant {variant.id}"
                    
                for av in variant.attribute_values.all():
                    if av.attribute.name not in dynamic_options:
                        dynamic_options[av.attribute.name] = []
                    if av.value not in dynamic_options[av.attribute.name]:
                        dynamic_options[av.attribute.name].append(av.value)
                    
                existing_variants.append({
                    "name": display_name,
                    "sku_suffix": variant.sku_suffix,
                    "stock_quantity": variant.stock_quantity,
                    "low_stock_threshold": variant.low_stock_threshold,
                    "base_price": variant.base_price,
                    "mrp": variant.mrp,
                    "purchase_price": variant.purchase_price,
                    "post_attr_string": attr_str
                })

    dynamic_options_list = [
        {"name": k, "values": ", ".join(v)}
        for k, v in dynamic_options.items()
    ]

    context = {
        "nav_section": "products",
        "page_title": f"{'Add' if mode == 'create' else 'Edit'} Product",
        "form": form,
        "images": images,
        "videos": videos,
        "specifications": specifications,
        "form_mode": mode,
        "product": product,
        "attributes": attributes,
        "has_existing_variants": has_existing_variants,
        "existing_variants": existing_variants,
        "dynamic_options_list": dynamic_options_list,
        "cancel_url": (
            request.POST.get("next")
            or request.GET.get("next")
            or reverse("dashboard:product-list")
        ),
    }
    
    return render(request, "dashboard/catalog/product_form.html", context)


def _style(form):
    """Apply Bootstrap classes to a form's widgets (shared with generic mixin)."""
    for field in form.fields.values():
        widget = field.widget
        css = widget.attrs.get("class", "")
        name = widget.__class__.__name__.lower()
        if "checkbox" in name:
            widget.attrs["class"] = (css + " form-check-input").strip()
        elif "select" in name:
            widget.attrs["class"] = (css + " form-select").strip()
        elif "file" in name:
            widget.attrs["class"] = (css + " form-control").strip()
        else:
            widget.attrs["class"] = (css + " form-control").strip()


@dashboard_required
@require_http_methods(["GET", "POST"])
def product_create(request):
    return _render_product_form(request, None, "create")


@dashboard_required
@require_http_methods(["GET", "POST"])
def product_update(request, pk):
    product = get_object_or_404(Product, pk=pk)
    return _render_product_form(request, product, "edit")


@dashboard_required
@require_http_methods(["POST"])
def product_home_toggle(request, pk):
    product = get_object_or_404(Product, pk=pk)
    home_prod, created = HomePageProduct.objects.get_or_create(product=product)
    
    #toggle the state
    home_prod.is_shown = not home_prod.is_shown
    home_prod.save()
    
    if home_prod.is_shown:
        messages.success(request, f"{product.name} order set as first.")
    else:
        messages.info(request, f"{product.name} order set as last.")
        
    return redirect("dashboard:product-list")


class CategoryListView(DashboardListView):
    model = Category
    nav_section = "categories"
    url_basename = "category"
    singular_name = "Category"
    plural_name = "Categories"
    search_fields = ["name", "slug"]
    filter_by_active_status = True
    columns = [
        {"label": "Name", "name": "name"},
        {"label": "Slug", "name": "slug"},
        {"label": "Parent", "name": "parent.name"},
        {"label": "Order", "name": "display_order"},
        {"label": "Active", "name": "is_active", "type": "bool"},
    ]


class CategoryCreateView(DashboardCreateView):
    model = Category
    form_class = forms.CategoryForm
    nav_section = "categories"
    url_basename = "category"
    singular_name = "Category"


class CategoryUpdateView(DashboardUpdateView):
    model = Category
    form_class = forms.CategoryForm
    nav_section = "categories"
    url_basename = "category"
    singular_name = "Category"
    template_name = "dashboard/catalog/category_form.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        category_id = self.object.pk
        category_ids = [category_id]
        category_ids.extend(
            Category.objects.filter(parent_id=category_id).values_list("id", flat=True)
        )
        qs = Product.objects.filter(category_id__in=category_ids).prefetch_related("images")
        context["product_count"] = qs.count()
        context["category_products"] = qs.order_by('-created_at')[:7]
        from core.models import Currency
        default_currency = Currency.objects.filter(is_default=True).first()
        context["currency_symbol"] = default_currency.symbol if default_currency else ""
        return context


class CategoryDeleteView(DashboardDeleteView):
    model = Category
    nav_section = "categories"
    url_basename = "category"
    singular_name = "Category"


class CollectionListView(DashboardListView):
    model = Collection
    nav_section = "collections"
    url_basename = "collection"
    singular_name = "Collection"
    plural_name = "Collections"
    search_fields = ["name", "slug"]
    filter_by_active_status = True
    columns = [
        {"label": "Name", "name": "name"},
        {"label": "Slug", "name": "slug"},
        {"label": "Active", "name": "is_active", "type": "bool"},
    ]


class CollectionCreateView(DashboardCreateView):
    model = Collection
    form_class = forms.CollectionForm
    nav_section = "collections"
    url_basename = "collection"
    singular_name = "Collection"


class CollectionUpdateView(DashboardUpdateView):
    model = Collection
    form_class = forms.CollectionForm
    nav_section = "collections"
    url_basename = "collection"
    singular_name = "Collection"
    template_name = "dashboard/catalog/collection_form.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        qs = Product.objects.filter(collections=self.object).prefetch_related("images")
        context["product_count"] = qs.count()
        context["collection_products"] = qs.order_by('-created_at')[:7]
        from core.models import Currency
        default_currency = Currency.objects.filter(is_default=True).first()
        context["currency_symbol"] = default_currency.symbol if default_currency else ""
        return context


class CollectionDeleteView(DashboardDeleteView):
    model = Collection
    nav_section = "collections"
    url_basename = "collection"
    singular_name = "Collection"



class BrandListView(DashboardListView):
    model = Brand
    nav_section = "brands"
    url_basename = "brand"
    singular_name = "Brand"
    plural_name = "Brands"
    search_fields = ["name", "slug"]
    filter_by_featured_status = True
    columns = [
        {"label": "Name", "name": "name"},
        {"label": "Slug", "name": "slug"},
        {"label": "Featured", "name": "is_featured", "type": "bool"},
    ]


class BrandCreateView(DashboardCreateView):
    model = Brand
    form_class = forms.BrandForm
    nav_section = "brands"
    url_basename = "brand"
    singular_name = "Brand"


class BrandUpdateView(DashboardUpdateView):
    model = Brand
    form_class = forms.BrandForm
    nav_section = "brands"
    url_basename = "brand"
    singular_name = "Brand"


class BrandDeleteView(DashboardDeleteView):
    model = Brand
    nav_section = "brands"
    url_basename = "brand"
    singular_name = "Brand"



class SizeChartListView(DashboardListView):
    model = SizeChart
    nav_section = "size_charts"
    url_basename = "sizechart"
    singular_name = "Size Chart"
    plural_name = "Size Charts"
    search_fields = ["name"]
    filter_by_active_status = True
    columns = [
        {"label": "Name", "name": "name"},
        {"label": "Created At", "name": "created_at", "type": "datetime"},
        {"label": "Active", "name": "is_active", "type": "bool"},
    ]


class SizeChartCreateView(DashboardCreateView):
    model = SizeChart
    form_class = forms.SizeChartForm
    nav_section = "size_charts"
    url_basename = "sizechart"
    singular_name = "Size Chart"
    template_name = "dashboard/catalog/sizechart_form.html"


class SizeChartUpdateView(DashboardUpdateView):
    model = SizeChart
    form_class = forms.SizeChartForm
    nav_section = "size_charts"
    url_basename = "sizechart"
    singular_name = "Size Chart"
    template_name = "dashboard/catalog/sizechart_form.html"


class SizeChartDeleteView(DashboardDeleteView):
    model = SizeChart
    nav_section = "size_charts"
    url_basename = "sizechart"
    singular_name = "Size Chart"



class ReviewListView(DashboardListView):
    model = Review
    nav_section = "reviews"
    url_basename = "review"
    singular_name = "Review"
    plural_name = "Reviews"
    select_related = ["product", "customer__user"]
    can_create = False
    columns = [
        {"label": "Product", "name": "product.name"},
        {"label": "Rating", "name": "rating"},
        {"label": "Title", "name": "title"},
        {"label": "Status", "name": "get_moderation_status_display", "type": "badge"},
        {"label": "Submitted", "name": "created_at", "type": "datetime"},
    ]


class ReviewUpdateView(DashboardUpdateView):
    model = Review
    form_class = forms.ReviewForm
    nav_section = "reviews"
    url_basename = "review"
    singular_name = "Review"

    def form_valid(self, form):
        form.instance.moderated_by = self.request.user
        
        #clear notification 
        original_review = self.get_object()
        from notifications.models import Notification
        body_text = f'Review "{original_review.title}" on {original_review.product.name} awaits approval.'
        Notification.objects.filter(
            title="Review pending moderation", 
            body=body_text,
            is_read=False
        ).update(is_read=True)
        
        return super().form_valid(form)


class ReviewDeleteView(DashboardDeleteView):
    model = Review
    nav_section = "reviews"
    url_basename = "review"
    singular_name = "Review"

    def form_valid(self, form):
        #clear notification 
        original_review = self.get_object()
        from notifications.models import Notification
        body_text = f'Review "{original_review.title}" on {original_review.product.name} awaits approval.'
        Notification.objects.filter(
            title="Review pending moderation", 
            body=body_text,
            is_read=False
        ).update(is_read=True)
        
        return super().form_valid(form)
