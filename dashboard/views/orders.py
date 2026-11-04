"""Order management: filterable list, detail, and guarded status transitions."""

from __future__ import annotations

from django.contrib import messages
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from dashboard.access import dashboard_required
from orders.exceptions import InvalidOrderStatusTransitionError
from orders.models import Order, OrderStatus
from orders.services import get_allowed_status_transitions, transition_order_status

_STATUS_LABELS = dict(OrderStatus.choices)


@dashboard_required
@require_http_methods(["GET"])
def order_list(request: HttpRequest) -> HttpResponse:
    """Paginated, status-filterable, searchable order list.

    Split into two tabs: "Orders" (everything past checkout) and "Abandoned
    Checkouts" (CHECKOUT_PENDING — reached payment but never completed it).
    Both are real Order rows by design (see orders.services.place_order), so
    without this split abandoned checkouts would otherwise clutter the main
    list by default.
    """
    view = request.GET.get("view", "orders").strip()
    if view not in ("orders", "abandoned"):
        view = "orders"

    qs = Order.objects.select_related("customer_profile__user", "currency").order_by("-created_at")

    if view == "abandoned":
        qs = qs.filter(order_status=OrderStatus.CHECKOUT_PENDING)
    else:
        qs = qs.exclude(order_status=OrderStatus.CHECKOUT_PENDING)

    status = request.GET.get("status", "").strip()
    if status and view == "orders":
        qs = qs.filter(order_status=status)
        
    customer_id = request.GET.get("customer", "").strip()
    if customer_id:
        qs = qs.filter(customer_profile_id=customer_id)

    from django.db.models import Q
    query = request.GET.get("q", "").strip()
    if query:
        qs = qs.filter(
            Q(order_number__icontains=query) |
            Q(customer_profile__user__first_name__icontains=query) |
            Q(customer_profile__user__last_name__icontains=query) |
            Q(customer_profile__phone__icontains=query)
        )

    from payments.models import PaymentStatus
    payment_status = request.GET.get("payment_status", "").strip()
    if payment_status:
        qs = qs.filter(payment_transactions__status=payment_status).distinct()

    paginator = Paginator(qs, 25)
    page_obj = paginator.get_page(request.GET.get("page"))

    params = request.GET.copy()
    params.pop("page", None)

    def _clear_url(param: str) -> str:
        p = request.GET.copy()
        p.pop("page", None)
        p.pop(param, None)
        return f"{request.path}?{p.urlencode()}" if p else request.path

    active_filters = []
    if status and view == "orders":
        active_filters.append({"label": _STATUS_LABELS.get(status, status), "clear_url": _clear_url("status")})
    if payment_status:
        active_filters.append({
            "label": f"Payment: {dict(PaymentStatus.choices).get(payment_status, payment_status)}",
            "clear_url": _clear_url("payment_status"),
        })
    if customer_id:
        active_filters.append({"label": f"Customer ID: {customer_id}", "clear_url": _clear_url("customer")})
    if query:
        active_filters.append({"label": f'Search: "{query}"', "clear_url": _clear_url("q")})

    abandoned_count = Order.objects.filter(order_status=OrderStatus.CHECKOUT_PENDING).count()
    from core.services import get_site_settings
    site_settings = get_site_settings()
    PRD_ORDER_STATUSES = [
        OrderStatus.PLACED_COD,
        OrderStatus.CONFIRMED,
        OrderStatus.PROCESSING,
        OrderStatus.SHIPPED,
        OrderStatus.DELIVERED,
        OrderStatus.CANCELLED,
        OrderStatus.REFUNDED,
    ]
    if not getattr(site_settings, "enable_cod", True):
        PRD_ORDER_STATUSES.remove(OrderStatus.PLACED_COD)

    orderable_statuses = [
        (value, _STATUS_LABELS[value]) for value in PRD_ORDER_STATUSES if value in _STATUS_LABELS
    ]

    context = {
        "nav_section": "orders",
        "page_title": "Orders",
        "page_obj": page_obj,
        "objects": page_obj.object_list,
        "statuses": orderable_statuses,
        "payment_statuses": PaymentStatus.choices,
        "current_status": status,
        "current_payment_status": payment_status,
        "search_query": query,
        "querystring": params.urlencode(),
        "active_filters": active_filters,
        "current_view": view,
        "abandoned_count": abandoned_count,
    }
    return render(request, "dashboard/orders/list.html", context)


@dashboard_required
@require_http_methods(["GET"])
def order_detail(request: HttpRequest, pk: int) -> HttpResponse:
    """Order detail with line items, status history, POD and payments."""
    order = get_object_or_404(
        Order.objects.select_related("customer_profile__user", "currency"), pk=pk
    )
    items = order.items.select_related("product", "variant").all()
    history = order.status_history.select_related("changed_by").all()
    payments = order.payment_transactions.select_related("currency").all()
    pod = getattr(order, "proof_of_delivery", None)

    #only the actually-valid next statuses — CONFIRMED is the sole trigger for AWB
    #creation, so an admin must never be able to pick an arbitrary status here.
    next_statuses = get_allowed_status_transitions().get(order.order_status, set())
    status_priority = {
        OrderStatus.CONFIRMED: 1,
        OrderStatus.PROCESSING: 2,
        OrderStatus.READY_TO_SHIP: 2,
        OrderStatus.SHIPPED: 3,
        OrderStatus.PICKED_UP: 3,
        OrderStatus.IN_TRANSIT: 4,
        OrderStatus.OUT_FOR_DELIVERY: 5,
        OrderStatus.DELIVERED: 6,
        OrderStatus.REFUNDED: 8,
        OrderStatus.CANCELLED: 9,
    }
    sorted_next_statuses = sorted(
        next_statuses, key=lambda s: status_priority.get(s, 50)
    )
    allowed_choices = [(value, _STATUS_LABELS[value]) for value in sorted_next_statuses if value in _STATUS_LABELS]
    from payments.models import PaymentStatus
    payment_statuses = PaymentStatus.choices

    from core.models import SiteSettings
    settings = SiteSettings.objects.first()
    enable_delhivery = settings.enable_delhivery if settings else True
    
    context = {
        "nav_section": "orders",
        "page_title": f"Order {order.order_number}",
        "order": order,
        "items": items,
        "history": history,
        "payments": payments,
        "pod": pod,
        "allowed_choices": allowed_choices,
        "payment_statuses": payment_statuses,
        "ENABLE_DELHIVERY": enable_delhivery,
    }
    return render(request, "dashboard/orders/detail.html", context)


@dashboard_required
@require_POST
def order_transition(request: HttpRequest, pk: int) -> HttpResponse:
    """Apply a status transition through the orders service state machine."""
    order = get_object_or_404(Order, pk=pk)
    new_status = request.POST.get("new_status", "")
    note = request.POST.get("note", "")
    try:
        transition_order_status(
            order=order, new_status=new_status, actor=request.user, note=note, force=False
        )
        messages.success(
            request, f"Order moved to {dict(OrderStatus.choices).get(new_status, new_status)}."
        )
    except InvalidOrderStatusTransitionError as exc:
        messages.error(request, str(exc))
    return redirect("dashboard:order-detail", pk=pk)


@dashboard_required
@require_POST
def order_payment_transition(request: HttpRequest, pk: int) -> HttpResponse:
    """Manually update the payment status of the latest payment transaction."""
    from payments.models import PaymentStatus
    
    order = get_object_or_404(Order, pk=pk)
    new_status = request.POST.get("new_status", "")
    
    # get the latest payment transaction to update
    tx = order.payment_transactions.last()
    
    if tx and new_status in dict(PaymentStatus.choices):
        if new_status == PaymentStatus.SUCCESS:
            from payments.services import confirm_payment_success
            confirm_payment_success(payment_transaction=tx)
            messages.success(request, f"Payment marked as {dict(PaymentStatus.choices).get(new_status)}.")
        elif new_status == PaymentStatus.FAILED:
            from payments.services import confirm_payment_failed
            confirm_payment_failed(payment_transaction=tx)
            messages.success(request, f"Payment marked as {dict(PaymentStatus.choices).get(new_status)}.")
        else:
            tx.status = new_status
            tx.save(update_fields=["status", "updated_at"])
            messages.success(request, f"Payment marked as {dict(PaymentStatus.choices).get(new_status)}.")
    elif not tx:
        messages.error(request, "Could not update payment status: No payment records found.")
        
    return redirect("dashboard:order-detail", pk=pk)


@dashboard_required
@require_http_methods(["GET"])
def order_invoice_detail(request: HttpRequest, pk: int) -> HttpResponse:
    """Render the HTML invoice for an order."""
    from core.models import SiteSettings
    from orders.services import REVENUE_ORDER_STATUSES
    from django.http import HttpResponse

    order = get_object_or_404(
        Order.objects.select_related("customer_profile__user", "currency"), pk=pk
    )
    
    if order.order_status not in REVENUE_ORDER_STATUSES:
        from django.contrib import messages
        from django.shortcuts import redirect
        messages.error(request, f"Invoice is not yet available for order {order.order_number} because it is not confirmed.")
        return redirect(request.META.get("HTTP_REFERER", "dashboard:order-list"))
    
    context = {
        "order": order,
        "site_settings": SiteSettings.objects.first(),
    }
    return render(request, "shared/order_invoice.html", context)


@dashboard_required
@require_http_methods(["POST"])
def order_bulk_invoice_detail(request: HttpRequest) -> HttpResponse:
    """Render the HTML bulk invoice for selected orders."""
    from core.models import SiteSettings
    
    order_ids = request.POST.getlist("order_ids")
    if not order_ids:
        messages.error(request, "No orders selected for printing.")
        return redirect("dashboard:order-list")
        
    from orders.services import REVENUE_ORDER_STATUSES

    orders_qs = Order.objects.select_related(
        "customer_profile__user", "currency"
    ).filter(pk__in=order_ids, order_status__in=REVENUE_ORDER_STATUSES).order_by("-created_at")
    
    if not orders_qs.exists():
        messages.error(request, "None of the selected orders are confirmed yet.")
        return redirect("dashboard:order-list")
    
    context = {
        "orders": orders_qs,
        "site_settings": SiteSettings.objects.first(),
    }
    return render(request, "shared/order_bulk_invoice.html", context)

@dashboard_required
@require_POST
def order_tracking_update(request: HttpRequest, pk: int) -> HttpResponse:
    """Manually update or create the tracking ID (waybill number)."""
    order = get_object_or_404(Order, pk=pk)
    
    from core.models import SiteSettings
    settings = SiteSettings.objects.first()
    enable_delhivery = settings.enable_delhivery if settings else True
    
    if enable_delhivery:
        from delhivery.models import DelhiveryShipment
        waybill_number = request.POST.get("waybill_number", "").strip()
        
        if waybill_number:
            shipment, created = DelhiveryShipment.objects.get_or_create(order=order)
            shipment.waybill_number = waybill_number
            if created:
                shipment.tracking_status = "Initiated"
            shipment.save(update_fields=["waybill_number", "tracking_status", "updated_at"] if not created else None)
            messages.success(request, f"Tracking ID saved: {waybill_number}")
        else:
            if hasattr(order, 'delhivery_shipment'):
                order.delhivery_shipment.waybill_number = None
                order.delhivery_shipment.save(update_fields=["waybill_number", "updated_at"])
                messages.info(request, "Tracking ID cleared.")
    else:
        tracking_number = request.POST.get("tracking_number", "").strip()
        shipping_provider = request.POST.get("shipping_provider", "").strip()
        shipping_provider_url = request.POST.get("shipping_provider_url", "").strip()
        
        order.tracking_number = tracking_number
        order.shipping_provider = shipping_provider
        order.shipping_provider_url = shipping_provider_url
        order.save(update_fields=["tracking_number", "shipping_provider", "shipping_provider_url", "updated_at"])
        
        if tracking_number or shipping_provider or shipping_provider_url:
            messages.success(request, "Tracking information updated.")
        else:
            messages.info(request, "Tracking information cleared.")
            
    return redirect("dashboard:order-detail", pk=pk)
