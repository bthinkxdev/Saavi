"""Write operations and business rules for the catalog app."""

from __future__ import annotations

from typing import Any, Union

from django.contrib.auth.models import User
from django.db import transaction

from accounts.models import CustomerProfile
from catalog.exceptions import InsufficientStockError, ProductValidationError
from catalog.models import (
    ModerationStatus,
    Product,
    ProductImage,
    ProductVariant,
    Review,
)


@transaction.atomic
def create_product_with_variants(
    *,
    product_data: dict[str, Any],
    variants_data: list[dict[str, Any]],
    images_data: list[dict[str, Any]],
) -> Product:
    """
    Atomically create a product with variants and images.

    Params:
        product_data: Field values for Product.
        variants_data: List of variant dicts (variant_type, name, price_delta, etc.).
        images_data: List of image dicts; at least one must have is_primary=True.
    Returns:
        Created Product instance.
    Raises:
        ProductValidationError: When no primary image is provided.
    """
    if not any(img.get("is_primary") for img in images_data):
        raise ProductValidationError("At least one primary image is required.")

    product = Product.objects.create(**product_data)

    for variant_data in variants_data:
        ProductVariant.objects.create(product=product, **variant_data)

    for image_data in images_data:
        ProductImage.objects.create(product=product, **image_data)

    return product


@transaction.atomic
def adjust_stock(
    *,
    target: Union[Product, ProductVariant],
    delta: int,
    reason: str,
) -> Union[Product, ProductVariant]:
    """
    Atomically adjust stock using select_for_update to prevent race conditions.

    Params:
        target: Product or ProductVariant instance to adjust.
        delta: Positive or negative integer change.
        reason: Audit reason string (logged in Phase 4 inventory module).
    Returns:
        Updated target instance.
    Raises:
        InsufficientStockError: When adjustment would make stock negative.
    """
    if isinstance(target, Product):
        locked = Product.objects.select_for_update().get(pk=target.pk)
        old_quantity = locked.stock_quantity
        new_quantity = locked.stock_quantity + delta
        if new_quantity < 0:
            raise InsufficientStockError(f"Insufficient stock for product {locked.sku}: {reason}")
        locked.stock_quantity = new_quantity
        locked.save(update_fields=["stock_quantity", "updated_at"])
        
        if old_quantity > locked.low_stock_threshold and new_quantity <= locked.low_stock_threshold:
            from notifications.tasks import dispatch_low_stock_admin_notification
            transaction.on_commit(
                lambda: dispatch_low_stock_admin_notification.delay(
                    product_name=locked.name,
                    sku=locked.sku,
                    current_stock=new_quantity,
                    threshold=locked.low_stock_threshold,
                )
            )
        return locked

    locked = ProductVariant.objects.select_for_update().get(pk=target.pk)
    old_quantity = locked.stock_quantity
    new_quantity = locked.stock_quantity + delta
    if new_quantity < 0:
        raise InsufficientStockError(f"Insufficient stock for variant {locked}: {reason}")
    locked.stock_quantity = new_quantity
    locked.save(update_fields=["stock_quantity", "updated_at"])

    if old_quantity > locked.low_stock_threshold and new_quantity <= locked.low_stock_threshold:
        from notifications.tasks import dispatch_low_stock_admin_notification
        product_name = f"{locked.product.name} ({locked.name})" if locked.name else locked.product.name
        full_sku = locked.sku_suffix if locked.sku_suffix else locked.product.sku
        transaction.on_commit(
            lambda: dispatch_low_stock_admin_notification.delay(
                product_name=product_name,
                sku=full_sku,
                current_stock=new_quantity,
                threshold=locked.low_stock_threshold,
            )
        )
    return locked


@transaction.atomic
def submit_review(
    *,
    product: Product,
    customer: CustomerProfile,
    rating: int,
    title: str,
    body: str,
    is_verified_purchase: bool = False,
) -> Review:
    """
    Create a review in PENDING moderation state and notify admins via Celery.

    Params:
        product: Reviewed product.
        customer: Author customer profile.
        rating: Star rating 1–5.
        title: Review headline.
        body: Review body text.
        is_verified_purchase: Whether the customer bought this product.
    Returns:
        Created Review in PENDING status.
    """
    from catalog.tasks import notify_review_moderation

    review = Review.objects.create(
        product=product,
        customer=customer,
        rating=rating,
        title=title,
        body=body,
        is_verified_purchase=is_verified_purchase,
        moderation_status=ModerationStatus.PENDING,
    )
    notify_review_moderation.delay(review_id=review.pk)
    return review


@transaction.atomic
def moderate_review(
    *,
    review_id: int,
    decision: str,
    moderator: User,
) -> Review:
    """
    Transition a review's moderation_status to APPROVED or REJECTED.

    Params:
        review_id: Primary key of the review.
        decision: ModerationStatus value (approved or rejected).
        moderator: Admin user performing moderation.
    Returns:
        Updated Review instance.
    """
    if decision not in (ModerationStatus.APPROVED, ModerationStatus.REJECTED):
        raise ValueError(f"Invalid moderation decision: {decision}")

    review = Review.objects.select_for_update().get(pk=review_id)
    review.moderation_status = decision
    review.moderated_by = moderator
    review.save(update_fields=["moderation_status", "moderated_by", "updated_at"])
    
    #dismiss the notification for all admins
    from notifications.models import Notification
    body_text = f'Review "{review.title}" on {review.product.name} awaits approval.'
    Notification.objects.filter(
        title="Review pending moderation", 
        body=body_text,
        is_read=False
    ).update(is_read=True)

    return review
