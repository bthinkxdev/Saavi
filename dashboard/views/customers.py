"""Customer and inquiry management."""

from __future__ import annotations

from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render, redirect
from django.core.mail import EmailMessage
from django.conf import settings
from django.contrib import messages

from accounts.models import CustomerProfile
from core.models import ContactInquiry
from dashboard import forms
from dashboard.access import dashboard_required
from dashboard.views.base import DashboardListView, DashboardUpdateView, DashboardDeleteView


class CustomerListView(DashboardListView):
    model = CustomerProfile
    nav_section = "customers"
    url_basename = "customer"
    singular_name = "Customer"
    plural_name = "Customers"
    search_fields = ["user__email", "user__username", "phone"]
    select_related = ["user"]
    can_create = False
    can_view = True
    can_delete = False
    columns = [
        {"label": "Name", "name": "user.get_full_name"},
        {"label": "Email", "name": "user.email"},
        {"label": "Phone", "name": "get_phone"},
        {"label": "Verified", "name": "phone_verified", "type": "bool"},
    ]


class CustomerUpdateView(DashboardUpdateView):
    model = CustomerProfile
    form_class = forms.CustomerProfileForm
    nav_section = "customers"
    url_basename = "customer"
    singular_name = "Customer"


@dashboard_required
def customer_detail(request: HttpRequest, pk: int) -> HttpResponse:
    """Customer profile with addresses and recent orders."""
    profile = get_object_or_404(CustomerProfile.objects.select_related("user"), pk=pk)
    context = {
        "nav_section": "customers",
        "page_title": str(profile),
        "profile": profile,
        "addresses": profile.addresses.all(),
        "orders": profile.orders.order_by("-created_at")[:10],
    }
    return render(request, "dashboard/customers/detail.html", context)


class ContactInquiryListView(DashboardListView):
    model = ContactInquiry
    nav_section = "inquiries"
    url_basename = "inquiry"
    singular_name = "Inquiry"
    plural_name = "Inquiries"
    search_fields = ["name", "email", "message"]
    can_create = False
    can_view = True
    can_edit = False
    can_delete = True
    columns = [
        {"label": "Name", "name": "name"},
        {"label": "Email", "name": "email"},
        {"label": "Date", "name": "created_at", "type": "date"},
        {"label": "Replied", "name": "is_replied", "type": "bool"},
    ]


class ContactInquiryDeleteView(DashboardDeleteView):
    model = ContactInquiry
    nav_section = "inquiries"
    url_basename = "inquiry"
    singular_name = "Inquiry"


@dashboard_required
def inquiry_detail(request: HttpRequest, pk: int) -> HttpResponse:
    """Read full inquiry message and handle reply."""
    from django.utils import timezone
    inquiry = get_object_or_404(ContactInquiry, pk=pk)
    
    from core.services import get_site_settings
    site_settings = get_site_settings()
    site_name = site_settings.site_name or "Sarocchi Luxe Designs"
    subject = inquiry.reply_subject or f"Re: Your inquiry to {site_name}"
    message_text = inquiry.reply_message or ""
    reply_sent = bool(inquiry.replied_at)

    if request.method == "POST":
        subject = request.POST.get("subject", subject)
        message_text = request.POST.get("message", "")
        if subject and message_text:
            try:
                email = EmailMessage(
                    subject=subject,
                    body=message_text,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    to=[inquiry.email],
                )
                email.send(fail_silently=False)
                
                inquiry.reply_subject = subject
                inquiry.reply_message = message_text
                inquiry.replied_at = timezone.now()
                inquiry.save()
                
                messages.success(request, f"Reply sent to {inquiry.email} successfully.")
                reply_sent = True
            except Exception as e:
                messages.error(request, f"Failed to send email: {e}")
        else:
            messages.error(request, "Subject and Message are required.")

    context = {
        "nav_section": "inquiries",
        "page_title": f"Inquiry from {inquiry.name}",
        "inquiry": inquiry,
        "subject": subject,
        "message": message_text,
        "reply_sent": reply_sent,
    }
    return render(request, "dashboard/customers/inquiry_detail.html", context)
