"""Delivery management views: cities and zones."""

from __future__ import annotations

from delivery.models import City, Country
from dashboard import forms
from dashboard.views.base import (
    DashboardCreateView,
    DashboardDeleteView,
    DashboardListView,
    DashboardUpdateView,
)

class CityListView(DashboardListView):
    model = City
    nav_section = "cities"
    url_basename = "city"
    singular_name = "City"
    plural_name = "Cities"
    search_fields = ["name", "country__name"]
    select_related = ["country"]
    paginate_by = 20
    columns = [
        {"label": "Name", "name": "name"},
        {"label": "Country", "name": "country.name"},
        {"label": "Base Charge", "name": "delivery_charge_base", "type": "money"},
        {"label": "Est. Delivery", "name": "estimated_delivery_text"},
        {"label": "Active", "name": "is_active", "type": "bool"},
    ]

class CityCreateView(DashboardCreateView):
    model = City
    form_class = forms.CityForm
    nav_section = "cities"
    url_basename = "city"
    singular_name = "City"

class CityUpdateView(DashboardUpdateView):
    model = City
    form_class = forms.CityForm
    nav_section = "cities"
    url_basename = "city"
    singular_name = "City"

class CityDeleteView(DashboardDeleteView):
    model = City
    nav_section = "cities"
    url_basename = "city"
    singular_name = "City"
