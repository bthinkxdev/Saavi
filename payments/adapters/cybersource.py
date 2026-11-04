"""Isolated CyberSource payment adapter module."""

from __future__ import annotations

import json
import logging
import os
import uuid
from decimal import Decimal
from typing import Any

from payments.adapters.base import (
    PaymentCaptureResult,
    PaymentGatewayAdapter,
    PaymentIntentResult,
)


def _get_cybersource_credentials() -> tuple[str, str, str, str]:
    """Retrieve CyberSource credentials from SiteSettings or django.conf.settings."""
    try:
        from core.models import SiteSettings
        settings_inst = SiteSettings.objects.first()
        if settings_inst and settings_inst.cybersource_merchant_id:
            return (
                settings_inst.cybersource_merchant_id.strip(),
                settings_inst.cybersource_key_id.strip(),
                settings_inst.cybersource_secret_key.strip(),
                settings_inst.cybersource_run_environment.strip() or "apitest.cybersource.com",
            )
    except Exception:
        pass
    from django.conf import settings
    return (
        getattr(settings, "CYBERSOURCE_MERCHANT_ID", ""),
        getattr(settings, "CYBERSOURCE_KEY_ID", ""),
        getattr(settings, "CYBERSOURCE_SECRET_KEY", ""),
        getattr(settings, "CYBERSOURCE_RUN_ENVIRONMENT", "apitest.cybersource.com"),
    )


def _get_cybersource_config(merchant_id: str, key_id: str, secret_key: str, run_env: str) -> dict[str, str]:
    return {
        "authentication_type": "http_signature",
        "merchantid": merchant_id,
        "run_environment": run_env,
        "merchant_keyid": key_id,
        "merchant_secretkey": secret_key,
    }


class CyberSourceAdapter(PaymentGatewayAdapter):
    key = "cybersource"
    display_name = "CyberSource"
    is_async = True

    def create_payment_intent(
        self,
        *,
        amount: Decimal,
        currency: str,
        metadata: dict[str, Any] | None = None,
    ) -> PaymentIntentResult:
        metadata = metadata or {}
        return PaymentIntentResult(
            intent_id=f"cs_pi_{uuid.uuid4().hex[:16]}",
            requires_webhook=True,
            metadata=metadata,
        )

    def verify_webhook(self, *, payload: bytes, signature: str) -> dict[str, Any]:
        return json.loads(payload.decode())

    def capture(self, *, intent_id: str) -> PaymentCaptureResult:
        return PaymentCaptureResult(
            success=True,
            transaction_id=f"cs_tx_{intent_id}",
            metadata={"gateway": self.key},
        )

    def refund(self, *, transaction_id: str, amount: Decimal) -> PaymentCaptureResult:
        return PaymentCaptureResult(success=True, transaction_id=f"cs_refund_{transaction_id}")

    def fetch_payment_status(self, intent_id: str) -> bool:
        """
        Synchronously query CyberSource for the payment status.
        Returns True if AUTHORIZED, CAPTURED, or SETTLED.
        """
        merchant_id, key_id, secret_key, run_environment = _get_cybersource_credentials()
        config_obj = _get_cybersource_config(merchant_id, key_id, secret_key, run_environment)

        import CyberSource
        api_instance = CyberSource.TransactionDetailsApi(config_obj)
        try:
            response = api_instance.get_transaction(id=intent_id)
            resp_obj = response[0] if isinstance(response, tuple) else response
            if hasattr(resp_obj, "to_dict"):
                resp_dict = resp_obj.to_dict()
            else:
                resp_dict = resp_obj

            status = resp_dict.get("applicationInformation", {}).get("status", "")
            return status in ("AUTHORIZED", "CAPTURED", "SETTLED")
        except Exception:
            logging.exception("CyberSource TransactionDetailsApi failed for %s", intent_id)
            return False


class CyberSourceCardAdapter(CyberSourceAdapter):
    key = "cybersource_card"
    display_name = "Credit/Debit Card (CyberSource)"

    def create_payment_intent(
        self,
        *,
        amount: Decimal,
        currency: str,
        metadata: dict[str, Any] | None = None,
    ) -> PaymentIntentResult:
        metadata = metadata or {}
        metadata["payment_type"] = "card"

        merchant_id, key_id, secret_key, run_environment = _get_cybersource_credentials()
        config_obj = _get_cybersource_config(merchant_id, key_id, secret_key, run_environment)

        import CyberSource
        from django.conf import settings

        target_origin = getattr(
            settings,
            "CYBERSOURCE_TARGET_ORIGIN",
            os.environ.get("CYBERSOURCE_TARGET_ORIGIN", "http://localhost:8000"),
        )
        if target_origin == "*" or not target_origin.startswith("http"):
            target_origin = "http://localhost:8000"

        req = CyberSource.models.GenerateCaptureContextRequest(
            client_version="v2.0",
            target_origins=[target_origin],
            allowed_card_networks=["VISA", "MASTERCARD", "AMEX"],
        )

        api_instance = CyberSource.MicroformIntegrationApi(config_obj)
        try:
            req_dict = api_instance.api_client.sanitize_for_serialization(req)
            req_str = json.dumps(req_dict)
            response = api_instance.generate_capture_context(req_str)
            jwt_token = response[0] if isinstance(response, tuple) else response
            metadata["capture_context"] = jwt_token

            if "apitest.cybersource.com" in run_environment.lower():
                metadata["microform_script_url"] = "https://testflex.cybersource.com/cybersource/assets/microform/0.11/flex-microform.min.js"
            else:
                metadata["microform_script_url"] = "https://flex.cybersource.com/cybersource/assets/microform/0.11/flex-microform.min.js"

            intent_id = f"cs_pi_{uuid.uuid4().hex[:16]}"
            return PaymentIntentResult(
                intent_id=intent_id,
                requires_webhook=True,
                metadata=metadata,
            )
        except Exception as e:
            logging.exception("CyberSource Microform context generation failed")
            raise ValueError("Failed to generate CyberSource capture context") from e

    def authorize_with_token(self, token: str, order_id: str, amount: Decimal, currency: str) -> dict[str, Any]:
        merchant_id, key_id, secret_key, run_environment = _get_cybersource_credentials()
        config_obj = _get_cybersource_config(merchant_id, key_id, secret_key, run_environment)

        import CyberSource
        from orders.models import Order

        order = Order.objects.get(pk=order_id)

        client_reference_information = CyberSource.models.Ptsv2paymentsClientReferenceInformation(
            code=str(order.order_number)
        )
        processing_information = CyberSource.models.Ptsv2paymentsProcessingInformation(
            capture=False,
            commerce_indicator="internet",
        )
        token_information = CyberSource.models.Ptsv2paymentsTokenInformation(
            transient_token_jwt=token
        )
        amount_details = CyberSource.models.Ptsv2paymentsOrderInformationAmountDetails(
            total_amount=str(amount),
            currency=currency,
        )

        addr = order.delivery_address_snapshot or {}
        full_name = addr.get("name") or order.customer_display_name or "Unknown Customer"
        name_parts = full_name.split()
        first_name = name_parts[0] if name_parts else "Unknown"
        last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else "Unknown"

        mapped_state = addr.get("state") or "Unknown State"
        country_code = (addr.get("country") or "NZ").strip().upper()
        if len(country_code) != 2:
            country_code = "NZ"

        bill_to = CyberSource.models.Ptsv2paymentsOrderInformationBillTo(
            first_name=first_name,
            last_name=last_name,
            address1=addr.get("line1") or addr.get("street_address") or addr.get("address_line_1") or "123 Unknown St",
            locality=addr.get("city") or "Unknown City",
            administrative_area=mapped_state,
            postal_code=addr.get("pincode") or addr.get("postal_code") or "000000",
            country=country_code,
            email=addr.get("email") or "test@example.com",
            phone_number=addr.get("phone") or "0000000000",
        )

        order_information = CyberSource.models.Ptsv2paymentsOrderInformation(
            amount_details=amount_details,
            bill_to=bill_to,
        )

        request = CyberSource.models.CreatePaymentRequest(
            client_reference_information=client_reference_information,
            processing_information=processing_information,
            token_information=token_information,
            order_information=order_information,
        )

        api_instance = CyberSource.PaymentsApi(config_obj)
        try:
            req_dict = api_instance.api_client.sanitize_for_serialization(request)
            req_str = json.dumps(req_dict)
            response = api_instance.create_payment(req_str)
            resp_obj = response[0] if isinstance(response, tuple) else response

            if hasattr(resp_obj, "to_dict"):
                return resp_obj.to_dict()
            return resp_obj
        except Exception as e:
            logging.exception("CyberSource authorize_with_token failed")
            if hasattr(e, "body"):
                try:
                    return json.loads(e.body)
                except Exception:
                    pass
            return {"status": "SERVER_ERROR", "message": f"Internal error: {str(e)}"}
