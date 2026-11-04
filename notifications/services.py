"""Write operations and business rules for the notifications app."""

from __future__ import annotations

import logging

from django.contrib.auth.models import User

from notifications.models import Notification

logger = logging.getLogger(__name__)


def send_sms(*, phone: str, message: str) -> None:
    """Dispatch an SMS — provider-agnostic stub that logs the payload."""
    logger.info("SMS to %s: %s", phone, message)


def send_email(*, email: str, subject: str, message: str) -> None:
    """Dispatch an email via Django's configured backend (console in dev, SMTP in production)."""
    from django.core.mail import send_mail
    from django.conf import settings
    from core.services import get_site_settings
    
    logger.info("Email to %s [%s]: %s", email, subject, message)
    
    site_settings = get_site_settings()
    if site_settings.site_name:
        from_email = f'"{site_settings.site_name}" <{settings.DEFAULT_FROM_EMAIL}>'
    else:
        from_email = settings.DEFAULT_FROM_EMAIL
    
    send_mail(
        subject=subject,
        message=message,
        from_email=from_email,
        recipient_list=[email],
        fail_silently=False,
    )


GUPSHUP_MSG_URL = "https://api.gupshup.io/wa/api/v1/msg"
GUPSHUP_TEMPLATE_URL = "https://api.gupshup.io/wa/api/v1/template/msg"


def _wa_digits(phone: str) -> str:
    """Gupshup expects the number with country code, digits only."""
    return "".join(ch for ch in (phone or "") if ch.isdigit())


def send_whatsapp(*, phone: str, message: str, template_id: str = "", template_params: list | None = None) -> bool:
    """Send a WhatsApp message through Gupshup.

    Free-form text only reaches customers inside the 24-hour service window; for
    business-initiated messages pass an approved ``template_id`` + params.
    Credentials live in SiteSettings (dashboard → Settings). Returns True on success.
    """
    import json

    import requests

    from core.services import get_site_settings

    site_settings = get_site_settings()
    api_key = getattr(site_settings, "gupshup_api_key", "")
    source = _wa_digits(getattr(site_settings, "gupshup_source_number", ""))
    destination = _wa_digits(phone)
    if not (api_key and source and destination):
        logger.info("WhatsApp (Gupshup not configured) to %s: %s", phone, message)
        return False

    data = {
        "channel": "whatsapp",
        "source": source,
        "destination": destination,
        "src.name": getattr(site_settings, "gupshup_app_name", "") or "",
    }
    if template_id:
        url = GUPSHUP_TEMPLATE_URL
        data["template"] = json.dumps({"id": template_id, "params": template_params or []})
    else:
        url = GUPSHUP_MSG_URL
        data["message"] = json.dumps({"type": "text", "text": message})

    try:
        resp = requests.post(
            url,
            data=data,
            headers={"apikey": api_key, "Content-Type": "application/x-www-form-urlencoded"},
            timeout=10,
        )
    except requests.RequestException:
        logger.exception("Gupshup WhatsApp send failed to %s", destination)
        return False
    if resp.status_code >= 300:
        logger.warning("Gupshup WhatsApp error %s: %s", resp.status_code, resp.text[:300])
        return False
    return True


def create_notification(*, user: User, title: str, body: str = "") -> Notification:
    """
    Persist an in-app notification for a user.

    Params:
        user: Recipient Django User.
        title: Notification headline.
        body: Optional full message body.
    Returns:
        Created Notification instance.
    """
    return Notification.objects.create(user=user, title=title, body=body)
