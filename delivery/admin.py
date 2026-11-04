"""Django admin registrations for the delivery app."""

from __future__ import annotations

from django.contrib import admin

from delivery.models import City, Country

@admin.register(Country)
class CountryAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "code")
    ordering = ("name",)

@admin.register(City)
class CityAdmin(admin.ModelAdmin):
    list_display = ("name", "country", "is_active", "delivery_charge_base", "estimated_delivery_text")
    list_filter = ("country", "is_active")
    search_fields = ("name",)
    ordering = ("name",)
