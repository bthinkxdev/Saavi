"""URL routing for the marketing app."""

from __future__ import annotations

from django.urls import path

from marketing import views

app_name = "marketing"

urlpatterns = [
    path("flash-sales/", views.flash_sales_view, name="flash-sales"),
    path("newsletter/subscribe/", views.newsletter_subscribe_view, name="newsletter-subscribe"),
]