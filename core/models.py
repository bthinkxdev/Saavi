"""Abstract base model mixins and shared core domain models for sarocchi."""

from __future__ import annotations

from typing import Any

from django.db import models
from django.utils import timezone
from django.core.cache import cache


class TimeStampedModel(models.Model):
    """Abstract mixin adding indexed created_at / updated_at audit columns."""

    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        verbose_name="Created at",
        help_text="Timestamp when this record was first created.",
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        db_index=True,
        verbose_name="Updated at",
        help_text="Timestamp when this record was last modified.",
    )

    class Meta:
        abstract = True


class SoftDeleteQuerySet(models.QuerySet):
    """QuerySet that performs soft deletes by flagging rows instead of removing them."""

    def delete(self) -> tuple[int, dict[str, int]]:
        """Soft-delete all rows in this queryset."""
        count = self.update(is_deleted=True, deleted_at=timezone.now())
        return count, {self.model._meta.label: count}

    def hard_delete(self) -> tuple[int, dict[str, int]]:
        """Permanently remove rows from the database."""
        return super().delete()


class SoftDeleteManager(models.Manager):
    """Manager excluding soft-deleted rows; exposes all_with_deleted()."""

    def get_queryset(self) -> SoftDeleteQuerySet:
        """Return only active (non-deleted) rows."""
        return SoftDeleteQuerySet(self.model, using=self._db).filter(is_deleted=False)

    def all_with_deleted(self) -> SoftDeleteQuerySet:
        """Return all rows including soft-deleted ones."""
        return SoftDeleteQuerySet(self.model, using=self._db)


class SoftDeleteModel(models.Model):
    """Abstract mixin adding soft-delete flags and a filtering manager."""

    is_deleted = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name="Is deleted",
        help_text="When True, this record is hidden from default queries.",
    )
    deleted_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        verbose_name="Deleted at",
        help_text="Timestamp when this record was soft-deleted.",
    )

    objects = SoftDeleteManager()

    class Meta:
        abstract = True

    def delete(
        self,
        using: str | None = None,
        keep_parents: bool = False,
    ) -> tuple[int, dict[str, int]]:
        """Soft-delete this instance."""
        self.is_deleted = True
        self.deleted_at = timezone.now()
        update_fields = ["is_deleted", "deleted_at"]
        if any(field.name == "updated_at" for field in self._meta.fields):
            update_fields.append("updated_at")
        self.save(update_fields=update_fields)
        return 1, {self._meta.label: 1}

    def hard_delete(
        self,
        using: str | None = None,
        keep_parents: bool = False,
    ) -> tuple[int, dict[str, int]]:
        """Permanently remove this instance from the database."""
        return super().delete(using=using, keep_parents=keep_parents)


class SEOModel(models.Model):
    """Abstract mixin for SEO metadata and a reusable slug field factory."""

    meta_title = models.CharField(
        max_length=70,
        blank=True,
        verbose_name="Meta title",
        help_text="HTML <title> tag content (max ~70 characters).",
    )
    meta_description = models.CharField(
        max_length=160,
        blank=True,
        verbose_name="Meta description",
        help_text="HTML meta description for search engines (max ~160 characters).",
    )
    og_image = models.ImageField(
        upload_to="seo/og/",
        blank=True,
        null=True,
        verbose_name="Open Graph image",
        help_text="Image used when this content is shared on social media.",
    )

    class Meta:
        abstract = True

    @staticmethod
    def slug_field(**kwargs: Any) -> models.SlugField:
        """
        Return a pre-configured SlugField for SEO-friendly URLs.

        Pass extra kwargs to override defaults (e.g. unique=False for drafts).
        """
        defaults: dict[str, Any] = {
            "max_length": 255,
            "unique": True,
            "db_index": True,
            "verbose_name": "Slug",
            "help_text": "URL-friendly identifier used in public-facing paths.",
        }
        defaults.update(kwargs)
        return models.SlugField(**defaults)


class State(TimeStampedModel):
    """Stores a list of states/provinces for checkout dropdown."""
    
    name = models.CharField(max_length=255, unique=True, verbose_name="State Name")
    is_active = models.BooleanField(default=True, help_text="Is this state active for delivery?")

    class Meta:
        verbose_name = "State"
        verbose_name_plural = "States"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

class Currency(TimeStampedModel):
    """Supported storefront currency with exchange rate relative to the base unit."""

    code = models.CharField(
        max_length=3,
        unique=True,
        db_index=True,
        verbose_name="Currency code",
        help_text="ISO 4217 currency code, e.g. QAR or USD.",
    )
    symbol = models.CharField(
        max_length=8,
        verbose_name="Symbol",
        help_text="Display symbol shown alongside prices, e.g. ر.ق or $.",
    )
    exchange_rate_to_base = models.DecimalField(
        max_digits=18,
        decimal_places=8,
        verbose_name="Exchange rate to base",
        help_text="Multiplier to convert this currency into the platform base currency.",
    )
    is_default = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name="Is default",
        help_text="When True, this currency is the storefront default.",
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        verbose_name="Is active",
        help_text="When False, this currency is hidden/inactive on the storefront.",
    )

    class Meta:
        verbose_name = "Currency"
        verbose_name_plural = "Currencies"
        indexes = [
            models.Index(fields=["is_default"], name="core_currency_is_default_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.code} ({self.symbol})"


class SiteSettings(TimeStampedModel):
    """
    Singleton site configuration (fixed pk=1 via core.services.get_site_settings).

    Secret payment keys stay in environment variables — only public key names
    and template slugs are stored here.
    """

    site_name = models.CharField(max_length=120, default="Sarocchi Luxe Designs")
    logo = models.ImageField(upload_to="site/", blank=True, null=True, verbose_name="Logo")
    primary_color = models.CharField(max_length=7, default="#1B4D3E")
    secondary_color = models.CharField(max_length=7, default="#C5A059")
    font_family = models.CharField(max_length=120, default="Inter, sans-serif")
    enable_brands = models.BooleanField(
        default=True,
        verbose_name="Enable Brands",
        help_text="Enable or disable Brand features across the entire site."
    )
    enable_delhivery = models.BooleanField(
        default=False,
        verbose_name="Enable Delhivery",
        help_text="Enable or disable Delhivery shipping integration across the site."
    )
    enable_newsletter = models.BooleanField(
        default=True,
        verbose_name="Enable Newsletter",
        help_text="Enable or disable Newsletter subscription features and display on home page and sidebar."
    )
    enable_pages = models.BooleanField(
        default=True,
        verbose_name="Enable Pages",
        help_text="Enable or disable custom Pages feature and display in footer and sidebar."
    )
    facebook_url = models.URLField(blank=True)
    instagram_url = models.URLField(blank=True)
    twitter_url = models.URLField(blank=True)
    whatsapp_number = models.CharField(max_length=20, blank=True)
    google_analytics_id = models.CharField(
        max_length=50, 
        blank=True,
        verbose_name="Google Analytics ID",
        help_text="GA4 Measurement ID (e.g. G-XXXXXXXXXX)"
    )
    meta_pixel_id = models.CharField(
        max_length=50, 
        blank=True,
        verbose_name="Meta Pixel ID",
        help_text="Meta Pixel ID (e.g. 1234567890)"
    )
    vendor_email = models.EmailField(
        blank=True,
        verbose_name="Vendor Email",
        help_text="Email address to receive quote requests and contact inquiries.",
    )
    order_notification_email = models.EmailField(
        blank=True,
        verbose_name="Notification Email",
        help_text="Email address to receive system notifications. Leave blank to disable all.",
    )
    notify_new_order = models.BooleanField(
        default=True,
        verbose_name="New Order Notification",
        help_text="Enable to receive notifications for new orders.",
    )
    notify_low_stock = models.BooleanField(
        default=True,
        verbose_name="Low Stock Notification",
        help_text="Enable to receive notifications for low stock alerts.",
    )
    notify_enquiry = models.BooleanField(
        default=True,
        verbose_name="Enquiry Notification",
        help_text="Enable to receive notifications for contact inquiries.",
    )
    default_currency = models.ForeignKey(
        Currency,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    default_language = models.CharField(max_length=5, default="en")
    tax_rate_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    enable_cod = models.BooleanField(
        default=True,
        verbose_name="Enable Cash on Delivery (COD)",
        help_text="Enable or disable Cash on Delivery payment option at checkout.",
    )
    cod_delivery_charge = models.DecimalField(max_digits=10, decimal_places=2, default=50, verbose_name="COD Delivery Charge")
    
    #generic shipping configuration
    default_estimated_delivery_text = models.CharField(
        max_length=255, 
        blank=True,
        default="Dispatch in 24 hours. Delivery in 2-5 Business Days.",
        verbose_name="Default Estimated Delivery",
        help_text="Shown on PDP and as fallback if city has no override."
    )
    default_shipping_charge = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        default=0.00,
        verbose_name="Default Shipping Charge",
        help_text="Fallback flat shipping rate."
    )
    free_shipping_threshold = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        verbose_name="Free Shipping Threshold",
        help_text="Orders over this amount get free shipping (leave blank for no free shipping)."
    )
    
    card_gateway_public_key_env = models.CharField(
        max_length=80,
        default="CARD_GATEWAY_PUBLIC_KEY",
        help_text="Environment variable name for the card gateway public key.",
    )
    qatar_gateway_public_key_env = models.CharField(
        max_length=80,
        default="QATAR_GATEWAY_PUBLIC_KEY",
        blank=True,
    )
    order_email_template_slug = models.CharField(max_length=80, default="order-status")
    whatsapp_template_slug = models.CharField(max_length=80, default="order-whatsapp")
    enable_razorpay = models.BooleanField(
        default=True,
        verbose_name="Enable Razorpay",
        help_text="Enable or disable Razorpay online payment option at checkout.",
    )
    razorpay_key_id = models.CharField(
        max_length=120,
        blank=True,
        verbose_name="Razorpay Key ID",
        help_text="Razorpay Key ID / Test Key ID for payment processing.",
    )
    razorpay_key_secret = models.CharField(
        max_length=120,
        blank=True,
        verbose_name="Razorpay Key Secret",
        help_text="Razorpay Key Secret / Test Key Secret for payment signature verification.",
    )
    enable_cybersource = models.BooleanField(
        default=True,
        verbose_name="Enable CyberSource",
        help_text="Enable or disable CyberSource payment option at checkout.",
    )
    cybersource_merchant_id = models.CharField(
        max_length=120,
        blank=True,
        verbose_name="CyberSource Merchant ID",
        help_text="CyberSource Merchant ID.",
    )
    cybersource_key_id = models.CharField(
        max_length=120,
        blank=True,
        verbose_name="CyberSource Key ID",
        help_text="CyberSource REST API Key ID.",
    )
    cybersource_secret_key = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="CyberSource Secret Key",
        help_text="CyberSource Shared Secret Key.",
    )
    cybersource_run_environment = models.CharField(
        max_length=50,
        default="apitest.cybersource.com",
        choices=[
            ("apitest.cybersource.com", "Test"),
            ("api.cybersource.com", "Live"),
        ],
        verbose_name="CyberSource Environment",
        help_text="Run environment for CyberSource API requests.",
    )
    enable_afterpay = models.BooleanField(
        default=True,
        verbose_name="Enable Afterpay",
        help_text="Enable or disable Afterpay payment option at checkout.",
    )
    afterpay_merchant_id = models.CharField(
        max_length=120,
        blank=True,
        verbose_name="Afterpay Merchant ID",
        help_text="Afterpay Merchant ID.",
    )
    afterpay_secret_key = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="Afterpay Secret Key",
        help_text="Afterpay Secret Key.",
    )
    afterpay_environment = models.CharField(
        max_length=50,
        default="global-api-sandbox.afterpay.com",
        choices=[
            ("global-api-sandbox.afterpay.com", "Test"),
            ("global-api.afterpay.com", "Live"),
        ],
        verbose_name="Afterpay Environment",
        help_text="Run environment for Afterpay API requests.",
    )
    enable_stripe = models.BooleanField(
        default=True,
        verbose_name="Enable Stripe",
        help_text="Enable or disable Stripe payment option at checkout.",
    )
    stripe_publishable_key = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="Stripe Publishable Key",
        help_text="Stripe Publishable API Key (pk_test_... or pk_live_...).",
    )
    stripe_secret_key = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="Stripe Secret Key",
        help_text="Stripe Secret API Key (sk_test_... or sk_live_...).",
    )
    stripe_webhook_secret = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="Stripe Webhook Secret",
        help_text="Stripe Webhook Signing Secret (whsec_...).",
    )

    class Meta:
        verbose_name = "Site settings"
        verbose_name_plural = "Site settings"

    def __str__(self) -> str:
        return self.site_name

    def save(self, *args, **kwargs) -> None:
        self.pk = 1
        super().save(*args, **kwargs)
        cache.delete("site_settings_singleton")
        cache.delete("cms:homepage_sections:active:v1")

    def delete(self, *args, **kwargs) -> tuple[int, dict[str, int]]:
        raise RuntimeError("SiteSettings singleton cannot be deleted.")


class ContactInquiry(TimeStampedModel):
    """Stores contact form submissions and quote requests."""

    name = models.CharField(max_length=255, verbose_name="Name")
    email = models.EmailField(verbose_name="Email Address")
    message = models.TextField(verbose_name="Message")
    reply_subject = models.CharField(max_length=255, blank=True, null=True, verbose_name="Reply Subject")
    reply_message = models.TextField(blank=True, null=True, verbose_name="Reply Message")
    replied_at = models.DateTimeField(blank=True, null=True, verbose_name="Replied At")
    
    class Meta:
        verbose_name = "Contact Inquiry"
        verbose_name_plural = "Contact Inquiries"

    def __str__(self) -> str:
        return f"Inquiry from {self.name} ({self.email})"

    @property
    def is_replied(self) -> bool:
        """Returns True if this inquiry has been replied to."""
        return bool(self.replied_at)
