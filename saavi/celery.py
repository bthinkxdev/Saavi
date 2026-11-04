"""Celery application instance for saavi."""

from __future__ import annotations

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "saavi.settings.dev")

app = Celery("saavi")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
