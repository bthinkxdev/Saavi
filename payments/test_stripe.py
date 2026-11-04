"""Tests for the Stripe integration: reconciliation, webhook, return flow, access control."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.services import register_customer_email
from cart.models import Cart, CartItem
from catalog.models import Category, Product
from checkout.access import SESSION_KEY
from checkout.services import create_checkout_session, place_order
from core.models import Currency, SiteSettings
from core.services import get_site_settings
from orders.models import OrderStatus
from payments.adapters.stripe import (
    StripePaymentAdapter,
    from_stripe_amount,
    stripe_is_configured,
    to_stripe_amount,
    validate_stripe_keys,
)
from payments.models import PaymentStatus, PaymentTransaction
from payments.services import process_payment

WH_SECRET = "whsec_testsecret"
PUB, SEC = "pk_test_abc", "sk_test_abc"


def _stripe_signature(payload: bytes, secret: str = WH_SECRET) -> str:
    ts = int(time.time())
    digest = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={ts},v1={digest}"


def _intent(tx, *, status="succeeded", **overrides) -> dict:
    data = {
        "id": tx.external_intent_id,
        "object": "payment_intent",
        "status": status,
        "amount": to_stripe_amount(tx.amount, tx.currency.code),
        "amount_received": to_stripe_amount(tx.amount, tx.currency.code),
        "currency": tx.currency.code.lower(),
        "metadata": {"order_id": str(tx.order_id)},
        "client_secret": f"{tx.external_intent_id}_secret_x",
    }
    data.update(overrides)
    return data


@override_settings(STRIPE_PUBLIC_KEY=PUB, STRIPE_SECRET_KEY=SEC, STRIPE_WEBHOOK_SECRET=WH_SECRET)
class StripeBase(TestCase):
    def setUp(self) -> None:
        self.currency, _ = Currency.objects.get_or_create(
            code="INR",
            defaults={"symbol": "Rs", "exchange_rate_to_base": "1.00000000", "is_default": True},
        )
        self.profile = register_customer_email(
            email="stripe-test@example.com", password="testpass12345", name="Stripe Test"
        )
        category = Category.objects.create(name="Cat", slug="cat")
        self.product = Product.objects.create(
            name="Yarn", slug="yarn", sku="SKU-S-1", category=category,
            base_price="500.00", mrp="500.00", purchase_price="300.00", stock_quantity=100,
        )
        for target in (
            "delhivery.tasks.create_shipment_for_order.delay",
            "notifications.tasks.dispatch_order_confirmation_notification.delay",
            "notifications.tasks.dispatch_new_order_admin_notification.delay",
        ):
            patcher = patch(target)
            patcher.start()
            self.addCleanup(patcher.stop)

    def make_order(self, suffix="1"):
        cart = Cart.objects.create(customer_profile=self.profile, currency=self.currency)
        CartItem.objects.create(
            cart=cart, product=self.product, quantity=1, unit_price_at_add=self.product.base_price
        )
        session = create_checkout_session(cart=cart, customer_profile=self.profile)
        return place_order(
            checkout_session_id=session.pk,
            idempotency_key=f"stripe-order-{suffix}",
            gateway_key="stripe",
            customer_profile=self.profile,
        )

    def make_tx(self, order, intent_id="pi_test_1", status=PaymentStatus.PENDING):
        return PaymentTransaction.objects.create(
            order=order,
            gateway_key="stripe",
            amount=order.total_amount,
            currency=order.currency,
            status=status,
            external_intent_id=intent_id,
        )

    def own(self, order):
        session = self.client.session
        session[SESSION_KEY] = [order.pk]
        session.save()


class AmountTests(TestCase):
    def test_rounding_is_half_up_not_bankers(self):
        self.assertEqual(to_stripe_amount(Decimal("0.125"), "usd"), 13)
        self.assertEqual(to_stripe_amount(Decimal("0.135"), "usd"), 14)

    def test_zero_and_three_decimal_currencies(self):
        self.assertEqual(to_stripe_amount(Decimal("1000"), "JPY"), 1000)
        self.assertEqual(to_stripe_amount(Decimal("1.234"), "KWD"), 1230)
        self.assertEqual(from_stripe_amount(1230, "KWD"), Decimal("1.23"))
        self.assertEqual(from_stripe_amount(1050, "USD"), Decimal("10.5"))


class KeyValidationTests(TestCase):
    def test_valid_set(self):
        self.assertEqual(
            validate_stripe_keys(publishable_key=PUB, secret_key=SEC, webhook_secret=WH_SECRET), []
        )

    def test_mode_mismatch_and_bad_prefixes(self):
        problems = validate_stripe_keys(
            publishable_key="pk_live_x", secret_key="sk_test_x", webhook_secret="nope"
        )
        self.assertEqual(len(problems), 2)
        self.assertTrue(any("mode" in p for p in problems))

    @override_settings(STRIPE_PUBLIC_KEY=PUB, STRIPE_SECRET_KEY=SEC, STRIPE_WEBHOOK_SECRET="")
    def test_not_configured_without_webhook_secret(self):
        self.assertFalse(stripe_is_configured())

    @override_settings(STRIPE_PUBLIC_KEY=PUB, STRIPE_SECRET_KEY=SEC, STRIPE_WEBHOOK_SECRET=WH_SECRET)
    def test_configured(self):
        self.assertTrue(stripe_is_configured())


class WebhookTests(StripeBase):
    url = "/payments/webhooks/stripe/"

    def _post(self, event: dict, *, sign=True):
        body = json.dumps(event).encode()
        sig = _stripe_signature(body) if sign else "t=1,v1=bad"
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(
                self.url, data=body, content_type="application/json", HTTP_STRIPE_SIGNATURE=sig
            )

    def _event(self, type_, obj):
        return {"id": "evt_1", "type": type_, "data": {"object": obj}}

    def test_bad_signature_rejected(self):
        order = self.make_order()
        tx = self.make_tx(order)
        r = self._post(self._event("payment_intent.succeeded", _intent(tx)), sign=False)
        self.assertEqual(r.status_code, 400)
        order.refresh_from_db()
        self.assertEqual(order.order_status, OrderStatus.CHECKOUT_PENDING)

    def test_succeeded_confirms_order_and_is_idempotent(self):
        order = self.make_order()
        tx = self.make_tx(order)
        for _ in range(2):
            r = self._post(self._event("payment_intent.succeeded", _intent(tx)))
            self.assertEqual(r.status_code, 200)
        order.refresh_from_db()
        tx.refresh_from_db()
        self.assertEqual(order.order_status, OrderStatus.CONFIRMED)
        self.assertEqual(tx.status, PaymentStatus.SUCCESS)
        self.assertEqual(tx.external_transaction_id, "pi_test_1")

    def test_amount_mismatch_is_not_confirmed(self):
        order = self.make_order()
        tx = self.make_tx(order)
        self._post(self._event("payment_intent.succeeded", _intent(tx, amount_received=1, amount=1)))
        order.refresh_from_db()
        tx.refresh_from_db()
        self.assertEqual(order.order_status, OrderStatus.CHECKOUT_PENDING)
        self.assertEqual(tx.status, PaymentStatus.PENDING)
        self.assertIn("amount", tx.metadata["stripe_anomaly"])

    def test_currency_mismatch_is_not_confirmed(self):
        order = self.make_order()
        tx = self.make_tx(order)
        self._post(self._event("payment_intent.succeeded", _intent(tx, currency="usd")))
        order.refresh_from_db()
        self.assertEqual(order.order_status, OrderStatus.CHECKOUT_PENDING)

    def test_unmatched_intent_is_acknowledged_not_confirmed(self):
        order = self.make_order()
        tx = self.make_tx(order)
        r = self._post(self._event("payment_intent.succeeded", _intent(tx, id="pi_other")))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "unmatched")
        order.refresh_from_db()
        self.assertEqual(order.order_status, OrderStatus.CHECKOUT_PENDING)

    def test_payment_failed_keeps_transaction_retryable(self):
        order = self.make_order()
        tx = self.make_tx(order)
        err = {"code": "card_declined", "decline_code": "insufficient_funds", "message": "no"}
        self._post(
            self._event(
                "payment_intent.payment_failed",
                _intent(tx, status="requires_payment_method", last_payment_error=err),
            )
        )
        tx.refresh_from_db()
        self.assertEqual(tx.status, PaymentStatus.PENDING)
        self.assertEqual(tx.metadata["last_payment_error"]["code"], "card_declined")
        self._post(self._event("payment_intent.succeeded", _intent(tx)))
        tx.refresh_from_db()
        self.assertEqual(tx.status, PaymentStatus.SUCCESS)

    def test_canceled_marks_failed(self):
        order = self.make_order()
        tx = self.make_tx(order)
        self._post(self._event("payment_intent.canceled", _intent(tx, status="canceled")))
        tx.refresh_from_db()
        self.assertEqual(tx.status, PaymentStatus.FAILED)

    def test_late_success_on_superseded_failed_transaction_still_settles(self):
        order = self.make_order()
        tx = self.make_tx(order, status=PaymentStatus.FAILED)
        self._post(self._event("payment_intent.succeeded", _intent(tx)))
        order.refresh_from_db()
        self.assertEqual(order.order_status, OrderStatus.CONFIRMED)

    def test_full_refund_marks_transaction_and_order_refunded(self):
        order = self.make_order()
        tx = self.make_tx(order)
        self._post(self._event("payment_intent.succeeded", _intent(tx)))
        amount = to_stripe_amount(tx.amount, "INR")
        self._post(
            self._event(
                "charge.refunded",
                {
                    "id": "ch_1",
                    "payment_intent": tx.external_intent_id,
                    "amount_refunded": amount,
                    "refunded": True,
                },
            )
        )
        order.refresh_from_db()
        tx.refresh_from_db()
        self.assertEqual(tx.status, PaymentStatus.REFUNDED)
        self.assertEqual(order.order_status, OrderStatus.REFUNDED)

    def test_partial_refund_only_recorded(self):
        order = self.make_order()
        tx = self.make_tx(order)
        self._post(self._event("payment_intent.succeeded", _intent(tx)))
        self._post(
            self._event(
                "charge.refunded",
                {
                    "id": "ch_1",
                    "payment_intent": tx.external_intent_id,
                    "amount_refunded": 100,
                    "refunded": False,
                },
            )
        )
        order.refresh_from_db()
        tx.refresh_from_db()
        self.assertEqual(tx.status, PaymentStatus.SUCCESS)
        self.assertEqual(Decimal(tx.metadata["amount_refunded"]), Decimal("1"))
        self.assertEqual(order.order_status, OrderStatus.CONFIRMED)

    def test_unrelated_event_ignored(self):
        r = self._post(self._event("customer.created", {}))
        self.assertEqual(r.json()["status"], "ignored")


class ReturnFlowAndAccessTests(StripeBase):
    def confirm_url(self, order):
        return reverse("checkout:confirmation", kwargs={"order_id": order.pk})

    def pay_url(self, order):
        return reverse("checkout:stripe-pay", kwargs={"order_id": order.pk})

    @patch("payments.stripe_service.retrieve_payment_intent")
    def test_forged_redirect_params_do_not_confirm(self, retrieve):
        order = self.make_order()
        tx = self.make_tx(order)
        self.own(order)
        retrieve.return_value = _intent(tx, status="requires_payment_method")
        r = self.client.get(
            self.confirm_url(order)
            + f"?payment_intent={tx.external_intent_id}&redirect_status=succeeded"
        )
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.context["payment_pending"])
        order.refresh_from_db()
        self.assertEqual(order.order_status, OrderStatus.CHECKOUT_PENDING)

    @patch("payments.stripe_service.retrieve_payment_intent")
    def test_return_confirms_when_stripe_says_succeeded(self, retrieve):
        order = self.make_order()
        tx = self.make_tx(order)
        self.own(order)
        retrieve.return_value = _intent(tx)
        with self.captureOnCommitCallbacks(execute=True):
            r = self.client.get(self.confirm_url(order) + f"?payment_intent={tx.external_intent_id}")
        self.assertFalse(r.context["payment_pending"])
        order.refresh_from_db()
        self.assertEqual(order.order_status, OrderStatus.CONFIRMED)

    def test_confirmation_requires_ownership(self):
        order = self.make_order()
        self.make_tx(order)
        self.assertEqual(self.client.get(self.confirm_url(order)).status_code, 404)

    def test_signed_in_owner_has_access(self):
        order = self.make_order()
        self.make_tx(order)
        self.client.force_login(self.profile.user)
        with patch("payments.stripe_service.retrieve_payment_intent", side_effect=ValueError):
            self.assertEqual(self.client.get(self.confirm_url(order)).status_code, 200)

    def test_pay_page_requires_ownership(self):
        order = self.make_order()
        self.make_tx(order)
        self.assertEqual(self.client.get(self.pay_url(order)).status_code, 404)

    @patch("payments.adapters.stripe.retrieve_payment_intent")
    def test_pay_page_fetches_client_secret_from_stripe(self, retrieve):
        order = self.make_order()
        tx = self.make_tx(order)
        self.own(order)
        retrieve.return_value = _intent(tx, status="requires_payment_method")
        r = self.client.get(self.pay_url(order))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, f"{tx.external_intent_id}_secret_x")
        self.assertEqual(r.context["error_code"], "")

    @patch("payments.adapters.stripe.retrieve_payment_intent", side_effect=ValueError("down"))
    def test_pay_page_distinguishes_unavailable_from_unconfigured(self, _):
        order = self.make_order()
        self.make_tx(order)
        self.own(order)
        self.assertEqual(self.client.get(self.pay_url(order)).context["error_code"], "unavailable")


class ProcessPaymentTests(StripeBase):
    @patch("payments.adapters.stripe.stripe.PaymentIntent.cancel")
    @patch("payments.adapters.stripe.stripe.PaymentIntent.create")
    def test_intent_is_idempotent_secretless_and_supersedes_old(self, create, cancel):
        create.side_effect = lambda **kw: type(
            "I",
            (),
            {"id": f"pi_{kw['metadata']['payment_transaction_id']}", "client_secret": "pi_secret_zzz"},
        )()
        order = self.make_order()
        first = process_payment(order=order, gateway_key="stripe", payment_data={})
        second = process_payment(order=order, gateway_key="stripe", payment_data={})

        kwargs = create.call_args_list[0].kwargs
        self.assertEqual(kwargs["idempotency_key"], f"sarocchi-pi-tx-{first.pk}")
        self.assertEqual(kwargs["metadata"]["payment_transaction_id"], str(first.pk))
        self.assertNotIn("pi_secret_zzz", json.dumps(first.metadata))
        self.assertNotIn("pi_secret_zzz", json.dumps(second.metadata))

        first.refresh_from_db()
        self.assertEqual(first.status, PaymentStatus.FAILED)
        cancel.assert_called_once()
        self.assertEqual(cancel.call_args.args[0], first.external_intent_id)


class RefundTests(TestCase):
    def test_zero_amount_and_missing_key_rejected_before_any_api_call(self):
        adapter = StripePaymentAdapter()
        with self.assertRaises(ValueError):
            adapter.refund(transaction_id="pi_1", amount=Decimal("0"), idempotency_key="k")
        with self.assertRaises(ValueError):
            adapter.refund(transaction_id="pi_1", amount=Decimal("5"))


class SettingsFormTests(TestCase):
    def _form(self, **data):
        from dashboard.forms import SiteSettingsForm

        base = {
            "site_name": "S",
            "stripe_publishable_key": PUB,
            "stripe_secret_key": "",
            "stripe_webhook_secret": "",
        }
        base.update(data)
        return SiteSettingsForm(base, instance=get_site_settings())

    def test_secrets_not_rendered_and_blank_keeps_stored(self):
        ss = SiteSettings.objects.get_or_create(pk=1)[0]
        ss.stripe_secret_key, ss.stripe_webhook_secret = SEC, WH_SECRET
        ss.save()
        form = self._form()
        self.assertNotIn(SEC, str(form["stripe_secret_key"]))
        self.assertNotIn(WH_SECRET, str(form["stripe_webhook_secret"]))
        form.is_valid()
        self.assertEqual(form.cleaned_data.get("stripe_secret_key"), SEC)
        self.assertEqual(form.cleaned_data.get("stripe_webhook_secret"), WH_SECRET)

    def test_mode_mismatch_rejected(self):
        form = self._form(stripe_secret_key="sk_live_x", stripe_webhook_secret=WH_SECRET)
        self.assertFalse(form.is_valid())
        self.assertTrue(any("mode" in e for e in form.non_field_errors()))
