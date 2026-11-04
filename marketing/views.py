"""HTTP views for the marketing app; thin request parsing delegating to selectors/services."""

from __future__ import annotations

from django.contrib import messages
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.views.decorators.http import require_POST

from marketing.forms import NewsletterSignupForm
from marketing.services import subscribe_newsletter


@require_POST
def newsletter_subscribe_view(request: HttpRequest) -> HttpResponse:
    """Subscribe an email to the newsletter from the homepage form."""
    referer = request.META.get("HTTP_REFERER", "/")
    if "#" in referer:
        referer = referer.split("#")[0]
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.accepts("application/json")

    from core.services import get_site_settings
    site_settings = get_site_settings()
    if not getattr(site_settings, "enable_newsletter", True):
        msg = "Newsletter subscription is currently unavailable."
        if is_ajax:
            return JsonResponse({"status": "error", "message": msg}, status=400)
        messages.error(request, msg)
        return redirect(redirect_url)

    form = NewsletterSignupForm(request.POST)
    if not form.is_valid():
        email_errors = form.errors.get("email")
        if email_errors:
            error_msg = email_errors[0]
            if error_msg == "This field is required.":
                msg = "Email address cannot be empty."
            else:
                msg = "Please enter a valid email address."
        else:
            msg = "Invalid form submission."
        
        if is_ajax:
            return JsonResponse({"status": "error", "message": msg}, status=400)
            
        messages.error(request, msg)
        return redirect(redirect_url)
        
    subscriber, is_new = subscribe_newsletter(email=form.cleaned_data["email"])
    
    if is_new:
        msg = "Thank you for subscribing to our newsletter!"
        if is_ajax:
            return JsonResponse({"status": "success", "message": msg})
        messages.success(request, msg)
    else:
        msg = "This email is already subscribed to our newsletter."
        if is_ajax:
            return JsonResponse({"status": "info", "message": msg})
        messages.info(request, msg)
        
    return redirect(redirect_url)


def flash_sales_view(request: HttpRequest) -> HttpResponse:
    """Redirect to storefront shop page filtered by active flash sales."""
    return redirect("/shop/?flash_sale=1")