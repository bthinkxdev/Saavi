"""sarocchi project package; loads Celery app on Django startup."""

from __future__ import annotations

from sarocchi.celery import app as celery_app

__all__ = ("celery_app",)
