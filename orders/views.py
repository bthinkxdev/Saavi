"""HTTP views for the orders app."""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

from orders.selectors import get_order_tracking_view, get_customer_orders


@login_required
@require_GET
def order_tracking_view(request: HttpRequest, order_id: int) -> HttpResponse:
    """Customer order tracking page with status timeline."""
    profile = request.user.customer_profile
    tracking = get_order_tracking_view(order_id=order_id, customer_profile=profile)
    if tracking is None:
        raise Http404("Order not found.")
    return render(
        request,
        "orders/tracking.html",
        {
            "tracking": tracking,
            "order": tracking.order,
            "status_history": tracking.status_history,
        },
    )


@login_required
@require_GET
def order_list_view(request: HttpRequest) -> HttpResponse:
    """Customer order history page."""
    profile = request.user.customer_profile
    page = int(request.GET.get("page", 1))
    orders_page = get_customer_orders(customer_profile=profile, page=page, page_size=20)
    
    return render(
        request,
        "orders/order_list.html",
        {
            "orders": orders_page["results"],
            "pagination": {
                "page": orders_page["page"],
                "total_count": orders_page["total_count"],
                "total_pages": orders_page["total_pages"],
                "has_next": orders_page["has_next"],
                "has_previous": orders_page["has_previous"],
            }
        },
    )


@login_required
@require_GET
def order_detail_view(request: HttpRequest, order_id: int) -> HttpResponse:
    """Customer order details page."""
    profile = request.user.customer_profile
    tracking = get_order_tracking_view(order_id=order_id, customer_profile=profile)
    if tracking is None:
        raise Http404("Order not found.")
    
    return render(
        request,
        "orders/order_detail.html",
        {
            "order": tracking.order,
            "items": tracking.order.items.all(),
            "tracking": tracking,
            "timeline": _build_timeline(tracking.order),
        },
    )


_TIMELINE_STEPS = [
    ("placed", "Order Placed", None),
    ("confirmed", "Order Confirmed", {"confirmed", "processing", "ready_to_ship", "placed_cod"}),
    ("shipped", "Shipped", {"shipped", "picked_up", "in_transit", "out_for_delivery"}),
    ("delivered", "Delivered", {"delivered"}),
]
_STATUS_RANK = {
    "checkout_pending": 0, "placed_cod": 1, "confirmed": 1, "processing": 1, "ready_to_ship": 1,
    "shipped": 2, "picked_up": 2, "in_transit": 2, "out_for_delivery": 2, "delivered": 3,
}


def _build_timeline(order) -> list[dict]:
    """Placed → Confirmed → Shipped → Delivered with the time each step was reached."""
    history = list(order.status_history.all().order_by("changed_at"))
    reached = _STATUS_RANK.get(order.order_status, -1)
    steps = []
    for idx, (key, label, statuses) in enumerate(_TIMELINE_STEPS):
        when = order.created_at if statuses is None else next(
            (h.changed_at for h in history if h.to_status in statuses), None
        )
        steps.append({"key": key, "label": label, "done": idx <= reached, "when": when})
    return steps


@login_required
@require_POST
def order_reorder_view(request: HttpRequest, order_id: int) -> HttpResponse:
    """Add every still-available item of a past order back into the cart."""
    from django.contrib import messages
    from django.shortcuts import redirect

    from cart.services import add_to_cart, get_or_create_cart

    profile = request.user.customer_profile
    tracking = get_order_tracking_view(order_id=order_id, customer_profile=profile)
    if tracking is None:
        raise Http404("Order not found.")
    cart = get_or_create_cart(request=request)
    added = skipped = 0
    for item in tracking.order.items.select_related("product", "variant"):
        try:
            add_to_cart(cart=cart, product=item.product, variant=item.variant, quantity=item.quantity, overwrite=True)
            added += 1
        except Exception:  # out of stock / inactive product
            skipped += 1
    if added:
        messages.success(request, "Items added to your cart.")
    if skipped:
        messages.error(request, f"{skipped} item(s) are no longer available.")
    return redirect("cart:page")
