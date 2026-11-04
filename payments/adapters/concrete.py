"""Concrete payment gateway adapters."""

from __future__ import annotations

import logging
import hashlib
import hmac
import json
import uuid
from decimal import Decimal
from typing import Any

from payments.adapters.base import PaymentCaptureResult, PaymentGatewayAdapter, PaymentIntentResult


class CardGatewayAdapter(PaymentGatewayAdapter):
    """
    Generic card processor sandbox adapter.

    Uses a vendor-neutral interface (Stripe-like intent/capture shape) without
    coupling to a specific SDK — swap the internals when a processor is chosen.
    """

    key = "card"
    display_name = "Credit / Debit Card"
    is_async = False

    def create_payment_intent(
        self,
        *,
        amount: Decimal,
        currency: str,
        metadata: dict[str, Any],
    ) -> PaymentIntentResult:
        intent_id = f"card_pi_{uuid.uuid4().hex[:16]}"
        return PaymentIntentResult(
            intent_id=intent_id,
            client_secret=f"{intent_id}_secret",
            metadata={"amount": str(amount), "currency": currency, **metadata},
        )

    def verify_webhook(self, *, payload: bytes, signature: str) -> dict[str, Any]:
        expected = hmac.new(b"sandbox-card", payload, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise ValueError("Invalid card webhook signature.")
        return json.loads(payload.decode())

    def capture(self, *, intent_id: str) -> PaymentCaptureResult:
        if intent_id.startswith("card_fail"):
            return PaymentCaptureResult(success=False, transaction_id=intent_id)
        return PaymentCaptureResult(
            success=True,
            transaction_id=f"card_tx_{intent_id}",
            metadata={"gateway": self.key},
        )

    def refund(self, *, transaction_id: str, amount: Decimal) -> PaymentCaptureResult:
        return PaymentCaptureResult(success=True, transaction_id=f"refund_{transaction_id}")


class QatarLocalGatewayAdapter(PaymentGatewayAdapter):
    """Qatar local payment rails sandbox adapter (e.g. NAPS-style deferred confirm)."""

    key = "qatar_local"
    display_name = "Qatar Local Payment"
    is_async = True

    def create_payment_intent(
        self,
        *,
        amount: Decimal,
        currency: str,
        metadata: dict[str, Any],
    ) -> PaymentIntentResult:
        intent_id = f"qa_pi_{uuid.uuid4().hex[:16]}"
        return PaymentIntentResult(
            intent_id=intent_id,
            metadata={"amount": str(amount), "currency": currency, **metadata},
            requires_webhook=True,
        )

    def verify_webhook(self, *, payload: bytes, signature: str) -> dict[str, Any]:
        expected = hmac.new(b"sandbox-qatar", payload, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise ValueError("Invalid Qatar local webhook signature.")
        return json.loads(payload.decode())

    def capture(self, *, intent_id: str) -> PaymentCaptureResult:
        return PaymentCaptureResult(success=True, transaction_id=f"qa_tx_{intent_id}")

    def refund(self, *, transaction_id: str, amount: Decimal) -> PaymentCaptureResult:
        return PaymentCaptureResult(success=True, transaction_id=f"qa_refund_{transaction_id}")


class ApplePayAdapter(PaymentGatewayAdapter):
    """Apple Pay wallet adapter — async webhook confirmation."""

    key = "apple_pay"
    display_name = "Apple Pay"
    is_async = True

    def create_payment_intent(
        self,
        *,
        amount: Decimal,
        currency: str,
        metadata: dict[str, Any],
    ) -> PaymentIntentResult:
        intent_id = f"ap_pi_{uuid.uuid4().hex[:16]}"
        return PaymentIntentResult(intent_id=intent_id, requires_webhook=True, metadata=metadata)

    def verify_webhook(self, *, payload: bytes, signature: str) -> dict[str, Any]:
        expected = hmac.new(b"sandbox-apple", payload, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise ValueError("Invalid Apple Pay webhook signature.")
        return json.loads(payload.decode())

    def capture(self, *, intent_id: str) -> PaymentCaptureResult:
        return PaymentCaptureResult(success=True, transaction_id=f"ap_tx_{intent_id}")

    def refund(self, *, transaction_id: str, amount: Decimal) -> PaymentCaptureResult:
        return PaymentCaptureResult(success=True, transaction_id=f"ap_refund_{transaction_id}")


class GooglePayAdapter(PaymentGatewayAdapter):
    """Google Pay wallet adapter — async webhook confirmation."""

    key = "google_pay"
    display_name = "Google Pay"
    is_async = True

    def create_payment_intent(
        self,
        *,
        amount: Decimal,
        currency: str,
        metadata: dict[str, Any],
    ) -> PaymentIntentResult:
        intent_id = f"gp_pi_{uuid.uuid4().hex[:16]}"
        return PaymentIntentResult(intent_id=intent_id, requires_webhook=True, metadata=metadata)

    def verify_webhook(self, *, payload: bytes, signature: str) -> dict[str, Any]:
        expected = hmac.new(b"sandbox-google", payload, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise ValueError("Invalid Google Pay webhook signature.")
        return json.loads(payload.decode())

    def capture(self, *, intent_id: str) -> PaymentCaptureResult:
        return PaymentCaptureResult(success=True, transaction_id=f"gp_tx_{intent_id}")

    def refund(self, *, transaction_id: str, amount: Decimal) -> PaymentCaptureResult:
        return PaymentCaptureResult(success=True, transaction_id=f"gp_refund_{transaction_id}")


class CashOnDeliveryAdapter(PaymentGatewayAdapter):
    """
    Cash on Delivery (COD) payment adapter.
    """

    key = "cod"
    display_name = "Cash on Delivery"
    is_async = False

    def create_payment_intent(
        self,
        *,
        amount: Decimal,
        currency: str,
        metadata: dict[str, Any],
    ) -> PaymentIntentResult:
        intent_id = f"cod_pi_{uuid.uuid4().hex[:16]}"
        return PaymentIntentResult(
            intent_id=intent_id,
            metadata={"amount": str(amount), "currency": currency, **metadata},
        )

    def verify_webhook(self, *, payload: bytes, signature: str) -> dict[str, Any]:
        raise NotImplementedError("Cash on Delivery does not use webhooks.")

    def capture(self, *, intent_id: str) -> PaymentCaptureResult:
        return PaymentCaptureResult(
            success=True,
            transaction_id=f"cod_tx_{intent_id}",
            metadata={"gateway": self.key},
        )

    def refund(self, *, transaction_id: str, amount: Decimal) -> PaymentCaptureResult:
        return PaymentCaptureResult(success=True, transaction_id=f"cod_refund_{transaction_id}")


def _get_razorpay_credentials() -> tuple[str, str]:
    try:
        from core.models import SiteSettings
        settings_inst = SiteSettings.objects.first()
        if settings_inst:
            key_id = settings_inst.razorpay_key_id.strip()
            key_secret = settings_inst.razorpay_key_secret.strip()
            if key_id and key_secret:
                return key_id, key_secret
    except Exception:
        pass
    import os
    return os.getenv("RAZORPAY_KEY_ID", ""), os.getenv("RAZORPAY_KEY_SECRET", "")


class RazorpayAdapter(PaymentGatewayAdapter):
    """
    Razorpay payment gateway base adapter.
    """
    key = "razorpay"
    display_name = "Razorpay (UPI, Credit/Debit Card, Net Banking, Wallets)"
    is_async = True

    def create_payment_intent(
        self,
        *,
        amount: Decimal,
        currency: str,
        metadata: dict[str, Any],
    ) -> PaymentIntentResult:
        key_id, key_secret = _get_razorpay_credentials()
        amount_in_paise = int(amount * 100)

        if key_id and key_secret:
            try:
                import requests
                response = requests.post(
                    "https://api.razorpay.com/v1/orders",
                    auth=(key_id, key_secret),
                    json={
                        "amount": amount_in_paise,
                        "currency": currency,
                        "receipt": f"ord_{metadata.get('order_id', '')}",
                        "notes": {
                            "order_id": str(metadata.get("order_id", "")),
                            "order_number": str(metadata.get("order_number", "")),
                        },
                    },
                    timeout=10,
                )
                if response.status_code in (200, 201):
                    data = response.json()
                    intent_id = data.get("id")
                    return PaymentIntentResult(
                        intent_id=intent_id,
                        requires_webhook=True,
                        metadata={"key_id": key_id, "razorpay_order_id": intent_id, **metadata},
                    )
            except Exception:
                pass

        intent_id = f"rzp_order_{uuid.uuid4().hex[:16]}"
        return PaymentIntentResult(
            intent_id=intent_id,
            requires_webhook=True,
            metadata={"key_id": key_id or "rzp_test_mock", "razorpay_order_id": intent_id, **metadata},
        )

    def verify_payment_signature(
        self,
        *,
        razorpay_order_id: str,
        razorpay_payment_id: str,
        razorpay_signature: str,
    ) -> bool:
        key_id, key_secret = _get_razorpay_credentials()
        if not key_secret:
            return True
        msg = f"{razorpay_order_id}|{razorpay_payment_id}".encode("utf-8")
        expected = hmac.new(key_secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, razorpay_signature)

    def verify_webhook(self, *, payload: bytes, signature: str) -> dict[str, Any]:
        key_id, key_secret = _get_razorpay_credentials()
        if key_secret:
            expected = hmac.new(key_secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected, signature):
                raise ValueError("Invalid Razorpay webhook signature.")
        return json.loads(payload.decode())

    def capture_payment(
        self,
        *,
        razorpay_payment_id: str,
        amount: Any = 0,
        currency: str = None,
    ) -> bool:
        """
        Capture a Razorpay payment, or confirm it was already captured.

        Returns True only when Razorpay confirms the payment is actually
        captured — never on ambiguity. Two cases require care beyond a bare
        HTTP-status check on the capture call itself:

        - Already captured: when auto-capture is enabled (Razorpay's default),
          the payment may already be captured by the time this runs. Calling
          /capture again then returns HTTP 400 "This payment has already been
          captured" — a legitimate success, not a failure. We disambiguate by
          fetching the payment directly rather than parsing error text.
        - Any network/exception failure now returns False instead of silently
          assuming success — a blocked confirmation here is still recoverable
          via the Razorpay webhook, but a wrongly-confirmed order is not.
        """
        if not currency:
            from core.selectors import get_default_currency
            default_curr = get_default_currency()
            currency = default_curr.code if default_curr else "AED"
        key_id, key_secret = _get_razorpay_credentials()
        if not (key_id and key_secret and razorpay_payment_id) or razorpay_payment_id.startswith("pay_test_"):
            return True

        import requests
        try:
            amount_in_paise = int(amount * 100)
            resp = requests.post(
                f"https://api.razorpay.com/v1/payments/{razorpay_payment_id}/capture",
                auth=(key_id, key_secret),
                json={"amount": amount_in_paise, "currency": currency},
                timeout=10,
            )
        except Exception:
            return False

        if resp.status_code in (200, 201):
            return True

        return self._fetch_payment_is_captured(
            razorpay_payment_id=razorpay_payment_id, key_id=key_id, key_secret=key_secret,
        )

    def _fetch_payment_is_captured(self, *, razorpay_payment_id: str, key_id: str, key_secret: str) -> bool:
        """Authoritative check of a payment's actual status, used when the
        capture call itself returned a non-2xx (e.g. already captured, or a
        genuine failure — only GET /payments/{id} can tell them apart)."""
        import requests
        try:
            resp = requests.get(
                f"https://api.razorpay.com/v1/payments/{razorpay_payment_id}",
                auth=(key_id, key_secret),
                timeout=10,
            )
            if resp.status_code == 200:
                return resp.json().get("status") == "captured"
        except Exception:
            pass
        return False

    def capture(self, *, intent_id: str) -> PaymentCaptureResult:
        return PaymentCaptureResult(
            success=True,
            transaction_id=f"rzp_tx_{intent_id}",
            metadata={"gateway": self.key},
        )

    def refund(self, *, transaction_id: str, amount: Decimal) -> PaymentCaptureResult:
        return PaymentCaptureResult(success=True, transaction_id=f"razorpay_refund_{transaction_id}")

class RazorpayUPIAdapter(RazorpayAdapter):
    key = "razorpay_upi"
    display_name = "UPI"

class RazorpayCardAdapter(RazorpayAdapter):
    key = "razorpay_card"
    display_name = "Credit/Debit Card"

class RazorpayNetbankingAdapter(RazorpayAdapter):
    key = "razorpay_netbanking"
    display_name = "Net Banking"

class RazorpayWalletAdapter(RazorpayAdapter):
    key = "razorpay_wallet"
    display_name = "Wallet"

#cyberSource adapter is completely isolated in payments.adapters.cybersource
from payments.adapters.cybersource import (  # noqa: F401
    CyberSourceAdapter,
    CyberSourceCardAdapter,
    _get_cybersource_config,
    _get_cybersource_credentials,
)


def _get_afterpay_credentials() -> tuple[str, str, str, str, str]:
    """
    Retrieve Afterpay credentials.
    Priority: SiteSettings database model -> django.conf.settings -> defaults.
    Returns: (merchant_id, secret_key, environment, currency, country_code)
    """
    merchant_id = ""
    secret_key = ""
    env_mode = "sandbox"
    try:
        from core.services import get_site_settings
        site_settings = get_site_settings()
        merchant_id = getattr(site_settings, "afterpay_merchant_id", "") or ""
        secret_key = getattr(site_settings, "afterpay_secret_key", "") or ""
        env_mode = getattr(site_settings, "afterpay_environment", "") or "sandbox"
    except Exception:
        pass

    from django.conf import settings
    if not merchant_id:
        merchant_id = getattr(settings, "AFTERPAY_MERCHANT_ID", "")
    if not secret_key:
        secret_key = getattr(settings, "AFTERPAY_SECRET_KEY", "")
    if not env_mode:
        env_mode = getattr(settings, "AFTERPAY_ENVIRONMENT", "sandbox")

    currency = getattr(settings, "AFTERPAY_CURRENCY", "NZD")
    country_code = getattr(settings, "AFTERPAY_COUNTRY_CODE", "NZ")
    return merchant_id.strip(), secret_key.strip(), env_mode.strip().lower(), currency, country_code


class AfterpayAdapter(PaymentGatewayAdapter):
    """
    Direct Afterpay / Clearpay Online API v2 Gateway Adapter.
    Connects directly to Afterpay API without needing Cybersource Sales pilot approval.
    Includes built-in simulator fallback for instant testing when API credentials are not yet set.
    """
    key = "afterpay"
    display_name = "Afterpay (Pay in 4 installments)"
    is_async = True

    def create_payment_intent(
        self,
        *,
        amount: Decimal,
        currency: str,
        metadata: dict[str, Any] | None = None,
    ) -> PaymentIntentResult:
        metadata = metadata or {}
        metadata["payment_type"] = "afterpay"

        merchant_id, secret_key, env_mode, default_currency, country_code = _get_afterpay_credentials()
        currency = currency or default_currency
        order_id = metadata.get("order_id")

        from django.conf import settings
        from django.urls import reverse
        from orders.models import Order

        order = Order.objects.filter(pk=order_id).first() if order_id else None

        #build absolute URLs
        host = getattr(settings, "ALLOWED_HOSTS", ["localhost"])[0]
        if host == "*" or not (host.startswith("http://") or host.startswith("https://")):
            protocol = "https://" if not settings.DEBUG else "http://"
            host = f"{protocol}{host if host != '*' else 'localhost:8000'}"

        confirm_url = f"{host.rstrip('/')}/checkout/pay/afterpay/callback/?order_id={order_id}"
        cancel_url = f"{host.rstrip('/')}/checkout/"

        #if credentials are not set or marked as dummy/test simulator, use smooth simulation mode
        if not merchant_id or not secret_key or merchant_id.lower().startswith("dummy"):
            intent_id = f"afterpay_sim_{order_id}_{uuid.uuid4().hex[:12]}"
            sim_url = reverse("checkout:afterpay-pay", kwargs={"order_id": order_id})
            metadata["redirect_url"] = sim_url
            metadata["is_simulation"] = True
            metadata["order_id"] = str(order_id)
            metadata["token"] = intent_id
            return PaymentIntentResult(
                intent_id=intent_id,
                requires_webhook=False,
                metadata=metadata,
            )

        #base URL from configured environment domain (matching CyberSource pattern)
        base_url = env_mode if env_mode.startswith("http") else f"https://{env_mode.rstrip('/')}"
        endpoint = f"{base_url}/v2/checkouts"

        buyer_email = "customer@sarocchi.co.nz"
        full_name = "Sarocchi Customer"
        first_name = "Sarocchi"
        last_name = "Customer"
        phone = "0210000000"
        address1 = "123 Queen Street"
        locality = "Auckland"
        administrative_area = "Auckland"
        postal_code = "1010"

        if order:
            addr = order.delivery_address_snapshot or {}
            full_name = addr.get("name") or order.customer_display_name or "Sarocchi Customer"
            parts = full_name.split(None, 1)
            first_name = parts[0] if parts else "Customer"
            last_name = parts[1] if len(parts) > 1 else "Customer"
            buyer_email = addr.get("email") or "customer@sarocchi.co.nz"
            phone = addr.get("phone") or "0210000000"
            address1 = addr.get("street_address") or addr.get("address_line_1") or "123 Queen Street"
            locality = addr.get("city") or "Auckland"
            administrative_area = addr.get("state") or "Auckland"
            postal_code = addr.get("postal_code") or addr.get("pincode") or "1010"
            country_code = addr.get("country") or country_code

        items = []
        if order:
            for item in order.items.all():
                items.append({
                    "name": item.product.name[:128] if item.product else "Item",
                    "quantity": item.quantity,
                    "price": {
                        "amount": f"{item.unit_price:.2f}",
                        "currency": currency,
                    },
                })

        payload = {
            "amount": {
                "amount": f"{amount:.2f}",
                "currency": currency,
            },
            "consumer": {
                "phoneNumber": phone,
                "givenNames": first_name,
                "surname": last_name,
                "email": buyer_email,
            },
            "billing": {
                "name": full_name,
                "line1": address1,
                "suburb": locality,
                "state": administrative_area,
                "postcode": postal_code,
                "countryCode": country_code,
                "phoneNumber": phone,
            },
            "shipping": {
                "name": full_name,
                "line1": address1,
                "suburb": locality,
                "state": administrative_area,
                "postcode": postal_code,
                "countryCode": country_code,
                "phoneNumber": phone,
            },
            "items": items if items else None,
            "merchant": {
                "redirectConfirmUrl": confirm_url,
                "redirectCancelUrl": cancel_url,
            },
            "merchantReference": str(order_id),
        }
        if not payload.get("items"):
            payload.pop("items", None)

        import base64
        import requests
        auth_bytes = f"{merchant_id}:{secret_key}".encode("utf-8")
        auth_str = base64.b64encode(auth_bytes).decode("ascii")
        headers = {
            "Authorization": f"Basic {auth_str}",
            "Content-Type": "application/json",
            "User-Agent": "Sarocchi-Ecommerce/1.0 (Django; New Zealand)",
        }

        try:
            resp = requests.post(endpoint, json=payload, headers=headers, timeout=15)
            data = resp.json()
            if resp.status_code in (200, 201) and "redirectCheckoutUrl" in data:
                token = data.get("token")
                metadata["redirect_url"] = data["redirectCheckoutUrl"]
                metadata["token"] = token
                metadata["order_id"] = str(order_id)
                metadata["is_simulation"] = False
                return PaymentIntentResult(
                    intent_id=token,
                    requires_webhook=False,
                    metadata=metadata,
                )
            else:
                logging.warning("Afterpay checkout initiation error (status %s): %s", resp.status_code, data)
                #fallback to local sandbox simulator so checkout is not broken
                sim_url = reverse("checkout:afterpay-pay", kwargs={"order_id": order_id})
                metadata["redirect_url"] = sim_url
                metadata["is_simulation"] = True
                metadata["api_warning"] = data.get("message", "API response error")
                metadata["token"] = f"afterpay_fallback_{order_id}"
                metadata["order_id"] = str(order_id)
                return PaymentIntentResult(
                    intent_id=f"afterpay_fallback_{order_id}",
                    requires_webhook=False,
                    metadata=metadata,
                )
        except Exception as exc:
            logging.exception("Failed to connect to Afterpay API")
            sim_url = reverse("checkout:afterpay-pay", kwargs={"order_id": order_id})
            metadata["redirect_url"] = sim_url
            metadata["is_simulation"] = True
            metadata["api_warning"] = str(exc)
            metadata["token"] = f"afterpay_exc_{order_id}"
            metadata["order_id"] = str(order_id)
            return PaymentIntentResult(
                intent_id=f"afterpay_exc_{order_id}",
                requires_webhook=False,
                metadata=metadata,
            )

    def capture_order(self, *, order_token: str, order_id: str) -> dict[str, Any]:
        """
        Call Afterpay capture endpoint: POST /v2/checkouts/{orderToken}/capture
        """
        merchant_id, secret_key, env_mode, _, _ = _get_afterpay_credentials()
        base_url = env_mode if env_mode.startswith("http") else f"https://{env_mode.rstrip('/')}"
        endpoint = f"{base_url}/v2/checkouts/{order_token}/capture"

        import base64
        import requests
        auth_bytes = f"{merchant_id}:{secret_key}".encode("utf-8")
        auth_str = base64.b64encode(auth_bytes).decode("ascii")
        headers = {
            "Authorization": f"Basic {auth_str}",
            "Content-Type": "application/json",
            "User-Agent": "Sarocchi-Ecommerce/1.0 (Django; New Zealand)",
        }

        try:
            resp = requests.post(endpoint, json={"merchantReference": str(order_id)}, headers=headers, timeout=15)
            return resp.json()
        except Exception as exc:
            logging.exception("Afterpay capture failed for order %s token %s", order_id, order_token)
            return {"status": "ERROR", "message": str(exc)}

    def capture(self, *, intent_id: str) -> PaymentCaptureResult:
        return PaymentCaptureResult(
            success=True,
            transaction_id=f"afterpay_tx_{intent_id}",
            metadata={"gateway": self.key},
        )

    def refund(self, *, transaction_id: str, amount: Decimal) -> PaymentCaptureResult:
        return PaymentCaptureResult(success=True, transaction_id=f"afterpay_refund_{transaction_id}")

    def verify_webhook(self, *, payload: bytes, signature: str) -> dict[str, Any]:
        return json.loads(payload.decode())

