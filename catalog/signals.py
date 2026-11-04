"""Cache invalidation signals for catalog models."""

from __future__ import annotations

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from catalog.models import Category
from catalog.selectors import invalidate_category_tree_cache


@receiver(post_save, sender=Category)
@receiver(post_delete, sender=Category)
def category_changed(sender, instance: Category, **kwargs) -> None:
    invalidate_category_tree_cache()
