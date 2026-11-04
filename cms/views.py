"""HTTP views for the cms app; thin request parsing delegating to selectors/services."""

from __future__ import annotations

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from catalog.selectors import get_homepage_product_rails
from cms.selectors import get_active_homepage_sections
from cms.services import get_section_render_context
from core.seo import seo_context


@require_GET
def homepage_view(request: HttpRequest) -> HttpResponse:
    """Render the CMS-driven homepage with zero DB reads for section config."""
    sections = get_active_homepage_sections()
    product_rails = get_homepage_product_rails()
    section_contexts = [
        {
            "section_type": section["section_type"],
            "partial": f"cms/sections/{section['section_type']}.html",
            "context": get_section_render_context(section=section, product_rails=product_rails),
        }
        for section in sections
    ]
    context = seo_context(
        request=request,
        title="Sarocchi Luxe Designs | Premium Sarees & Jewellery NZ",
        description="Discover luxury sarees, bridal collections, and handcrafted jewellery tailored for New Zealand by Sarocchi Luxe Designs.",
    )
    context["section_contexts"] = section_contexts
    response = render(request, "cms/homepage.html", context)
    response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response["Pragma"] = "no-cache"
    return response
