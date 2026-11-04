"""ModelForms used by the admin dashboard CRUD screens."""

from __future__ import annotations

from django import forms
from django.utils.text import slugify

from accounts.models import CustomerProfile
from catalog.models import (
    Brand,
    Category,
    Product,
    ProductImage,
    ProductVideo,
    ProductSpecification,
    ProductVariant,
    Review,
    SizeChart,
    Collection,
)
from cms.models import BlogPost, FAQItem, HeroSlide, HomepageSection, Page, PolicyDocument
from core.models import SiteSettings, Currency

from marketing.models import Coupon, FlashSale, NewsletterSubscriber

_DATE = forms.DateInput(attrs={"type": "date"})
_DATETIME = forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M")
_TIME = forms.TimeInput(attrs={"type": "time"})


class SlugAutoMixin(forms.ModelForm):
    """Auto-populate an empty ``slug`` from ``name``/``title`` on save."""

    def clean(self):
        cleaned = super().clean()
        if "slug" in self.fields and not cleaned.get("slug"):
            source = cleaned.get("name") or cleaned.get("title")
            if source:
                cleaned["slug"] = slugify(source)
        return cleaned


class ProductForm(SlugAutoMixin):
    class Meta:
        model = Product
        fields = [
            "name",
            "slug",
            "sku",
            "category",
            "brand",
            "size_chart",
            "base_price",
            "mrp",
            "purchase_price",

            "color",
            "stock_quantity",
            "low_stock_threshold",
            "is_active",
            "is_featured",
            "is_bestseller",
            "is_new_arrival",
            "collections",
            "tags",
            "labels",
            "care_instructions",
            "meta_title",
            "meta_description",
            "og_image",
            "weight",
            "length",
            "width",
            "height",
        ]
        widgets = {
            "base_price": forms.NumberInput(attrs={"min": "0"}),
            "mrp": forms.NumberInput(attrs={"min": "0"}),
            "purchase_price": forms.NumberInput(attrs={"min": "0"}),
            "stock_quantity": forms.NumberInput(attrs={"min": "0"}),
            "low_stock_threshold": forms.NumberInput(attrs={"min": "0"}),
        }
        error_messages = {
            "name": {"required": "Product name is required."},
            "sku": {"required": "SKU is required."},
            "category": {"required": "Category is required."},
            "base_price": {"required": "Base price is required.", "min_value": "Base price cannot be negative."},
            "mrp": {"required": "MRP is required.", "min_value": "MRP cannot be negative."},
            "purchase_price": {"required": "Purchase price is required.", "min_value": "Purchase price cannot be negative."},
            "stock_quantity": {"required": "Stock quantity is required.", "min_value": "Stock quantity cannot be negative."},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from django.db.models import Q
        qs = SizeChart.objects.filter(is_active=True)
        if self.instance and self.instance.pk and self.instance.size_chart_id:
            qs = SizeChart.objects.filter(Q(is_active=True) | Q(pk=self.instance.size_chart_id))
        self.fields["size_chart"].queryset = qs.order_by("name")
        self.fields["size_chart"].empty_label = "No Size Chart"
        
        qs_cat = Category.objects.filter(is_active=True)
        if self.instance and self.instance.pk and self.instance.category_id:
            qs_cat = Category.objects.filter(Q(is_active=True) | Q(pk=self.instance.category_id))
        self.fields["category"].queryset = qs_cat.order_by("name")
        self.fields["category"].empty_label = "Select Category"

        qs_col = Collection.objects.filter(is_active=True)
        if self.instance and self.instance.pk:
            qs_col = qs_col | self.instance.collections.all()
        self.fields["collections"].queryset = qs_col.distinct().order_by("name")
        
        self.fields["slug"].required = False
        self.fields["base_price"].required = False
        self.fields["mrp"].required = False
        self.fields["purchase_price"].required = False
        self.fields["stock_quantity"].required = False
        self.fields["low_stock_threshold"].required = False
        self.fields["collections"].required = False

        from core.services import get_site_settings
        site_settings = get_site_settings()
        if not site_settings.enable_brands and "brand" in self.fields:
            del self.fields["brand"]
        self.fields["tags"].required = False
        self.fields["labels"].required = False
        
        self.fields["collections"].widget.attrs["class"] = "form-select form-control"
        self.fields["tags"].widget.attrs["class"] = "form-select form-control"
        self.fields["labels"].widget.attrs["class"] = "form-select form-control"

    def clean_sku(self):
        sku = (self.cleaned_data.get("sku") or "").strip()
        pk = self.instance.pk if self.instance else None
        if Product.objects.filter(sku__iexact=sku).exclude(pk=pk).exists():
            raise forms.ValidationError("Product with this SKU already exists.")
        if ProductVariant.objects.filter(sku_suffix__iexact=sku).exclude(product_id=pk).exists():
            raise forms.ValidationError("This SKU is already in use by a variant.")
        return sku

    def clean(self):
        cleaned = super().clean()
        has_variants = self.data.get("has_variants") == "on"
        
        if not has_variants and cleaned.get("base_price") is None:
            self.add_error("base_price", "Base price is required for simple products.")
            
        for field in ["base_price", "mrp", "purchase_price", "stock_quantity", "low_stock_threshold"]:
            val = cleaned.get(field)
            if val is None:
                cleaned[field] = 0
            elif val < 0:
                self.add_error(field, f"{field.replace('_', ' ').capitalize()} cannot be negative.")
        return cleaned


class CategoryForm(SlugAutoMixin):
    class Meta:
        model = Category
        fields = [
            "name",
            "slug",
            "parent",
            "display_order",
            "is_active",
            "meta_title",
            "meta_description",
            "og_image",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["slug"].required = False


class CollectionForm(SlugAutoMixin):
    class Meta:
        model = Collection
        fields = [
            "name",
            "slug",
            "description",
            "image",
            "is_active",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["slug"].required = False


class BrandForm(SlugAutoMixin):
    class Meta:
        model = Brand
        fields = ["name", "slug", "logo", "is_featured"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["slug"].required = False


class SizeChartForm(forms.ModelForm):
    class Meta:
        model = SizeChart
        fields = ["name", "content_html", "image", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["content_html"].widget.attrs["class"] = "tinymce-editor"
        self.fields["content_html"].widget.attrs["style"] = "visibility: hidden; height: 300px;"


from delivery.models import City, Country

class CityForm(SlugAutoMixin):
    class Meta:
        model = City
        fields = [
            "country",
            "name",
            "slug",
            "delivery_charge_base",
            "estimated_delivery_text",
            # "same_day_cutoff_hour",
            "is_active",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["slug"].required = False


class ReviewForm(forms.ModelForm):
    class Meta:
        model = Review
        fields = ["moderation_status"]


class ProductVariantForm(forms.ModelForm):
    class Meta:
        model = ProductVariant
        fields = ["variant_type", "name", "base_price", "mrp", "purchase_price", "sku_suffix", "stock_quantity", "low_stock_threshold"]
        widgets = {
            "variant_type": forms.TextInput(attrs={
                "list": "variant-type-list",
                "class": "form-control",
                "placeholder": "e.g. Size, Packaging, Color"
            }),
            "base_price": forms.NumberInput(attrs={"min": "0"}),
            "mrp": forms.NumberInput(attrs={"min": "0"}),
            "purchase_price": forms.NumberInput(attrs={"min": "0"}),
            "stock_quantity": forms.NumberInput(attrs={"min": "0"}),
            "low_stock_threshold": forms.NumberInput(attrs={"min": "0"}),
        }
        error_messages = {
            "variant_type": {"required": "Variant type is required."},
            "name": {"required": "Name is required."},
            "base_price": {"required": "Base price is required.", "min_value": "Base price cannot be negative."},
            "mrp": {"required": "MRP is required.", "min_value": "MRP cannot be negative."},
            "purchase_price": {"required": "Purchase price is required.", "min_value": "Purchase price cannot be negative."},
            "stock_quantity": {"required": "Stock quantity is required.", "min_value": "Stock quantity cannot be negative."},
            "low_stock_threshold": {"required": "Low stock threshold is required.", "min_value": "Low stock threshold cannot be negative."},
        }

    def has_changed(self):
        """Ignore empty extra forms even if fields have model defaults (like stock_quantity=0)."""
        changed = super().has_changed()
        if changed:
            #if every field in the POST data is empty or default, it's an untouched extra form.
            has_real_data = False
            for name in self.fields:
                prefixed_name = self.add_prefix(name)
                val = self.data.get(prefixed_name)
                if val and val not in ["0", "5", "0.0", "0.00"]:  # ignore empty strings and default numeric strings
                    has_real_data = True
                    break
            return has_real_data
        return changed

ProductVariantFormSet = forms.inlineformset_factory(
    Product,
    ProductVariant,
    form=ProductVariantForm,
    extra=0,
    can_delete=True,
)

class HideExtraIfDataMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound and self.initial_form_count() > 0:
            self.extra = 0

class BaseProductMediaFormSet(HideExtraIfDataMixin, forms.BaseInlineFormSet):
    def _construct_form(self, i, **kwargs):
        form = super()._construct_form(i, **kwargs)
        choices = [("", "Select"), ("all", "--All Variants")]
        if self.instance and self.instance.pk:
            variants = ProductVariant.objects.filter(product=self.instance).order_by('name')
            for v in variants:
                display_name = v.sku_suffix if v.sku_suffix else v.name
                choices.append((v.sku_suffix, display_name))
        
        if 'variant_sku' in form.fields:
            form.fields['variant_sku'].widget.choices = choices
        return form

    @property
    def empty_form(self):
        form = super().empty_form
        choices = [("", "Select"), ("all", "--All Variants")]
        if self.instance and self.instance.pk:
            variants = ProductVariant.objects.filter(product=self.instance).order_by('name')
            for v in variants:
                display_name = v.sku_suffix if v.sku_suffix else v.name
                choices.append((v.sku_suffix, display_name))
        
        if 'variant_sku' in form.fields:
            form.fields['variant_sku'].widget.choices = choices
        return form

class ProductImageForm(forms.ModelForm):
    variant_sku = forms.CharField(
        required=False,
        widget=forms.Select(attrs={'class': 'form-select form-select-sm variant-dropdown', 'style': 'min-width: 130px; width: 100%;'})
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            if self.instance.variant:
                self.initial['variant_sku'] = self.instance.variant.sku_suffix
            else:
                self.initial['variant_sku'] = "all"
            
        self.fields["display_order"].required = False
        if self.empty_permitted:
            self.initial["display_order"] = None

    def clean_display_order(self):
        val = self.cleaned_data.get("display_order")
        return val if val is not None else 0

    class Meta:
        model = ProductImage
        fields = ["image", "alt_text", "display_order", "is_primary"]
        widgets = {
            'alt_text': forms.TextInput(attrs={'class': 'form-control form-control-sm', 'style': 'width: 100%; min-width: 80px;', 'placeholder': 'Alt text'}),
            'display_order': forms.NumberInput(attrs={'class': 'form-control form-control-sm text-center px-1', 'style': 'max-width: 60px; min-width: 60px; margin: 0 auto;'}),
        }
        error_messages = {
            "image": {"required": "Image file is required."},
            "alt_text": {"required": "Alt text is required."},
            "display_order": {"required": "Required."},
        }

ProductImageFormSet = forms.inlineformset_factory(
    Product,
    ProductImage,
    form=ProductImageForm,
    formset=BaseProductMediaFormSet,
    extra=1,
    can_delete=True,
)

class ProductVideoForm(forms.ModelForm):
    variant_sku = forms.CharField(
        required=False,
        widget=forms.Select(attrs={'class': 'form-select form-select-sm variant-dropdown', 'style': 'min-width: 130px; width: 100%;'})
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            if self.instance.variant:
                self.initial['variant_sku'] = self.instance.variant.sku_suffix
            else:
                self.initial['variant_sku'] = "all"

    class Meta:
        model = ProductVideo
        fields = ["video_file", "thumbnail"]
        error_messages = {
            "video_file": {"required": "Video file is required."},
        }

ProductVideoFormSet = forms.inlineformset_factory(
    Product,
    ProductVideo,
    form=ProductVideoForm,
    formset=BaseProductMediaFormSet,
    extra=1,
    can_delete=True,
)

class ProductSpecificationForm(forms.ModelForm):
    class Meta:
        model = ProductSpecification
        fields = ["name", "value", "display_order"]
        error_messages = {
            "name": {"required": "Specification name is required."},
            "value": {"required": "Value is required."},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["display_order"].required = False
        if not self.instance.pk:
            self.initial["display_order"] = None

    def clean_display_order(self):
        val = self.cleaned_data.get("display_order")
        return val if val is not None else 0


class BaseProductSpecificationFormSet(HideExtraIfDataMixin, forms.BaseInlineFormSet):
    pass

ProductSpecificationFormSet = forms.inlineformset_factory(
    Product,
    ProductSpecification,
    form=ProductSpecificationForm,
    formset=BaseProductSpecificationFormSet,
    extra=1,
    can_delete=True,
)


class CustomerProfileForm(forms.ModelForm):
    class Meta:
        model = CustomerProfile
        fields = [
            "phone",
            "phone_verified",
            "notify_via_email",
            "notify_via_sms",
            "notify_via_whatsapp",
        ]



class CouponForm(forms.ModelForm):
    class Meta:
        model = Coupon
        fields = [
            "code",
            "discount_type",
            "discount_value",
            "min_order_value",
            "max_uses",
            "max_uses_per_customer",
            "valid_from",
            "valid_until",
            "applicable_categories",
            "is_active",
        ]
        widgets = {"valid_from": _DATETIME, "valid_until": _DATETIME}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from django.utils import timezone
        now = timezone.localtime().strftime('%Y-%m-%dT%H:%M')
        self.fields["valid_from"].widget.attrs["min"] = now
        self.fields["valid_until"].widget.attrs["min"] = now

    def clean(self):
        cleaned_data = super().clean()
        valid_from = cleaned_data.get("valid_from")
        valid_until = cleaned_data.get("valid_until")

        if valid_from and valid_until and valid_from >= valid_until:
            self.add_error("valid_until", "Valid until date must be after valid from date.")

        return cleaned_data


class FlashSaleForm(forms.ModelForm):
    class Meta:
        model = FlashSale
        fields = ["name", "products", "discount_percentage", "starts_at", "ends_at", "is_active"]
        widgets = {"starts_at": _DATETIME, "ends_at": _DATETIME}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from django.utils import timezone
        now = timezone.localtime().strftime('%Y-%m-%dT%H:%M')
        self.fields["starts_at"].widget.attrs["min"] = now
        self.fields["ends_at"].widget.attrs["min"] = now

    def clean(self):
        cleaned_data = super().clean()
        starts_at = cleaned_data.get("starts_at")
        ends_at = cleaned_data.get("ends_at")

        if starts_at and ends_at and starts_at >= ends_at:
            self.add_error("ends_at", "End date must be after start date.")

        return cleaned_data


class NewsletterSubscriberForm(forms.ModelForm):
    class Meta:
        model = NewsletterSubscriber
        fields = ["email", "is_active"]


from cms.forms import HomepageSectionAdminForm


class HomepageSectionForm(HomepageSectionAdminForm):
    """Structured homepage section form with per-type config fields."""
    pass


class HeroSlideForm(forms.ModelForm):
    class Meta:
        model = HeroSlide
        fields = ["title", "image", "video", "poster", "display_order", "is_active"]

    def clean_image(self):
        image = self.cleaned_data.get("image")
        if image:
            from django.core.files.images import get_image_dimensions
            width, height = get_image_dimensions(image)
            
            # Enforce approximately 2:1 aspect ratio, allowing a small tolerance limit
            aspect_ratio = width / height
            if not (1.95 <= aspect_ratio <= 2.05):
                raise forms.ValidationError(
                    f"Banner image must have approximately a 2:1 aspect ratio. "
                    f"Uploaded image is {width}x{height}."
                )
            
            #enforce a minimum resolution for quality
            if width < 1000:
                raise forms.ValidationError(
                    f"Banner image must be at least 1000px wide for good quality. Uploaded image is {width}px wide."
                )
                
        return image

    def clean_poster(self):
        poster = self.cleaned_data.get("poster")
        if poster:
            from django.core.files.images import get_image_dimensions
            width, height = get_image_dimensions(poster)
            
            if width != height * 2:
                raise forms.ValidationError(
                    f"Poster image must have exactly a 2:1 aspect ratio. Uploaded image is {width}x{height}."
                )
            
            if width < 1200:
                raise forms.ValidationError(
                    f"Poster image must be at least 1200px wide. Uploaded image is {width}px wide."
                )
                
        return poster


class BlogPostForm(SlugAutoMixin):
    class Meta:
        model = BlogPost
        fields = [
            "title",
            "slug",
            "excerpt",
            "body",
            "is_published",
            "publish_at",
            "meta_title",
            "meta_description",
            "og_image",
        ]
        widgets = {"publish_at": _DATETIME}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["slug"].required = False
        if "og_image" in self.fields:
            self.fields["og_image"].label = "Featured / Cover Image"
            self.fields["og_image"].help_text = (
                "Displayed as the blog cover image on the storefront and used as preview when shared on social media."
            )


class PageForm(SlugAutoMixin):
    class Meta:
        model = Page
        fields = [
            "title",
            "slug",
            "body",
            "is_published",
            "publish_at",
            "meta_title",
            "meta_description",
            "og_image",
        ]
        widgets = {"publish_at": _DATETIME}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["slug"].required = False
        if "og_image" in self.fields:
            self.fields["og_image"].label = "Open Graph Image (Social Share)"
            self.fields["og_image"].help_text = (
                "Image used when this content is shared on social media."
            )


class FAQItemForm(forms.ModelForm):
    class Meta:
        model = FAQItem
        fields = ["question", "answer", "display_order", "is_published", "publish_at"]
        widgets = {"publish_at": _DATETIME}


class PolicyDocumentForm(SlugAutoMixin):
    class Meta:
        model = PolicyDocument
        fields = [
            "title",
            "slug",
            "policy_type",
            "body",
            "is_published",
            "publish_at",
            "meta_title",
            "meta_description",
            "og_image",
        ]
        widgets = {"publish_at": _DATETIME}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["slug"].required = False








class SiteSettingsForm(forms.ModelForm):
    default_currency = forms.ModelChoiceField(
        queryset=Currency.objects.exclude(code__in=["AED", "INR", "USD"]),
        required=False,
        empty_label="--- Select Default Currency ---",
        help_text="Select the store's default currency."
    )

    field_order = [
        "site_name",
        "logo",
        "primary_color",
        "secondary_color",
        "font_family",
        "facebook_url",
        "instagram_url",
        "twitter_url",
        "whatsapp_number",
        "default_currency",
        "vendor_email",
        "order_notification_email",
        "notify_new_order",
        "notify_low_stock",
        "notify_enquiry",
        "tax_rate_percent",
        "cod_delivery_charge",
        "default_shipping_charge",
        "free_shipping_threshold",
        "default_estimated_delivery_text",
        "google_analytics_id",
        "meta_pixel_id",
        "razorpay_key_id",
        "razorpay_key_secret",
        "cybersource_merchant_id",
        "cybersource_key_id",
        "cybersource_secret_key",
        "cybersource_run_environment",
        "afterpay_merchant_id",
        "afterpay_secret_key",
        "afterpay_environment",
        "stripe_publishable_key",
        "stripe_secret_key",
        "stripe_webhook_secret",
    ]

    class Meta:
        model = SiteSettings
        fields = [
            "site_name",
            "logo",
            "primary_color",
            "secondary_color",
            "font_family",
            "facebook_url",
            "instagram_url",
            "twitter_url",
            "whatsapp_number",
            "vendor_email",
            "order_notification_email",
            "notify_new_order",
            "notify_low_stock",
            "notify_enquiry",
            "tax_rate_percent",
            "cod_delivery_charge",
            "default_shipping_charge",
            "free_shipping_threshold",
            "default_estimated_delivery_text",
            "google_analytics_id",
            "meta_pixel_id",
            "razorpay_key_id",
            "razorpay_key_secret",
            "cybersource_merchant_id",
            "cybersource_key_id",
            "cybersource_secret_key",
            "cybersource_run_environment",
            "afterpay_merchant_id",
            "afterpay_secret_key",
            "afterpay_environment",
            "stripe_publishable_key",
            "stripe_secret_key",
            "stripe_webhook_secret",
        ]
        widgets = {
            "cybersource_secret_key": forms.PasswordInput(render_value=True),
            "afterpay_secret_key": forms.PasswordInput(render_value=True),
            # Stripe secrets are never echoed back into the page; blank on save keeps the stored value.
            "stripe_secret_key": forms.PasswordInput(render_value=False),
            "stripe_webhook_secret": forms.PasswordInput(render_value=False),
        }
        labels = {
            "vendor_email": "Email",
            "order_notification_email": "Notification Email",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "default_currency" in self.fields:
            self.fields["default_currency"].queryset = Currency.objects.exclude(
                code__in=["AED", "INR", "USD"]
            )
        default_curr = Currency.objects.filter(is_default=True).first()
        if default_curr and default_curr.code not in ["AED", "INR", "USD"]:
            if "default_currency" in self.fields:
                self.fields["default_currency"].initial = default_curr.pk
        if self.instance and not getattr(self.instance, "enable_cod", True):
            self.fields.pop("cod_delivery_charge", None)
        if self.instance and not getattr(self.instance, "enable_razorpay", True):
            self.fields.pop("razorpay_key_id", None)
            self.fields.pop("razorpay_key_secret", None)
        if self.instance and not getattr(self.instance, "enable_cybersource", True):
            self.fields.pop("cybersource_merchant_id", None)
            self.fields.pop("cybersource_key_id", None)
            self.fields.pop("cybersource_secret_key", None)
            self.fields.pop("cybersource_run_environment", None)
        if self.instance and not getattr(self.instance, "enable_afterpay", True):
            self.fields.pop("afterpay_merchant_id", None)
            self.fields.pop("afterpay_secret_key", None)
            self.fields.pop("afterpay_environment", None)
        if self.instance and not getattr(self.instance, "enable_stripe", True):
            self.fields.pop("stripe_publishable_key", None)
            self.fields.pop("stripe_secret_key", None)
            self.fields.pop("stripe_webhook_secret", None)
        for name in self.STRIPE_SECRET_FIELDS:
            if name in self.fields and getattr(self.instance, name, ""):
                self.fields[name].widget.attrs["placeholder"] = "Saved - leave blank to keep the current value"
                self.fields[name].help_text = "A value is saved. Leave blank to keep it, or enter a new one to replace it."
        for field_name, field in self.fields.items():
            if field_name != "logo":
                if isinstance(field.widget, forms.CheckboxInput):
                    field.widget.attrs["class"] = "form-check-input"
                else:
                    if "class" in field.widget.attrs:
                        field.widget.attrs["class"] += " form-control"
                    else:
                        field.widget.attrs["class"] = "form-control"

    STRIPE_SECRET_FIELDS = ("stripe_secret_key", "stripe_webhook_secret")

    def _keep_stored_secret(self, name: str) -> str:
        value = (self.cleaned_data.get(name) or "").strip()
        return value or getattr(self.instance, name, "")

    def clean_stripe_secret_key(self):
        return self._keep_stored_secret("stripe_secret_key")

    def clean_stripe_webhook_secret(self):
        return self._keep_stored_secret("stripe_webhook_secret")

    def clean(self):
        cleaned = super().clean()
        if "stripe_publishable_key" not in self.fields:
            return cleaned

        # Stripe is only usable with all three credentials, in one consistent mode.
        from payments.adapters.stripe import validate_stripe_keys

        keys = {
            "stripe_publishable_key": (cleaned.get("stripe_publishable_key") or "").strip(),
            "stripe_secret_key": (cleaned.get("stripe_secret_key") or "").strip(),
            "stripe_webhook_secret": (cleaned.get("stripe_webhook_secret") or "").strip(),
        }
        if any(keys.values()):
            problems = validate_stripe_keys(
                publishable_key=keys["stripe_publishable_key"],
                secret_key=keys["stripe_secret_key"],
                webhook_secret=keys["stripe_webhook_secret"],
            )
            for problem in problems:
                self.add_error(None, f"Stripe: {problem}")
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit)
        new_default = self.cleaned_data.get("default_currency")
        if new_default:
            Currency.objects.update(is_default=False)
            new_default.is_default = True
            new_default.save()
            from core.selectors import invalidate_default_currency_cache
            invalidate_default_currency_cache()
        return instance


class OrderStatusForm(forms.Form):
    """Free-standing form for applying an order status transition."""

    new_status = forms.ChoiceField(choices=[])
    note = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, allowed_choices=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["new_status"].choices = allowed_choices or []
