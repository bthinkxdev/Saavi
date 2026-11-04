"""HTTP views for the delivery app; thin request parsing delegating to selectors/services."""

from django.http import HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET

from core.models import SiteSettings
from delivery.models import City

@require_GET
def delivery_estimate(request: HttpRequest) -> JsonResponse:
    """Return JSON delivery estimate for a specific city_id."""
    city_id = request.GET.get("city_id")
    if not city_id:
        return JsonResponse({"error": "Missing city_id parameter."}, status=400)
        
    city = get_object_or_404(City, pk=city_id, is_active=True)
    settings = SiteSettings.objects.first()
    
    estimate_text = city.estimated_delivery_text or (settings.default_estimated_delivery_text if settings else "")
    
    return JsonResponse({
        "city_id": city.pk,
        "city_name": city.name,
        "estimated_delivery_text": estimate_text,
        "delivery_charge": str(city.delivery_charge_base),
    })
