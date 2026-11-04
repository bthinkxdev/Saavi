"""Tests for the dashboard app.

Access control, CRUD flows, and report views are exercised here. Add cases
under a tests/ package as coverage grows (see scripts/scaffold_apps.py).
"""

from __future__ import annotations

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from accounts.services import register_customer_email
from cart.models import Cart, CartItem
from catalog.models import Category, Product
from checkout.services import create_checkout_session, place_order
from core.models import Currency
from orders.models import OrderStatus
from payments.models import PaymentStatus, PaymentTransaction
from payments.services import confirm_payment_success


class OrderListTabsTests(TestCase):
    """The Orders list splits real orders from CHECKOUT_PENDING abandoned
    checkouts into two tabs (see dashboard/views/orders.py::order_list)."""

    def setUp(self) -> None:
        self.staff_user = User.objects.create_superuser(
            username="dash-admin", email="dash-admin@example.com", password="testpass12345"
        )
        self.client.force_login(self.staff_user)

        self.currency, _ = Currency.objects.get_or_create(
            code="INR",
            defaults={"symbol": "₹", "exchange_rate_to_base": "1.00000000", "is_default": True},
        )
        self.profile = register_customer_email(
            email="dash-order-test@example.com", password="testpass12345", name="Dash Order Test"
        )
        category = Category.objects.create(name="Test Category", slug="dash-test-category")
        self.product = Product.objects.create(
            name="Test Yarn",
            slug="dash-test-yarn",
            sku="SKU-DASH-1",
            category=category,
            base_price="500.00",
            mrp="500.00",
            purchase_price="300.00",
            stock_quantity=100,
        )

        self.confirmed_order = self._place_order("confirmed")
        tx = PaymentTransaction.objects.create(
            order=self.confirmed_order,
            gateway_key="razorpay_upi",
            amount=self.confirmed_order.total_amount,
            currency=self.confirmed_order.currency,
            status=PaymentStatus.PENDING,
            external_intent_id="order_dash_confirmed_1",
        )
        confirm_payment_success(payment_transaction=tx, external_transaction_id="pay_dash_confirmed_1")

        self.abandoned_order = self._place_order("abandoned")
        self.assertEqual(self.abandoned_order.order_status, OrderStatus.CHECKOUT_PENDING)

    def _place_order(self, suffix: str):
        cart = Cart.objects.create(customer_profile=self.profile, currency=self.currency)
        CartItem.objects.create(
            cart=cart, product=self.product, quantity=1, unit_price_at_add=self.product.base_price
        )
        session = create_checkout_session(cart=cart, customer_profile=self.profile)
        return place_order(
            checkout_session_id=session.pk,
            idempotency_key=f"dash-order-test-{suffix}",
            gateway_key="razorpay_upi",
            customer_profile=self.profile,
        )

    def test_orders_tab_excludes_abandoned_checkouts(self):
        response = self.client.get(reverse("dashboard:order-list"))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertContains(response, self.confirmed_order.order_number)
        self.assertNotContains(response, self.abandoned_order.order_number)
        self.assertIn("Abandoned Checkouts", content)
        self.assertIn(">1<", content)  # abandoned_count badge
        self.assertNotIn("Payment Pending", content)  # excluded from status dropdown + rows

    def test_abandoned_tab_shows_only_abandoned_checkouts(self):
        response = self.client.get(reverse("dashboard:order-list") + "?view=abandoned")
        self.assertEqual(response.status_code, 200)

        self.assertContains(response, self.abandoned_order.order_number)
        self.assertNotContains(response, self.confirmed_order.order_number)
        # status dropdown is hidden entirely on this tab
        self.assertNotContains(response, "All order statuses")

    def test_search_filter_works_within_abandoned_tab(self):
        response = self.client.get(
            reverse("dashboard:order-list") + f"?view=abandoned&q={self.abandoned_order.order_number}"
        )
        self.assertContains(response, self.abandoned_order.order_number)

        response = self.client.get(reverse("dashboard:order-list") + "?view=abandoned&q=NO_SUCH_ORDER")
        self.assertNotContains(response, self.abandoned_order.order_number)
