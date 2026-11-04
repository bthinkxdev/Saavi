"""Structured admin forms per homepage section type — one entry per type."""

from __future__ import annotations

from django import forms

from cms.models import HomepageSectionType


class BaseSectionConfigForm(forms.Form):
    """Base for section config fields that serialize into HomepageSection.config."""

    def to_config(self) -> dict:
        return self.cleaned_data


class HeroSliderConfigForm(BaseSectionConfigForm):
    """Hero slides are managed via HeroSlide uploads — no section JSON caption config."""

    pass



class ProductCollectionConfigForm(BaseSectionConfigForm):
    product_ids = forms.CharField(
        help_text="Comma-separated product IDs",
        required=False,
    )
    collection_key = forms.CharField(max_length=80, required=False)
    brand_id = forms.IntegerField(
        required=False,
        min_value=1,
        help_text="Optional: limit this collection to a single brand (Brand Campaign).",
    )

    def to_config(self) -> dict:
        raw = self.cleaned_data.get("product_ids", "")
        ids = [int(x.strip()) for x in raw.split(",") if x.strip().isdigit()]
        config: dict = {"product_ids": ids}
        if self.cleaned_data.get("collection_key"):
            config["collection_key"] = self.cleaned_data["collection_key"]
        if self.cleaned_data.get("brand_id"):
            config["brand_id"] = self.cleaned_data["brand_id"]
        return config


class PromotionalSectionConfigForm(BaseSectionConfigForm):
    badge = forms.CharField(
        max_length=80,
        required=False,
        label="Promotional Badge / Tag",
        help_text="e.g. 'LIMITED OFFER', 'HOT DEAL', 'NEW DROP'",
        widget=forms.TextInput(attrs={"placeholder": "e.g. SPECIAL OFFER"}),
    )
    subtitle = forms.CharField(
        max_length=300,
        required=False,
        label="Promotional Description",
        help_text="Catchy promotional text describing the offer.",
        widget=forms.Textarea(
            attrs={
                "rows": 2,
                "placeholder": "e.g. Discover our exquisite bridal sarees and handcrafted heirloom jewellery.",
            }
        ),
    )
    image = forms.ImageField(
        required=False,
        label="Upload Banner Image",
        help_text="Upload a promotional banner image from your computer.",
    )
    button_text = forms.CharField(
        max_length=60,
        required=False,
        initial="Shop Now",
        label="Button Text",
        widget=forms.TextInput(attrs={"placeholder": "Shop Now"}),
    )
    destination = forms.ChoiceField(
        choices=[
            ("products", "Products (All Products)"),
            ("category", "Category"),
            ("collections", "Collections"),
            ("flash_sales", "Flash Sales / Deals"),
            ("coupons", "Coupons"),
        ],
        required=False,
        initial="category",
        label="Destination Section",
        help_text="Choose which section this promotional banner points to.",
    )
    target = forms.ChoiceField(
        required=False,
        label="Target Selection",
        help_text="Select 'All' or a specific category/collection to filter.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from catalog.models import Category, Collection, Product

        self._existing_image_url = (self.initial or {}).get("image_url", "")
        if not self._existing_image_url and self.data:
            self._existing_image_url = (self.initial or {}).get("image", "")

        target_choices = [
            ("products:all", "All Products"),
        ]
        try:
            for prod in Product.objects.filter(is_active=True).order_by("name"):
                target_choices.append((f"products:{prod.slug}", prod.name))
        except Exception:
            pass

        target_choices.append(("category:all", "All Categories"))
        try:
            for cat in Category.objects.filter(is_active=True).order_by("name"):
                target_choices.append((f"category:{cat.slug}", cat.name))
        except Exception:
            pass

        target_choices.append(("collections:all", "All Collections"))
        try:
            for col in Collection.objects.filter(is_active=True).order_by("name"):
                target_choices.append((f"collections:{col.slug}", col.name))
        except Exception:
            pass

        target_choices.append(("flash_sales:all", "All Active Flash Sales"))
        try:
            from marketing.models import FlashSale

            for fs in FlashSale.objects.filter(is_active=True).order_by("name"):
                target_choices.append((f"flash_sales:{fs.id}", fs.name))
        except Exception:
            pass

        target_choices.append(("coupons:all", "All Offers"))
        try:
            from marketing.models import Coupon

            for c in Coupon.objects.filter(is_active=True).order_by("code"):
                target_choices.append((f"coupons:{c.code}", c.code))
        except Exception:
            pass

        self.fields["target"].choices = target_choices



    def to_config(self) -> dict:
        data = self.cleaned_data
        image_url = getattr(self, "_existing_image_url", "")
        upload_img = data.get("image")
        if upload_img:
            from django.core.files.uploadedfile import UploadedFile

            if isinstance(upload_img, UploadedFile):
                from django.conf import settings
                from django.core.files.storage import default_storage

                saved_path = default_storage.save(f"cms/promotions/{upload_img.name}", upload_img)
                image_url = f"{settings.MEDIA_URL}{saved_path}"
            elif isinstance(upload_img, str) and upload_img.strip():
                image_url = upload_img.strip()

        if not image_url:
            image_url = (self.initial or {}).get("image_url") or (self.initial or {}).get("image") or ""

        destination = data.get("destination") or "products"
        target = data.get("target") or f"{destination}:all"

        return {
            "badge": data.get("badge", ""),
            "subtitle": data.get("subtitle", ""),
            "image_url": image_url,
            "button_text": data.get("button_text") or "Shop Now",
            "destination": destination,
            "target": target,
        }



MarketingFeaturesConfigForm = PromotionalSectionConfigForm


class BannerConfigForm(BaseSectionConfigForm):
    image_url = forms.URLField(
        required=False,
        help_text="Note: All banners should have the same resolution."
    )
    link_url = forms.URLField(required=False)
    subtitle = forms.CharField(max_length=200, required=False)


class InstagramConfigForm(BaseSectionConfigForm):
    instagram_handle = forms.CharField(max_length=80, required=False)
    post_urls = forms.CharField(
        widget=forms.Textarea,
        required=False,
        help_text="One image URL per line",
    )

    def to_config(self) -> dict:
        raw = self.cleaned_data.get("post_urls", "")
        urls = [line.strip() for line in raw.splitlines() if line.strip()]
        return {
            "instagram_handle": self.cleaned_data.get("instagram_handle", ""),
            "post_urls": urls,
        }


class CategoryProductsConfigForm(BaseSectionConfigForm):
    category_slug = forms.ChoiceField(
        required=False,
        help_text="Select 'All Categories' to show a grid for every category, or select a specific category."
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from catalog.models import Category
        try:
            choices = [("all", "All Categories")]
            for cat in Category.objects.filter(is_active=True, parent__isnull=True):
                choices.append((cat.slug, cat.name))
            self.fields["category_slug"].choices = choices
        except Exception:
            self.fields["category_slug"].choices = [("all", "All Categories")]


class FeaturedCollectionsConfigForm(BaseSectionConfigForm):
    collection_slugs = forms.MultipleChoiceField(
        required=False,
        widget=forms.SelectMultiple(attrs={"class": "form-select", "size": "6"}),
        help_text="Select one or more collections to feature. Hold Ctrl/Cmd to select multiple.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from catalog.models import Collection
        try:
            self.fields["collection_slugs"].choices = [
                (col.slug, col.name)
                for col in Collection.objects.filter(is_active=True).order_by("name")
            ]
        except Exception:
            self.fields["collection_slugs"].choices = []

    def to_config(self) -> dict:
        slugs = self.cleaned_data.get("collection_slugs", [])
        return {"collection_slugs": slugs}


class EmptyConfigForm(BaseSectionConfigForm):
    """Sections that need no extra config."""


SECTION_CONFIG_FORMS: dict[str, type[BaseSectionConfigForm]] = {
    HomepageSectionType.HERO_SLIDER: HeroSliderConfigForm,
    HomepageSectionType.SHOP_BY_CATEGORY: EmptyConfigForm,
    HomepageSectionType.FEATURED_PRODUCTS: EmptyConfigForm,
    HomepageSectionType.NEW_ARRIVALS: EmptyConfigForm,
    HomepageSectionType.BEST_SELLERS: EmptyConfigForm,
    HomepageSectionType.FEATURED_BRANDS: EmptyConfigForm,
    HomepageSectionType.SUBSCRIPTION_BANNER: BannerConfigForm,
    HomepageSectionType.MARKETING_FEATURES: MarketingFeaturesConfigForm,
    HomepageSectionType.REVIEWS: EmptyConfigForm,
    HomepageSectionType.INSTAGRAM_GALLERY: InstagramConfigForm,
    HomepageSectionType.NEWSLETTER: EmptyConfigForm,
    HomepageSectionType.CATEGORY_PRODUCTS: CategoryProductsConfigForm,
    HomepageSectionType.FEATURED_COLLECTIONS: FeaturedCollectionsConfigForm,
}


def get_section_config_form(
    *, section_type: str, initial: dict | None = None
) -> BaseSectionConfigForm:
    """Return the structured config form for a section type."""
    form_class = SECTION_CONFIG_FORMS.get(section_type, EmptyConfigForm)
    initial_data = _flatten_config_for_form(section_type=section_type, config=initial or {})
    return form_class(initial=initial_data)


def _flatten_config_for_form(*, section_type: str, config: dict) -> dict:
    """Map stored JSON config to form initial values."""
    if section_type == HomepageSectionType.MARKETING_FEATURES:
        dest = config.get("destination")
        if not dest:
            lt = config.get("link_type", "category")
            dest = "collections" if lt == "collection" else ("flash_sales" if lt == "flash_sale" else lt)
        target = config.get("target")
        if not target:
            if dest == "category":
                cslug = config.get("category_slug")
                target = f"category:{cslug}" if cslug else "category:all"
            elif dest == "collections":
                cslug = config.get("collection_slug")
                target = f"collections:{cslug}" if cslug else "collections:all"
            else:
                target = f"{dest}:all"
        img = config.get("image_url", "")
        return {
            "badge": config.get("badge", ""),
            "subtitle": config.get("subtitle", ""),
            "image": img,
            "image_url": img,
            "button_text": config.get("button_text", "Shop Now"),
            "destination": dest,
            "target": target,
        }
    if section_type == HomepageSectionType.INSTAGRAM_GALLERY:
        return {
            "instagram_handle": config.get("instagram_handle", ""),
            "post_urls": "\n".join(config.get("post_urls", [])),
        }
    if section_type == HomepageSectionType.FEATURED_COLLECTIONS:
        return {
            "collection_slugs": config.get("collection_slugs", []),
        }
    if section_type == HomepageSectionType.HERO_SLIDER:
        return {}
    return {k: v for k, v in config.items() if isinstance(v, (str, int, float, bool))}


def config_from_form(*, section_type: str, form: BaseSectionConfigForm) -> dict:
    """Serialize a validated config form back to JSON storage."""
    if not form.is_valid():
        return {}
    data = form.to_config()
    if section_type == HomepageSectionType.HERO_SLIDER:
        return {}
    return data
