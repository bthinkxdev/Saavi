"""Celery tasks for core platform maintenance."""

from __future__ import annotations

from celery import shared_task
from django.core.cache import cache
from django.test import Client


@shared_task(name="core.tasks.refresh_sitemap_cache")
def refresh_sitemap_cache() -> int:
    """
    Warm sitemap endpoints nightly so the first crawler hit is fast.

    Returns HTTP status code from sitemap index request.
    """
    client = Client()
    response = client.get("/sitemap.xml")
    cache.set("seo:sitemap:last_refresh", response.status_code, timeout=86400 * 2)
    return response.status_code
