"""Write operations and business rules for the orders app."""

from __future__ import annotations

import random
import string
import uuid
from typing import Optional

from django.contrib.auth.models import User
from django.db import transaction

from orders.exceptions import InvalidOrderStatusTransitionError
from orders.models import Order, OrderStatus, OrderStatusHistory
from orders.signals import order_status_changed

#Admin-manual transitions only. The webhook (delhivery.views.delhivery_webhook)
#always calls transition_order_status with force=True, so it is never limited by
#this map — PICKED_UP / IN_TRANSIT / OUT_FOR_DELIVERY / DELIVERED are reachable only
#through the webhook, never listed here, so an admin can never select them from the
#dashboard's transition dropdown (which is built from this same map).
def get_allowed_status_transitions() -> dict[str, set[str]]:
    transitions = {
        OrderStatus.CHECKOUT_PENDING: {OrderStatus.CONFIRMED, OrderStatus.CANCELLED},
        OrderStatus.PLACED_COD: {OrderStatus.CONFIRMED, OrderStatus.CANCELLED},
        OrderStatus.CONFIRMED: {OrderStatus.READY_TO_SHIP, OrderStatus.PROCESSING, OrderStatus.CANCELLED},
        
        #delhivery flow
        OrderStatus.READY_TO_SHIP: {OrderStatus.CANCELLED},
        OrderStatus.PICKED_UP: set(),
        OrderStatus.IN_TRANSIT: set(),
        OrderStatus.OUT_FOR_DELIVERY: set(),
        
        #generic flow
        OrderStatus.PROCESSING: {OrderStatus.SHIPPED, OrderStatus.CANCELLED},
        OrderStatus.SHIPPED: {OrderStatus.DELIVERED, OrderStatus.CANCELLED},
        
        #shared
        OrderStatus.DELIVERED: {OrderStatus.REFUNDED},
        OrderStatus.CANCELLED: {OrderStatus.REFUNDED},
        OrderStatus.REFUNDED: set(),
    }
    
    try:
        from core.models import SiteSettings
        settings = SiteSettings.objects.first()
        enable_delhivery = settings.enable_delhivery if settings else True
    except Exception:
        enable_delhivery = True
        
    if enable_delhivery:
        #hide generic manual transitions from UI if delhivery is active
        transitions[OrderStatus.CONFIRMED].discard(OrderStatus.PROCESSING)
    else:
        #hide delhivery manual transitions from UI if generic is active
        transitions[OrderStatus.CONFIRMED].discard(OrderStatus.READY_TO_SHIP)
        #fallback manual transitions if needed
        transitions[OrderStatus.READY_TO_SHIP].update({OrderStatus.PICKED_UP, OrderStatus.IN_TRANSIT})
        transitions[OrderStatus.PICKED_UP].update({OrderStatus.IN_TRANSIT})
        transitions[OrderStatus.IN_TRANSIT].update({OrderStatus.OUT_FOR_DELIVERY, OrderStatus.DELIVERED})
        transitions[OrderStatus.OUT_FOR_DELIVERY].add(OrderStatus.DELIVERED)
        
    return transitions

#Fulfillment rank used by the Delhivery webhook to reject out-of-order/backward scan
#events (e.g. a stale "in transit" push arriving after "delivered" already landed).
#CANCELLED/REFUNDED are absorbing states and intentionally excluded — a courier
#RTO/cancel can legitimately happen from any rank.
ORDER_STATUS_RANK: dict[str, int] = {
    OrderStatus.CONFIRMED: 1,
    OrderStatus.PROCESSING: 2,
    OrderStatus.READY_TO_SHIP: 2,
    OrderStatus.PICKED_UP: 3,
    OrderStatus.SHIPPED: 4,
    OrderStatus.IN_TRANSIT: 4,
    OrderStatus.OUT_FOR_DELIVERY: 5,
    OrderStatus.DELIVERED: 6,
}

#Statuses that represent a real, uncancelled sale — for revenue/order-count
#reporting (reports.services, reports.selectors, dashboard.selectors). Deliberately
#an include-list, not an exclude-list: CHECKOUT_PENDING/PLACED_COD haven't converted
#to a sale yet (nothing paid or confirmed), CANCELLED/REFUNDED had the sale reversed.
#An include-list also means a future new status defaults to NOT counting as revenue
#until someone deliberately adds it here, rather than silently counting by default.
REVENUE_ORDER_STATUSES: frozenset[str] = frozenset(ORDER_STATUS_RANK.keys())


from django.db.models import Max, IntegerField
from django.db.models.functions import Cast, Substr

def generate_order_number() -> str:
    """Return a unique sequential order number starting from #3000."""
    max_num = Order.objects.filter(order_number__startswith="#").annotate(
        num_val=Cast(Substr('order_number', 2), output_field=IntegerField())
    ).aggregate(Max('num_val'))['num_val__max']

    if max_num and max_num >= 3000:
        next_num = max_num + 1
    else:
        next_num = 3000

    order_number = f"#{next_num}"
    
    while Order.objects.filter(order_number=order_number).exists():
        next_num += 1
        order_number = f"#{next_num}"
        
    return order_number


@transaction.atomic
def transition_order_status(
    *,
    order: Order,
    new_status: str,
    actor: Optional[User] = None,
    note: str = "",
    send_notifications: bool = True,
    force: bool = False,
) -> Order:
    """
    Validate and apply an order status transition.

    Writes ``OrderStatusHistory`` atomically and emits ``order_status_changed``.
    Notifications listen to the signal — this service never calls them directly.
    """
    old_status = order.order_status
    if new_status == old_status:
        return order

    if not force:
        allowed = get_allowed_status_transitions().get(old_status, set())
        if new_status not in allowed:
            raise InvalidOrderStatusTransitionError(
                f"Cannot transition order from {old_status} to {new_status}."
            )

    order.order_status = new_status
    order.save(update_fields=["order_status", "updated_at"])

    OrderStatusHistory.objects.create(
        order=order,
        from_status=old_status,
        to_status=new_status,
        changed_by=actor,
        note=note,
    )

    order_status_changed.send(
        sender=Order,
        order=order,
        old_status=old_status,
        new_status=new_status,
        send_notifications=send_notifications,
    )

    if new_status == OrderStatus.CONFIRMED:
        from orders.plugins import order_confirmed_registry
        transaction.on_commit(lambda: order_confirmed_registry.execute_plugins(order))

        #COD orders already alerted the admin at creation (PLACED_COD) — only notify
        #here the first time an order becomes real, i.e. an online payment succeeding
        #(or an admin manually confirming a still-unpaid CHECKOUT_PENDING order).
        if old_status == OrderStatus.CHECKOUT_PENDING:
            from catalog.services import adjust_stock
            for item in order.items.all():
                target = item.variant if item.variant else item.product
                adjust_stock(target=target, delta=-item.quantity, reason=f"payment_success:{order.order_number}")

            from notifications.tasks import dispatch_new_order_admin_notification
            transaction.on_commit(lambda: dispatch_new_order_admin_notification.delay(order_id=order.pk))

    tx = order.payment_transactions.last()
    if tx:
        from payments.models import PaymentStatus
        if new_status == OrderStatus.DELIVERED:
            tx.status = PaymentStatus.SUCCESS
            tx.save(update_fields=["status", "updated_at"])
        elif new_status == OrderStatus.CANCELLED:
            tx.status = PaymentStatus.CANCELLED
            tx.save(update_fields=["status", "updated_at"])
        elif new_status == OrderStatus.REFUNDED:
            tx.status = PaymentStatus.REFUNDED
            tx.save(update_fields=["status", "updated_at"])

    return order
