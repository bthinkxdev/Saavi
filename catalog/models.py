"""Data layer for the catalog app — models only, no business logic."""

from __future__ import annotations

import json
from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from core.models import TimeStampedModel


class Category(TimeStampedModel):
    """Hierarchical product category tree."""

    name = models.CharField(
        max_length=120,
        verbose_name="Name",
        help_text="Display name of the category.",
    )
    slug = models.SlugField(
        max_length=120,
        unique=True,
        db_index=True,
        verbose_name="Slug",
        help_text="URL-friendly category identifier.",
    )
    meta_title = models.CharField(max_length=70, blank=True, verbose_name="Meta title")
    meta_description = models.CharField(max_length=160, blank=True, verbose_name="Meta description")
    og_image = models.ImageField(
        upload_to="seo/categories/",
        blank=True,
        null=True,
        verbose_name="Open Graph image",
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="children",
        verbose_name="Parent category",
        help_text="Parent node in the category tree; null for top-level.",
    )
    display_order = models.PositiveIntegerField(
        default=0,
        verbose_name="Display order",
        help_text="Lower values appear first in navigation.",
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        verbose_name="Is active",
        help_text="When False, category is hidden from the storefront.",
    )

    class Meta:
        verbose_name = "Category"
        verbose_name_plural = "Categories"
        ordering = ["display_order", "name"]
        indexes = [
            models.Index(fields=["is_active"], name="cat_category_is_active_idx"),
        ]

    def __str__(self) -> str:
        return self.name



class Brand(TimeStampedModel):
    """Product brand for filtering and brand pages."""

    name = models.CharField(max_length=120, verbose_name="Name")
    slug = models.SlugField(
        max_length=120,
        unique=True,
        db_index=True,
        verbose_name="Slug",
    )
    logo = models.ImageField(
        upload_to="brands/logos/",
        blank=True,
        verbose_name="Logo",
    )
    is_featured = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name="Is featured",
        help_text="Featured brands appear on the homepage.",
    )

    class Meta:
        verbose_name = "Brand"
        verbose_name_plural = "Brands"
        indexes = [
            models.Index(fields=["is_featured"], name="cat_brand_is_featured_idx"),
        ]

    def __str__(self) -> str:
        return self.name



class SizeChart(TimeStampedModel):
    """Reusable size chart that can be assigned to multiple products."""

    name = models.CharField(
        max_length=120,
        verbose_name="Name",
        help_text="Internal name to identify the size chart (e.g., 'Men T-Shirts').",
    )
    content_html = models.TextField(
        blank=True,
        verbose_name="Content",
        help_text="Use the table tool to create your size chart grid.",
    )
    image = models.ImageField(
        upload_to="size_charts/",
        blank=True,
        null=True,
        verbose_name="Fallback Image",
        help_text="Optional fallback image. Used if no rich text content is provided.",
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        verbose_name="Is active",
        help_text="When False, size chart is hidden from the product selection dropdown.",
    )

    class Meta:
        verbose_name = "Size Chart"
        verbose_name_plural = "Size Charts"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.name

class ProductTag(TimeStampedModel):
    """Descriptive tag for a product (e.g., 'summer', 'cotton')."""

    name = models.CharField(max_length=50, unique=True, verbose_name="Name")
    slug = models.SlugField(max_length=50, unique=True, db_index=True, verbose_name="Slug")

    class Meta:
        verbose_name = "Product Tag"
        verbose_name_plural = "Product Tags"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class ProductLabel(TimeStampedModel):
    """Visual badge for product cards (e.g., 'Sale', 'New', 'Selling Fast')."""

    name = models.CharField(max_length=50, unique=True, verbose_name="Name")
    color = models.CharField(
        max_length=20, 
        default="#000000", 
        verbose_name="Color",
        help_text="Hex color code (e.g., #FF0000 for red) or valid CSS color."
    )

    class Meta:
        verbose_name = "Product Label"
        verbose_name_plural = "Product Labels"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Collection(TimeStampedModel):
    """Thematic grouping of products (e.g., 'Bridal Collection', 'Summer Sale')."""

    name = models.CharField(max_length=120, verbose_name="Name")
    slug = models.SlugField(max_length=120, unique=True, db_index=True, verbose_name="Slug")
    description = models.TextField(blank=True, verbose_name="Description")
    image = models.ImageField(upload_to="collections/", blank=True, verbose_name="Image")
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        verbose_name="Is active",
        help_text="When False, collection is hidden from the storefront.",
    )

    class Meta:
        verbose_name = "Collection"
        verbose_name_plural = "Collections"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Product(TimeStampedModel):
    """Core sellable product — highest read volume entity in the platform."""

    name = models.CharField(max_length=255, verbose_name="Name")
    slug = models.SlugField(
        max_length=255,
        unique=True,
        db_index=True,
        verbose_name="Slug",
    )
    sku = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        verbose_name="SKU",
        help_text="Stock keeping unit identifier.",
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name="products",
        verbose_name="Category",
    )
    brand = models.ForeignKey(
        Brand,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="products",
        verbose_name="Brand",
    )
    size_chart = models.ForeignKey(
        SizeChart,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="products",
        verbose_name="Size Chart",
    )
    tags = models.ManyToManyField(
        ProductTag,
        blank=True,
        related_name="products",
        verbose_name="Tags",
    )
    labels = models.ManyToManyField(
        ProductLabel,
        blank=True,
        related_name="products",
        verbose_name="Labels",
    )
    collections = models.ManyToManyField(
        Collection,
        blank=True,
        related_name="products",
        verbose_name="Collections",
    )
    attribute_values = models.ManyToManyField(
        "ProductAttributeValue",
        blank=True,
        related_name="products",
        verbose_name="Attribute values",
    )
    base_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        verbose_name="Base price",
        help_text="Default price before variant deltas.",
    )
    mrp = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="MRP")
    purchase_price = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Purchase Price")
    is_rental = models.BooleanField(default=False, db_index=True, verbose_name="Is Rental Eligible")
    rental_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name="Rental Price")
    show_rental_storefront = models.BooleanField(default=True, db_index=True, verbose_name="Show Rental in Storefront")
    color = models.CharField(
        max_length=50,
        blank=True,
        db_index=True,
        verbose_name="Color",
        help_text="Primary color for PLP color-filter chips.",
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        verbose_name="Is active",
    )
    is_featured = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name="Is featured",
    )
    is_bestseller = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name="Is bestseller",
    )
    is_new_arrival = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name="Is new arrival",
    )

    stock_quantity = models.PositiveIntegerField(
        default=0,
        verbose_name="Stock quantity",
    )
    care_instructions = models.TextField(
        blank=True,
        verbose_name="Care instructions",
        help_text="Product-specific care instructions.",
    )
    meta_title = models.CharField(max_length=70, blank=True, verbose_name="Meta title")
    meta_description = models.CharField(max_length=160, blank=True, verbose_name="Meta description")
    og_image = models.ImageField(
        upload_to="seo/products/",
        blank=True,
        null=True,
        verbose_name="Open Graph image",
    )
    low_stock_threshold = models.PositiveIntegerField(
        default=5,
        verbose_name="Low stock threshold",
        help_text="Triggers low-stock alerts when stock falls at or below this value.",
    )

    #shipping dimensions
    weight = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True, verbose_name="Weight (kg)", help_text="Weight in kilograms, used for courier booking.")
    length = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True, verbose_name="Length (cm)", help_text="Length in centimeters.")
    width = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True, verbose_name="Width (cm)", help_text="Width (breadth) in centimeters.")
    height = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True, verbose_name="Height (cm)", help_text="Height in centimeters.")

    class Meta:
        verbose_name = "Product"
        verbose_name_plural = "Products"
        indexes = [
            models.Index(
                fields=["is_active", "category_id"],
                name="cat_prod_active_category_idx",
            ),
            models.Index(
                fields=["is_active", "is_bestseller"],
                name="cat_prod_active_bestseller_idx",
            ),
            models.Index(fields=["is_active", "is_new_arrival"], name="cat_prod_active_new_idx"),
            models.Index(
                fields=["is_active", "is_featured"], name="cat_prod_featured_idx"
            ),
        ]

    def __str__(self) -> str:
        return self.name

    def get_absolute_url(self) -> str:
        from django.urls import reverse

        return reverse("catalog:pdp", kwargs={"slug": self.slug})

    @property
    def is_in_stock(self) -> bool:
        """True when aggregate product stock is available."""
        return self.stock_quantity > 0

    @property
    def price(self):
        return self.base_price

    @price.setter
    def price(self, value):
        self.base_price = value

    @property
    def display_variant(self):
        """
        Return the first in-stock variant for display on product cards (PLP/Home) and initial PDP loading.
        If all variants are out of stock, fallback to the first variant.
        """
        variants = self.variant_list if hasattr(self, "variant_list") else list(self.variants.all())
        if not variants:
            return None
        for v in variants:
            if v.stock_quantity > 0:
                return v
        return variants[0]

    @property
    def effective_base_price(self):
        v = self.display_variant
        return v.base_price if (v and v.base_price is not None and v.base_price > 0) else self.base_price

    @property
    def effective_mrp(self):
        v = self.display_variant
        return v.mrp if (v and v.mrp is not None and v.mrp > 0) else self.mrp

    @property
    def quick_view_variants_json(self):
        variants = self.variant_list if hasattr(self, "variant_list") else list(self.variants.all())
        if not variants:
            return ""

        variant_image_map = {}
        images = getattr(self, "primary_images", None)
        if images is None and hasattr(self, "images"):
            images = list(self.images.all())
        if images:
            for img in images:
                if getattr(img, "variant_id", None) and img.variant_id not in variant_image_map and getattr(img, "image", None):
                    try:
                        variant_image_map[img.variant_id] = img.image.url
                    except Exception:
                        pass

        data = []
        for v in variants:
            eff_price = v.base_price if (v.base_price is not None and v.base_price > 0) else self.effective_base_price
            eff_mrp = v.mrp if (v.mrp is not None and v.mrp > 0) else self.effective_mrp
            discount = 0
            if eff_mrp and eff_mrp > eff_price:
                discount = int(((eff_mrp - eff_price) / eff_mrp) * 100)
            data.append({
                "id": str(v.pk),
                "name": v.display_name,
                "stock": v.stock_quantity,
                "thresh": getattr(v, "low_stock_threshold", self.low_stock_threshold),
                "price": str(eff_price),
                "mrp": str(eff_mrp) if (eff_mrp and eff_mrp > eff_price) else "",
                "discount": discount,
                "image": variant_image_map.get(v.pk, ""),
            })
        return json.dumps(data)

    @property
    def primary_images(self):
        if hasattr(self, "_prefetched_primary_images"):
            return self._prefetched_primary_images
        return list(self.images.order_by("-is_primary", "display_order"))

    @primary_images.setter
    def primary_images(self, value):
        self._prefetched_primary_images = value


class ProductAttribute(TimeStampedModel):
    """Global product attribute definition (e.g., Color, Size)."""
    name = models.CharField(max_length=120, unique=True, verbose_name="Name")

    class Meta:
        verbose_name = "Product attribute"
        verbose_name_plural = "Product attributes"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class ProductAttributeValue(TimeStampedModel):
    """Specific value for a product attribute (e.g., Red, XL)."""
    attribute = models.ForeignKey(
        ProductAttribute,
        on_delete=models.CASCADE,
        related_name="values",
        verbose_name="Attribute",
    )
    value = models.CharField(max_length=120, verbose_name="Value")
    display_order = models.PositiveIntegerField(
        default=0,
        verbose_name="Display order",
        help_text="Lower values appear first.",
    )

    class Meta:
        verbose_name = "Product attribute value"
        verbose_name_plural = "Product attribute values"
        ordering = ["attribute__name", "display_order", "value"]
        unique_together = [("attribute", "value")]

    def __str__(self) -> str:
        return f"{self.attribute.name}: {self.value}"


class VariantType(models.TextChoices):
    """Allowed product variant dimensions."""

    SIZE = "size", "Size"
    PACKAGING = "packaging", "Packaging"


class ProductVariant(TimeStampedModel):
    """Purchasable variant altering price and/or stock."""

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="variants",
        verbose_name="Product",
    )
    variant_type = models.CharField(
        max_length=50,
        blank=True,
        verbose_name="Variant type",
    )
    name = models.CharField(max_length=120, blank=True, verbose_name="Variant Name")
    attribute_values = models.ManyToManyField(
        ProductAttributeValue,
        blank=True,
        related_name="variants",
        verbose_name="Attribute values",
    )
    display_order = models.PositiveIntegerField(
        default=0,
        verbose_name="Display order",
    )
    
    @property
    def display_name(self):
        """Returns just the variant-specific part of the name (e.g. 'Red - S' or custom name)"""
        if self.name:
            prefix = f"{self.product.name} - "
            cleaned_name = self.name[len(prefix):] if self.name.startswith(prefix) else self.name
            if cleaned_name and cleaned_name != self.sku_suffix:
                return cleaned_name
                
        attr_vals = [av.value for av in self.attribute_values.all()]
        if attr_vals:
            return " - ".join(attr_vals)
            
        return self.name or self.sku_suffix or f"Variant {self.pk}"
    base_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        verbose_name="Base price",
    )
    mrp = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        verbose_name="MRP",
    )
    purchase_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        verbose_name="Purchase Price",
    )
    sku_suffix = models.CharField(
        max_length=128,
        blank=True,
        null=True,
        unique=True,
        verbose_name="Variant SKU",
        help_text="Full globally unique SKU for this variant.",
    )
    stock_quantity = models.PositiveIntegerField(
        default=0,
        verbose_name="Stock quantity",
    )
    low_stock_threshold = models.PositiveIntegerField(
        default=5,
        verbose_name="Low stock threshold",
    )

    class Meta:
        verbose_name = "Product variant"
        verbose_name_plural = "Product variants"
        ordering = ["display_order", "id"]

    def __str__(self) -> str:
        return self.sku_suffix or f"{self.product.sku}-Variant"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.product_id:
            total = self.product.variants.aggregate(total=models.Sum("stock_quantity"))["total"] or 0
            Product.objects.filter(pk=self.product_id).update(stock_quantity=total)

    def delete(self, *args, **kwargs):
        product_id = self.product_id
        res = super().delete(*args, **kwargs)
        if product_id:
            total = ProductVariant.objects.filter(product_id=product_id).aggregate(total=models.Sum("stock_quantity"))["total"] or 0
            Product.objects.filter(pk=product_id).update(stock_quantity=total)
        return res


class ProductImage(TimeStampedModel):
    """Gallery image for a product."""

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="images",
        verbose_name="Product",
    )
    variant = models.ForeignKey(
        "ProductVariant",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="images",
        verbose_name="Variant",
    )
    image = models.ImageField(
        upload_to="products/images/",
        verbose_name="Image",
    )
    alt_text = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="Alt text",
    )
    display_order = models.PositiveIntegerField(
        default=0,
        verbose_name="Display order",
    )
    is_primary = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name="Is primary",
        help_text="Primary image shown on PLP cards and homepage rails.",
    )

    class Meta:
        verbose_name = "Product image"
        verbose_name_plural = "Product images"
        ordering = ["display_order"]
        indexes = [
            models.Index(
                fields=["product", "is_primary"],
                name="cat_img_product_primary_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"Image for {self.product.slug}"


class ProductVideo(TimeStampedModel):
    """Hosted or external video for a product detail page."""

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="videos",
        verbose_name="Product",
    )
    variant = models.ForeignKey(
        "ProductVariant",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="videos",
        verbose_name="Variant",
    )
    video_file = models.FileField(
        upload_to="products/videos/",
        verbose_name="Video File",
    )
    thumbnail = models.ImageField(
        upload_to="products/video_thumbs/",
        blank=True,
        verbose_name="Thumbnail",
    )

    class Meta:
        verbose_name = "Product video"
        verbose_name_plural = "Product videos"

    def __str__(self) -> str:
        return f"Video for {self.product.slug}"


class RelationType(models.TextChoices):
    """Types of product-to-product relationships."""

    RELATED = "related", "Related"
    FREQUENTLY_BOUGHT_TOGETHER = "fbt", "Frequently Bought Together"


class ProductRelation(TimeStampedModel):
    """Directed relationship between two products."""

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="relations",
        verbose_name="Product",
    )
    related_product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="related_from",
        verbose_name="Related product",
    )
    relation_type = models.CharField(
        max_length=20,
        choices=RelationType.choices,
        verbose_name="Relation type",
    )

    class Meta:
        verbose_name = "Product relation"
        verbose_name_plural = "Product relations"
        unique_together = [("product", "related_product", "relation_type")]

    def __str__(self) -> str:
        return f"{self.product.slug} -> {self.related_product.slug} ({self.relation_type})"


class ModerationStatus(models.TextChoices):
    """Review moderation workflow states."""

    PENDING = "pending", "Pending"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


class Review(TimeStampedModel):
    """Customer product review subject to moderation."""

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="reviews",
        verbose_name="Product",
    )
    customer = models.ForeignKey(
        "accounts.CustomerProfile",
        on_delete=models.CASCADE,
        related_name="reviews",
        verbose_name="Customer",
    )
    rating = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        verbose_name="Rating",
    )
    title = models.CharField(max_length=200, verbose_name="Title")
    body = models.TextField(verbose_name="Body")
    is_verified_purchase = models.BooleanField(
        default=False,
        verbose_name="Verified purchase",
    )
    moderation_status = models.CharField(
        max_length=20,
        choices=ModerationStatus.choices,
        default=ModerationStatus.PENDING,
        db_index=True,
        verbose_name="Moderation status",
    )
    moderated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="moderated_reviews",
        verbose_name="Moderated by",
    )

    class Meta:
        verbose_name = "Review"
        verbose_name_plural = "Reviews"
        indexes = [
            models.Index(
                fields=["product", "moderation_status"],
                name="cat_review_product_mod_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.rating}★ — {self.product.slug}"


class ReviewPhoto(TimeStampedModel):
    """Photo attached to a customer review."""

    review = models.ForeignKey(
        Review,
        on_delete=models.CASCADE,
        related_name="photos",
        verbose_name="Review",
    )
    image = models.ImageField(
        upload_to="reviews/photos/",
        verbose_name="Image",
    )

    class Meta:
        verbose_name = "Review photo"
        verbose_name_plural = "Review photos"

    def __str__(self) -> str:
        return f"Photo for review {self.review_id}"


class ProductSpecification(TimeStampedModel):
    """Specification key-value pair for a product."""

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="specifications",
        verbose_name="Product",
    )
    name = models.CharField(
        max_length=120,
        verbose_name="Specification Name",
        help_text="e.g., Weight, Dimensions, Battery Life, Voltage",
    )
    value = models.CharField(
        max_length=1024,
        verbose_name="Specification Value",
        help_text="e.g., 2.5 kg, 12V, Lithium-Ion",
    )
    display_order = models.PositiveIntegerField(
        default=0,
        verbose_name="Display order",
        help_text="Lower values appear first.",
    )

    class Meta:
        verbose_name = "Product Specification"
        verbose_name_plural = "Product Specifications"
        ordering = ["display_order", "name"]
        unique_together = [("product", "name")]

    def __str__(self) -> str:
        return f"{self.product.name} - {self.name}: {self.value}"


class ProductDocument(TimeStampedModel):
    """Downloadable document/manual for a product."""

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="documents",
        verbose_name="Product",
    )
    title = models.CharField(
        max_length=150,
        verbose_name="Document Title",
        help_text="e.g., User Manual, Installation Guide, Warranty Details",
    )
    document_file = models.FileField(
        upload_to="products/documents/",
        verbose_name="Document File",
        help_text="PDF format manuals or brochures.",
    )
    display_order = models.PositiveIntegerField(
        default=0,
        verbose_name="Display order",
        help_text="Lower values appear first.",
    )

    class Meta:
        verbose_name = "Product Document"
        verbose_name_plural = "Product Documents"
        ordering = ["display_order", "title"]

    @property
    def filename(self) -> str:
        import os
        return os.path.basename(self.document_file.name) if self.document_file else ""

    def __str__(self) -> str:
        return f"{self.product.name} - {self.title}"


class HomePageProduct(TimeStampedModel):
    """Tracks products toggled to appear on the homepage."""

    product = models.OneToOneField(
        Product,
        on_delete=models.CASCADE,
        related_name="homepage_featured",
        verbose_name="Product",
    )
    is_shown = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name="Is shown on home",
    )

    class Meta:
        verbose_name = "Home Page Product"
        verbose_name_plural = "Home Page Products"
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return f"{self.product.name} (Shown: {self.is_shown})"
