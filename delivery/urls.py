"""URL routing for the delivery app."""

from __future__ import annotations

from django.urls import path
from delivery.views import delivery_estimate

app_name = "delivery"

urlpatterns: list = [
    path("api/estimate/", delivery_estimate, name="estimate"),
]
