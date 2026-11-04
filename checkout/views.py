"""HTTP views for the checkout app."""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from accounts.selectors import get_address_by_id, get_saved_addresses
from cart.selectors import get_cart_for_request, get_cart_summary
from cart.services import get_or_create_cart
from checkout.access import can_access_order, grant_order_access
from checkout.forms import CheckoutAddressForm, CheckoutDeliveryForm, CheckoutPaymentForm
from checkout.selectors import get_checkout_session_by_id
from checkout.services import create_checkout_session, place_order, update_checkout_session

from payments.registry import CHECKOUT_GATEWAY_KEYS, PAYMENT_GATEWAYS
from payments.services import process_payment

logger = logging.getLogger(__name__)


def _get_checkout_cart(request: HttpRequest, create: bool = False):
    if request.GET.get("mode") == "cart":
        request.session["checkout_mode"] = "cart"
    if request.session.get("checkout_mode") == "buy_now":
        buy_now_cart_id = request.session.get("buy_now_cart_id")
        if buy_now_cart_id:
            from cart.models import Cart
            cart = Cart.objects.filter(pk=buy_now_cart_id).first()
            if cart:
                return cart
    if create:
        return get_or_create_cart(request=request)
    return get_cart_for_request(request=request)


def _resolve_checkout_address_and_city(
    request: HttpRequest,
    session: Optional[Any] = None,
    profile: Optional[Any] = None,
    addresses: Optional[list] = None,
):
    """
    Resolve the selected address and city name for delivery calculation during checkout.
    Checks POST data first, then session storage, then saved addresses.
    """
    from accounts.models import Address

    raw_address_id = request.POST.get("address_id")
    if raw_address_id is not None:
        raw_address_id = raw_address_id.strip()
        request.session["checkout_address_id"] = raw_address_id
    else:
        raw_address_id = request.session.get("checkout_address_id", "")

    manual_city = request.POST.get("guest_city_manual", "").strip()
    selected_city_post = request.POST.get("guest_city")
    if selected_city_post is not None:
        selected_city_post = selected_city_post.strip()
        if selected_city_post == "__other__":
            raw_city = manual_city
            request.session["checkout_guest_city"] = manual_city or "__other__"
        else:
            raw_city = selected_city_post
            request.session["checkout_guest_city"] = selected_city_post
    elif manual_city:
        raw_city = manual_city
        request.session["checkout_guest_city"] = manual_city
    else:
        raw_city = request.session.get("checkout_guest_city", "")

    address = None
    if raw_address_id:
        try:
            address = Address.objects.filter(pk=int(raw_address_id)).first()
        except (ValueError, TypeError):
            pass

    if not address and session and getattr(session, "address", None):
        address = session.address

    if not address and raw_address_id != "" and addresses:
        address = addresses[0]
    elif not address and raw_address_id != "" and profile:
        if getattr(profile, "default_address", None):
            address = profile.default_address
        else:
            saved_list = list(get_saved_addresses(customer_profile=profile, page_size=1)["results"])
            if saved_list:
                address = saved_list[0]

    city_name = ""
    if address and getattr(address, "city", None):
        city_name = address.city
    elif raw_city:
        city_name = raw_city

    return address, city_name


@require_POST
def checkout_update_delivery_charge_view(request: HttpRequest) -> HttpResponse:
    """Update cart delivery charge based on selected city, address, or payment method."""
    cart = _get_checkout_cart(request=request, create=False)
    if not cart:
        return HttpResponse("")

    gateway_key = request.POST.get("gateway_key", "")
    from core.services import get_site_settings
    settings = get_site_settings()
    enable_cod = getattr(settings, "enable_cod", True)
    if gateway_key:
        if gateway_key not in CHECKOUT_GATEWAY_KEYS or (gateway_key == "cod" and not enable_cod):
            gateway_key = ""
        request.session["checkout_gateway_key"] = gateway_key
    else:
        gateway_key = request.session.get("checkout_gateway_key", "")

    session = cart.checkout_sessions.filter(status="draft").order_by("-updated_at").first() if hasattr(cart, "checkout_sessions") else None
    profile = cart.customer_profile if hasattr(cart, "customer_profile") else None

    address, city_name = _resolve_checkout_address_and_city(
        request=request,
        session=session,
        profile=profile,
    )

    if address and session and session.address != address:
        session.address = address
        session.save(update_fields=["address", "updated_at"])

    is_cod = (gateway_key == "cod" and enable_cod)
    summary = get_cart_summary(cart=cart, skip_delivery_charge_calculation=True)
    from delivery.selectors import get_delivery_charge
    cart.delivery_charge = get_delivery_charge(
        subtotal=summary.subtotal,
        address=address,
        city=city_name,
        is_cod=is_cod,
    )
    cart.save(update_fields=["delivery_charge", "updated_at"])

    from django.shortcuts import redirect
    return redirect("checkout:checkout")


@require_POST
def checkout_fix_stock_view(request: HttpRequest) -> HttpResponse:
    """Adjust cart items exceeding available stock to their maximum available stock."""
    cart = _get_checkout_cart(request=request, create=False)
    if not cart:
        return HttpResponse("")

    from cart.models import CartItem
    from cart.services import _resolve_unit_price

    items = CartItem.objects.filter(cart=cart).select_related("product", "variant")
    for item in items:
        max_stock = item.variant.stock_quantity if item.variant else item.product.stock_quantity
        if max_stock is None:
            max_stock = 0
        if max_stock > 0 and item.quantity > max_stock:
            user = (
                cart.customer_profile.user
                if (hasattr(cart, "customer_profile") and cart.customer_profile and cart.customer_profile.user_id)
                else None
            )
            try:
                unit_price = _resolve_unit_price(
                    product=item.product,
                    variant=item.variant,
                    user=user,
                    quantity=max_stock,
                )
            except Exception:
                unit_price = item.unit_price_at_add

            item.quantity = max_stock
            item.unit_price_at_add = unit_price
            item.save(update_fields=["quantity", "unit_price_at_add", "updated_at"])

    from django.shortcuts import redirect
    return redirect("checkout:checkout")


@require_GET
def checkout_view(request: HttpRequest) -> HttpResponse:
    """Multi-step checkout page with gift Order Preview partial."""
    cart = _get_checkout_cart(request=request, create=True)
    summary = get_cart_summary(cart=cart)
    if not summary.lines:
        #do not redirect,render the empty state in checkout.html
        pass

    if request.user.is_authenticated:
        from accounts.services import ensure_customer_profile_for_user
        profile = ensure_customer_profile_for_user(user=request.user)
    else:
        profile = None

    session = create_checkout_session(
        cart=cart,
        customer_profile=profile,
        session_key=request.session.session_key or "",
    )


    addresses = []
    if profile:
        if profile.default_address:
            addresses = [profile.default_address]
        else:
            saved_list = list(get_saved_addresses(customer_profile=profile, page_size=1)["results"])
            if saved_list:
                addresses = [saved_list[0]]
            
    from delivery.models import City
    active_cities = City.objects.filter(is_active=True)

    address, city_name = _resolve_checkout_address_and_city(
        request=request,
        session=session,
        profile=profile,
        addresses=addresses,
    )
    if address and not session.address:
        session.address = address
        session.save(update_fields=["address", "updated_at"])

    selected_gateway_key = request.session.get("checkout_gateway_key")
    if not selected_gateway_key and session.order:
        last_tx = session.order.payment_transactions.last()
        if last_tx:
            selected_gateway_key = last_tx.gateway_key

    from core.services import get_site_settings
    settings = get_site_settings()
    enable_cod = getattr(settings, "enable_cod", True)
    enable_afterpay = getattr(settings, "enable_afterpay", True)
    enable_stripe = getattr(settings, "enable_stripe", True)

    from payments.adapters.stripe import stripe_is_configured
    stripe_ready = stripe_is_configured()

    available_gateways = {}
    for key, adapter in PAYMENT_GATEWAYS.items():
        if key not in CHECKOUT_GATEWAY_KEYS:
            continue
        if key == "cod" and not enable_cod:
            continue
        if key == "afterpay":
            if not enable_afterpay:
                continue
        if key == "stripe":
            if not enable_stripe or not stripe_ready:
                continue
        available_gateways[key] = adapter
        
    if not selected_gateway_key or selected_gateway_key not in available_gateways:
        selected_gateway_key = list(available_gateways.keys())[0] if available_gateways else ""
        
    summary = get_cart_summary(cart=cart, skip_delivery_charge_calculation=True)
    from delivery.selectors import get_delivery_charge
    
    is_cod = (selected_gateway_key == "cod" and enable_cod)
    new_charge = get_delivery_charge(
        subtotal=summary.subtotal,
        address=address,
        city=city_name,
        is_cod=is_cod,
    )
    if cart.delivery_charge != new_charge:
        cart.delivery_charge = new_charge
        cart.save(update_fields=["delivery_charge", "updated_at"])

    #reload summary after potential delivery charge update
    summary = get_cart_summary(cart=cart, skip_delivery_charge_calculation=True)

    from core.models import State
    INDIAN_STATES = list(State.objects.filter(is_active=True).values_list('name', flat=True))

    city_in_active_cities = any(c.name.lower() == (city_name or "").lower() for c in active_cities)

    estimated_delivery_text = ""
    if city_name:
        city_obj = active_cities.filter(name__iexact=city_name).first() if hasattr(active_cities, "filter") else None
        if city_obj and city_obj.estimated_delivery_text:
            estimated_delivery_text = city_obj.estimated_delivery_text
        elif settings and settings.default_estimated_delivery_text:
            estimated_delivery_text = settings.default_estimated_delivery_text

    from marketing.selectors import has_any_active_coupons
    return render(
        request,
        "checkout/checkout.html",
        {
            "cart": cart,
            "summary": summary,
            "checkout_session": session,
            "addresses": addresses,
            "active_cities": active_cities,
            "selected_city": city_name,
            "city_in_active_cities": city_in_active_cities,
            "estimated_delivery_text": estimated_delivery_text,
            "selected_address_id": str(address.pk) if address else (request.session.get("checkout_address_id") or ""),
            "indian_states": INDIAN_STATES,
            "settings": settings,

            "payment_gateways": available_gateways,
            "selected_gateway_key": selected_gateway_key,
            "has_active_coupons": has_any_active_coupons(),
            "is_buy_now": request.session.get("checkout_mode") == "buy_now",
        },
    )


@require_http_methods(["POST"])
def checkout_place_order_view(request: HttpRequest) -> HttpResponse:
    """Place order and process payment in one HTMX step."""
    form = CheckoutPaymentForm(request.POST)
    if not form.is_valid():
        return render(
            request,
            "checkout/partials/errors.html",
            {"errors": form.errors},
            status=200,
        )

    cart = _get_checkout_cart(request=request, create=False)
    if cart is None:
        raise Http404("Cart not found.")

    if request.user.is_authenticated:
        from accounts.services import ensure_customer_profile_for_user
        profile = ensure_customer_profile_for_user(user=request.user)
    else:
        profile = None

    session = create_checkout_session(cart=cart, customer_profile=profile, session_key=request.session.session_key or "")
    
    address = None
    address_form = CheckoutAddressForm(request.POST)
    if address_form.is_valid() and address_form.cleaned_data.get("address_id") and profile:
        address = get_address_by_id(
            address_id=address_form.cleaned_data["address_id"],
            customer_profile=profile,
        )
        if address:
            update_checkout_session(checkout_session=session, address=address)
            from accounts.services import set_default_address
            set_default_address(customer_profile=profile, address_id=address.pk)

    guest_name = request.POST.get("guest_name", "").strip()
    guest_email = request.POST.get("guest_email", "").strip()
    guest_phone = request.POST.get("guest_phone", "").strip()

    errors = {}
    if not guest_name:
        errors["guest_name"] = ["Name is required."]

    if not guest_email:
        errors["guest_email"] = ["Email is required."]
    else:
        if not re.match(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$", guest_email) or "@." in guest_email:
            errors["guest_email"] = ["Enter a valid email address."]
        else:
            try:
                validate_email(guest_email)
            except ValidationError:
                errors["guest_email"] = ["Enter a valid email address."]

    if not guest_phone:
        errors["guest_phone"] = ["Phone is required."]
    else:
        if not re.match(r'^\+?\d+$', guest_phone):
            errors["guest_phone"] = ["Phone number can only contain numbers."]
        elif not re.match(r'^\+?\d{10,15}$', guest_phone):
            errors["guest_phone"] = ["Enter a valid phone number."]

    if not address:
        guest_address_line1 = request.POST.get("guest_address_line1", "").strip()
        guest_address_line2 = request.POST.get("guest_address_line2", "").strip()
        selected_city_val = request.POST.get("guest_city", "").strip()
        manual_city_val = request.POST.get("guest_city_manual", "").strip()
        if selected_city_val == "__other__" or not selected_city_val:
            guest_city = manual_city_val
        else:
            guest_city = selected_city_val
        guest_state = request.POST.get("guest_state", "").strip()
        guest_country = request.POST.get("guest_country", "").strip()
        guest_pincode = request.POST.get("guest_pincode", "").strip()

        if not guest_address_line1:
            errors["guest_address_line1"] = ["Address Line 1 is required."]
        elif re.fullmatch(r"^\d+$", guest_address_line1):
            errors["guest_address_line1"] = ["Address cannot consist of numbers only."]
        elif re.fullmatch(r"^[^a-zA-Z0-9]+$", guest_address_line1):
            errors["guest_address_line1"] = ["Address cannot consist of special characters only."]
        elif not re.search(r"[a-zA-Z]", guest_address_line1):
            errors["guest_address_line1"] = ["Enter a valid address containing letters."]

        if not guest_city:
            errors["guest_city"] = ["City is required."]
        elif re.fullmatch(r"^\d+$", guest_city):
            errors["guest_city"] = ["City cannot consist of numbers only."]
        elif re.fullmatch(r"^[^a-zA-Z0-9]+$", guest_city):
            errors["guest_city"] = ["City cannot consist of special characters only."]
        elif not re.search(r"[a-zA-Z]", guest_city):
            errors["guest_city"] = ["Enter a valid city containing letters."]

        if not guest_state:
            errors["guest_state"] = ["State / Province is required."]
        elif re.fullmatch(r"^\d+$", guest_state):
            errors["guest_state"] = ["State cannot consist of numbers only."]
        elif re.fullmatch(r"^[^a-zA-Z0-9]+$", guest_state):
            errors["guest_state"] = ["State cannot consist of special characters only."]
        elif not re.search(r"[a-zA-Z]", guest_state):
            errors["guest_state"] = ["Enter a valid state containing letters."]

        if not guest_country:
            errors["guest_country"] = ["Country Code is required."]
        elif not re.fullmatch(r"^[a-zA-Z]{2}$", guest_country):
            errors["guest_country"] = ["Country must be exactly a 2-letter code (e.g. NZ)."]

        if not guest_pincode:
            errors["guest_pincode"] = ["PIN / Postal Code is required."]
        elif re.fullmatch(r"^[a-zA-Z\s]+$", guest_pincode):
            errors["guest_pincode"] = ["Postal code cannot contain alphabets only."]
        elif re.fullmatch(r"^[^a-zA-Z0-9]+$", guest_pincode):
            errors["guest_pincode"] = ["Postal code cannot contain special characters only."]
        elif not guest_pincode.isdigit():
            errors["guest_pincode"] = ["Postal code can only contain numbers."]
        elif len(guest_pincode) < 3:
            errors["guest_pincode"] = ["Enter a valid postal code."]

    if errors:
        return render(
            request,
            "checkout/partials/errors.html",
            {"errors": errors},
            status=200,
        )

    if not profile and not request.user.is_authenticated and guest_email:
        from accounts.services import login_or_create_customer_by_email
        profile = login_or_create_customer_by_email(email=guest_email, name=guest_name)

    if profile:
        if guest_phone and profile.phone != guest_phone:
            profile.phone = guest_phone
            profile.save(update_fields=["phone", "updated_at"])
        if guest_name:
            parts = guest_name.split(" ", 1)
            first_name = parts[0]
            last_name = parts[1] if len(parts) > 1 else ""
            if profile.user.first_name != first_name or profile.user.last_name != last_name:
                profile.user.first_name = first_name
                profile.user.last_name = last_name
                profile.user.save(update_fields=["first_name", "last_name"])

    if not address:
        from accounts.models import Address
        address = Address.objects.filter(
            customer_profile=profile,
            line1=guest_address_line1,
            line2=guest_address_line2,
            city=guest_city,
            pincode=guest_pincode,
        ).first()
        if not address and profile:
            address = Address.objects.create(
                customer_profile=profile,
                line1=guest_address_line1,
                line2=guest_address_line2,
                city=guest_city,
                state=guest_state,
                country=guest_country,
                pincode=guest_pincode,
                label="Delivery Address"
            )
        elif address and profile:
            if getattr(address, "state", "") != guest_state or getattr(address, "country", "") != guest_country or getattr(address, "pincode", "") != guest_pincode:
                address.state = guest_state
                address.country = guest_country
                address.pincode = guest_pincode
                address.save(update_fields=["state", "country", "pincode", "updated_at"])
            
        if profile and address:
            from accounts.services import set_default_address
            set_default_address(customer_profile=profile, address_id=address.pk)
            
        if address:
            update_checkout_session(checkout_session=session, address=address)
            
        if session.customer_profile != profile:
            session.customer_profile = profile
            session.save(update_fields=["customer_profile", "updated_at"])

    delivery_form = CheckoutDeliveryForm(request.POST)
    if delivery_form.is_valid():
        update_checkout_session(
            checkout_session=session,
            delivery_date=delivery_form.cleaned_data.get("delivery_date"),
        )
        
    gateway_key = form.cleaned_data["gateway_key"]
    from core.services import get_site_settings
    settings = get_site_settings()
    enable_cod = getattr(settings, "enable_cod", True)

    if gateway_key not in CHECKOUT_GATEWAY_KEYS:
        return render(
            request,
            "checkout/partials/errors.html",
            {"errors": {"gateway_key": ["This payment method is not available."]}},
            status=200,
        )

    if gateway_key == "cod" and not enable_cod:
        return render(
            request,
            "checkout/partials/errors.html",
            {"errors": {"gateway_key": ["Cash on Delivery is currently disabled."]}},
            status=200,
        )

    if gateway_key == "afterpay" and not getattr(settings, "enable_afterpay", True):
        return render(
            request,
            "checkout/partials/errors.html",
            {"errors": {"gateway_key": ["Afterpay payment is currently disabled."]}},
            status=200,
        )

    if gateway_key == "stripe":
        from payments.adapters.stripe import stripe_is_configured
        if not getattr(settings, "enable_stripe", True) or not stripe_is_configured():
            return render(
                request,
                "checkout/partials/errors.html",
                {"errors": {"gateway_key": ["Card payment is currently unavailable."]}},
                status=200,
            )

    summary = get_cart_summary(cart=cart, skip_delivery_charge_calculation=True)
    from delivery.selectors import get_delivery_charge
    if not address and session.address:
        address = session.address
    
    if gateway_key == "cod" and enable_cod:
        new_charge = get_delivery_charge(subtotal=summary.subtotal, address=address, is_cod=True)
        if cart.delivery_charge != new_charge:
            cart.delivery_charge = new_charge
            cart.save(update_fields=["delivery_charge", "updated_at"])
    else:
        new_charge = get_delivery_charge(subtotal=summary.subtotal, address=address, is_cod=False)
        if cart.delivery_charge != new_charge:
            cart.delivery_charge = new_charge
            cart.save(update_fields=["delivery_charge", "updated_at"])

    # summary is already retrieved on line 375 with skip_delivery_charge_calculation=True
    if summary.has_stock_issues:
        from django.utils.translation import gettext as _
        is_buy_now = request.session.get("checkout_mode") == "buy_now"
        msg = _("This item just went out of stock or quantity exceeds available stock. Please review your order summary.") if is_buy_now else _("Some items in your cart are out of stock. Please review your order summary to adjust them.")
        response = render(
            request,
            "checkout/partials/errors.html",
            {"errors": {"__all__": [msg]}},
            status=200,
        )
        response["HX-Trigger"] = "stockChanged"
        return response

    try:
        from catalog.exceptions import InsufficientStockError
        order = place_order(
            checkout_session_id=session.pk,
            idempotency_key=form.cleaned_data["idempotency_key"],
            gateway_key=gateway_key,
            customer_profile=profile,
            is_guest_checkout=not request.user.is_authenticated,
        )
    except InsufficientStockError as exc:
        response = render(
            request,
            "checkout/partials/errors.html",
            {"errors": {"__all__": [str(exc)]}},
            status=200,
        )
        response["HX-Trigger"] = "stockChanged"
        return response

    grant_order_access(request=request, order=order)

    payment_data = {}

    process_payment(
        order=order,
        gateway_key=gateway_key,
        payment_data=payment_data,
    )

    if gateway_key.startswith("razorpay"):
        pay_url = reverse("checkout:razorpay-pay", kwargs={"order_id": order.pk})
        if request.headers.get("HX-Request"):
            response = HttpResponse()
            response["HX-Redirect"] = pay_url
            return response
        return redirect(pay_url)

    if gateway_key.startswith("cybersource"):
        pay_url = reverse("checkout:cybersource-pay", kwargs={"order_id": order.pk})
        if request.headers.get("HX-Request"):
            response = HttpResponse()
            response["HX-Redirect"] = pay_url
            return response
        return redirect(pay_url)

    if gateway_key == "afterpay":
        pay_url = reverse("checkout:afterpay-pay", kwargs={"order_id": order.pk})
        if request.headers.get("HX-Request"):
            response = HttpResponse()
            response["HX-Redirect"] = pay_url
            return response
        return redirect(pay_url)

    if gateway_key == "stripe":
        pay_url = reverse("checkout:stripe-pay", kwargs={"order_id": order.pk})
        if request.headers.get("HX-Request"):
            response = HttpResponse()
            response["HX-Redirect"] = pay_url
            return response
        return redirect(pay_url)

    confirmation_url = reverse("checkout:confirmation", kwargs={"order_id": order.pk})
    if request.headers.get("HX-Request"):
        response = HttpResponse()
        response["HX-Redirect"] = confirmation_url
        return response
    return redirect(confirmation_url)


@never_cache
@require_GET
def checkout_confirmation_view(request: HttpRequest, order_id: int) -> HttpResponse:
    """
    Order success / status page.

    For Stripe the redirect query string is NOT evidence of payment: the page asks
    Stripe directly (and the webhook settles the order independently), then renders
    whatever the order's real state is.
    """
    request.session["checkout_mode"] = "cart"
    from orders.models import Order, OrderStatus
    from django.shortcuts import get_object_or_404
    order = get_object_or_404(Order.objects.select_related("customer_profile__user", "currency"), pk=order_id)
    if not can_access_order(request=request, order=order):
        raise Http404("Order not found.")

    if order.order_status == OrderStatus.CHECKOUT_PENDING:
        from payments.stripe_service import sync_order_payment_from_stripe
        sync_order_payment_from_stripe(
            order=order,
            payment_intent_id=request.GET.get("payment_intent", ""),
        )
        order.refresh_from_db()

    return render(
        request,
        "checkout/confirmation_page.html",
        {
            "order": order,
            "payment_pending": order.order_status == OrderStatus.CHECKOUT_PENDING,
        },
    )


@never_cache
@require_GET
def razorpay_pay_view(request: HttpRequest, order_id: int) -> HttpResponse:
    """Render Razorpay checkout payment page."""
    from orders.models import Order, OrderStatus
    from payments.models import PaymentTransaction
    from payments.adapters.concrete import _get_razorpay_credentials
    from django.shortcuts import get_object_or_404

    order = get_object_or_404(Order, pk=order_id)
    
    if order.order_status != OrderStatus.CHECKOUT_PENDING:
        from django.shortcuts import redirect
        return redirect("catalog:plp")

    payment_tx = PaymentTransaction.objects.filter(order=order, gateway_key__startswith="razorpay").last()
    key_id, _ = _get_razorpay_credentials()

    customer_name = ""
    customer_email = ""
    customer_phone = ""
    if order.customer_profile:
        customer_name = f"{order.customer_profile.user.first_name} {order.customer_profile.user.last_name}".strip() or order.customer_profile.user.username
        customer_email = order.customer_profile.user.email
        customer_phone = order.customer_profile.phone
    elif order.delivery_address_snapshot:
        customer_name = order.delivery_address_snapshot.get("recipient_name", "")
        customer_email = order.delivery_address_snapshot.get("email", "")
        customer_phone = order.delivery_address_snapshot.get("phone", "")

    amount_in_paise = int(order.total_amount * 100)
    from core.selectors import get_default_currency
    default_curr = get_default_currency()
    currency_code = order.currency.code if order.currency else (default_curr.code if default_curr else "AED")
    razorpay_order_id = payment_tx.external_intent_id if payment_tx else f"rzp_order_{order.pk}"

    #determine prefill method based on gateway key
    prefill_method = ""
    payment_method_name = "Razorpay"
    if payment_tx and payment_tx.gateway_key:
        if payment_tx.gateway_key == "razorpay_upi":
            prefill_method = "upi"
            payment_method_name = "UPI"
        elif payment_tx.gateway_key == "razorpay_card":
            prefill_method = "card"
            payment_method_name = "Credit/Debit Card"
        elif payment_tx.gateway_key == "razorpay_netbanking":
            prefill_method = "netbanking"
            payment_method_name = "Net Banking"
        elif payment_tx.gateway_key == "razorpay_wallet":
            prefill_method = "wallet"
            payment_method_name = "Wallet"

    #store order_id in session so the callback can retrieve it
    request.session["razorpay_order_pk"] = order.pk

    #build absolute callback URL for Razorpay redirect
    callback_url = request.build_absolute_uri(reverse("checkout:razorpay-callback"))
    cancel_url = request.build_absolute_uri(reverse("checkout:checkout"))

    return render(
        request,
        "checkout/razorpay_pay.html",
        {
            "order": order,
            "razorpay_key_id": key_id or "rzp_test_mock",
            "razorpay_order_id": razorpay_order_id,
            "amount_in_paise": amount_in_paise,
            "currency_code": currency_code,
            "customer_name": customer_name,
            "customer_email": customer_email,
            "customer_phone": customer_phone,
            "callback_url": callback_url,
            "cancel_url": cancel_url,
            "prefill_method": prefill_method,
            "payment_method_name": payment_method_name,
        },
    )


from django.views.decorators.csrf import csrf_exempt


@csrf_exempt
@require_http_methods(["POST"])
def razorpay_callback_view(request: HttpRequest) -> HttpResponse:
    """
    Handle POST callback from Razorpay after payment.

    Razorpay redirects the full browser here with razorpay_payment_id,
    razorpay_order_id, and razorpay_signature as POST parameters.
    """
    from payments.models import PaymentTransaction
    from payments.adapters.concrete import RazorpayAdapter
    from payments.services import confirm_payment_success, confirm_payment_failed
    from django.shortcuts import get_object_or_404
    from orders.models import Order
    from core.selectors import get_default_currency

    razorpay_payment_id = request.POST.get("razorpay_payment_id", "")
    razorpay_order_id = request.POST.get("razorpay_order_id", "")
    razorpay_signature = request.POST.get("razorpay_signature", "")

    #try order_id from POST (JS form submit) or session (Razorpay redirect)
    order_id = request.POST.get("order_id") or request.session.get("razorpay_order_pk")

    if not order_id:
        #fallback: look up order via Razorpay order ID stored in PaymentTransaction
        payment_tx = PaymentTransaction.objects.filter(
            external_intent_id=razorpay_order_id,
            gateway_key__startswith="razorpay",
        ).last()
        if payment_tx:
            order_id = payment_tx.order_id
        else:
            return redirect("checkout:checkout")

    order = get_object_or_404(Order, pk=order_id)
    payment_tx = PaymentTransaction.objects.filter(order=order, gateway_key__startswith="razorpay").last()

    #clean up session
    request.session.pop("razorpay_order_pk", None)

    adapter = RazorpayAdapter()
    is_valid = adapter.verify_payment_signature(
        razorpay_order_id=razorpay_order_id,
        razorpay_payment_id=razorpay_payment_id,
        razorpay_signature=razorpay_signature,
    )

    if is_valid and payment_tx:
        if not payment_tx.currency:
            default_curr = get_default_currency()
        currency_code = payment_tx.currency.code if payment_tx.currency else (default_curr.code if default_curr else "AED")
        capture_succeeded = adapter.capture_payment(
            razorpay_payment_id=razorpay_payment_id,
            amount=payment_tx.amount,
            currency=currency_code,
        )
        if not capture_succeeded:
            logger.error(
                "Razorpay capture failed after valid signature: order_id=%s "
                "razorpay_payment_id=%s razorpay_order_id=%s",
                order.pk, razorpay_payment_id, razorpay_order_id,
            )
            confirm_payment_failed(payment_transaction=payment_tx)
            return redirect("checkout:checkout")

        confirm_payment_success(payment_transaction=payment_tx, external_transaction_id=razorpay_payment_id)
        return redirect("checkout:confirmation", order_id=order.pk)
    else:
        if payment_tx:
            confirm_payment_failed(payment_transaction=payment_tx)
        return redirect("checkout:checkout")


@require_POST
def checkout_coupon_apply_view(request: HttpRequest) -> HttpResponse:
    """Validate and apply a coupon code from checkout."""
    from cart.forms import CartCouponForm
    from cart.services import apply_coupon
    from marketing.exceptions import InvalidCouponError
    from django.contrib import messages
    from cart.selectors import get_cart_for_request
    from django.utils.translation import gettext as _

    form = CartCouponForm(request.POST)
    if not form.is_valid():
        messages.error(request, _("Enter a valid coupon code."))
        return redirect("checkout:checkout")

    cart = _get_checkout_cart(request=request, create=False)
    if cart is None:
        raise Http404("Cart not found.")

    try:
        apply_coupon(cart=cart, code=form.cleaned_data["code"])
        messages.success(request, _("Coupon applied successfully!"))
    except InvalidCouponError as exc:
        messages.error(request, str(exc))

    return redirect("checkout:checkout")


@require_POST
def checkout_coupon_remove_view(request: HttpRequest) -> HttpResponse:
    """Remove any applied coupon from the cart from checkout."""
    from cart.services import remove_coupon
    from cart.selectors import get_cart_for_request
    from django.contrib import messages
    from django.utils.translation import gettext as _
    
    cart = _get_checkout_cart(request=request, create=False)
    if cart:
        remove_coupon(cart=cart)
        messages.success(request, _("Coupon removed."))
    return redirect("checkout:checkout")


@never_cache
@require_GET
def cybersource_pay_view(request: HttpRequest, order_id: int) -> HttpResponse:
    """Render CyberSource hosted checkout form or redirect."""
    from orders.models import Order, OrderStatus
    from payments.models import PaymentTransaction
    from django.shortcuts import get_object_or_404, redirect

    order = get_object_or_404(Order, pk=order_id)
    if order.order_status != OrderStatus.CHECKOUT_PENDING:
        return redirect("catalog:plp")

    payment_tx = PaymentTransaction.objects.filter(order=order, gateway_key__startswith="cybersource").last()
    if not payment_tx:
        return redirect("checkout:checkout")

    #if it's an Afterpay redirect, just redirect there immediately
    redirect_url = payment_tx.metadata.get("redirect_url")
    if redirect_url:
        if payment_tx.metadata.get("error"):
            from django.contrib import messages
            messages.error(request, "Failed to initialize payment with the provider. Please try another payment method.")
            return redirect("checkout:checkout")
        return redirect(redirect_url)

    #otherwise, render a form for the hosted page
    hosted_page_url = payment_tx.metadata.get("hosted_page_url", "")
    
    request.session["cybersource_order_pk"] = order.pk

    return render(
        request,
        "checkout/cybersource_pay.html",
        {
            "order": order,
            "hosted_page_url": hosted_page_url,
            "metadata": payment_tx.metadata,
        },
    )

@require_http_methods(["GET", "POST"])
@csrf_exempt
def cybersource_redirect_view(request: HttpRequest) -> HttpResponse:
    """Handle browser return from CyberSource. Does not confirm payment."""
    from orders.models import Order, OrderStatus
    from payments.models import PaymentTransaction
    from django.shortcuts import redirect
    
    #try to find the user's latest pending order, or use the one stored in session
    order = None
    order_id = request.session.get("cybersource_order_pk")
    
    if order_id:
        order = Order.objects.filter(pk=order_id).first()
    elif request.user.is_authenticated:
        order = Order.objects.filter(user=request.user).last()
        
    if order:
        #if the webhook already processed it (or we are simulating)
        if order.order_status != OrderStatus.CHECKOUT_PENDING:
            return redirect("checkout:confirmation", order_id=order.id)
            
        #synchronous verification (like Razorpay)
        payment_tx = PaymentTransaction.objects.filter(order=order, gateway_key__startswith="cybersource").last()
        if payment_tx and payment_tx.external_intent_id:
            from payments.adapters.concrete import CyberSourceAdapter
            from payments.services import confirm_payment_success
            from django.conf import settings
            
            adapter = CyberSourceAdapter()
            is_success = adapter.fetch_payment_status(payment_tx.external_intent_id)
            
            #in sandbox, if the TransactionDetailsApi isn't enabled, fallback to DEBUG auto-success
            if is_success or settings.DEBUG:
                confirm_payment_success(payment_transaction=payment_tx, external_transaction_id=payment_tx.external_intent_id)
                request.session.pop("cybersource_order_pk", None)
                return redirect("checkout:confirmation", order_id=order.id)

    return render(request, "checkout/cybersource_redirect.html", {})

@require_http_methods(["POST"])
@csrf_exempt
def cybersource_process_token_view(request: HttpRequest) -> HttpResponse:
    """
    Receives the transientToken from Flex Microform and processes the payment.
    """
    import json
    from django.http import JsonResponse
    from payments.models import PaymentTransaction
    from payments.adapters.concrete import CyberSourceCardAdapter
    from django.shortcuts import get_object_or_404
    from orders.models import Order
    import logging
    
    logger = logging.getLogger(__name__)
    
    try:
        data = json.loads(request.body)
        transient_token = data.get('transientToken')
        order_id = data.get('order_id')
        
        if not transient_token or not order_id:
            return JsonResponse({'success': False, 'error': 'Missing token or order_id'}, status=400)
            
        order = get_object_or_404(Order, pk=order_id)
        
        adapter = CyberSourceCardAdapter()
        
        #authorize with token
        resp_dict = adapter.authorize_with_token(
            token=transient_token,
            order_id=order.pk,
            amount=order.total_amount,
            currency=order.currency.code
        )
        
        status = resp_dict.get('status', '').upper()
        
        if status in ['AUTHORIZED', 'SETTLED', 'COMPLETED']:
            #mark payment success synchronously
            tx = PaymentTransaction.objects.filter(order=order).last()
            if tx:
                tx.external_transaction_id = resp_dict.get('id', '')
                tx.save(update_fields=["external_transaction_id"])
                from payments.services import confirm_payment_success
                confirm_payment_success(payment_transaction=tx)
                
            return JsonResponse({
                'success': True, 
                'redirect_url': f"/checkout/confirmation/{order.pk}/"
            })
        else:
            #payment failed
            tx = PaymentTransaction.objects.filter(order=order).last()
            if tx:
                from payments.services import confirm_payment_failed
                confirm_payment_failed(payment_transaction=tx)
            
            error_message = resp_dict.get('message', '') or resp_dict.get('reason', '')
            details = resp_dict.get('details', [])
            detail_str = ""
            if details:
                detail_str = " | " + ", ".join([f"{d.get('field')}: {d.get('reason')}" for d in details])
                
            return JsonResponse({
                'success': False,
                'error': f"Payment declined: {status}. {error_message}{detail_str}",
                'redirect_url': "/checkout/"
            }, status=400)
            
    except Exception as e:
        logger.exception("Failed to process transient token")
        return JsonResponse({'success': False, 'error': 'Internal processing error'}, status=500)


@never_cache
@require_GET
def afterpay_pay_view(request: HttpRequest, order_id: int) -> HttpResponse:
    """
    Handle redirection to Afterpay hosted checkout or local sandbox simulator.
    """
    from decimal import Decimal
    from orders.models import Order, OrderStatus
    from payments.models import PaymentTransaction
    from django.shortcuts import get_object_or_404, redirect

    order = get_object_or_404(Order, pk=order_id)
    if order.order_status != OrderStatus.CHECKOUT_PENDING:
        return redirect("catalog:plp")

    payment_tx = PaymentTransaction.objects.filter(order=order, gateway_key="afterpay").last()
    if not payment_tx:
        return redirect("checkout:checkout")

    request.session["afterpay_order_pk"] = order.pk

    redirect_url = payment_tx.metadata.get("redirect_url", "")
    is_simulation = payment_tx.metadata.get("is_simulation", False)

    #if it is a real external Afterpay checkout URL, redirect immediately
    if redirect_url and not is_simulation and redirect_url.startswith("http"):
        return redirect(redirect_url)

    #render clean Afterpay payment & sandbox simulator page
    installment_amount = round(order.total_amount / Decimal("4.0"), 2)
    return render(
        request,
        "checkout/afterpay_pay.html",
        {
            "order": order,
            "payment_tx": payment_tx,
            "metadata": payment_tx.metadata,
            "installment_amount": installment_amount,
            "is_simulation": is_simulation,
            "token": payment_tx.metadata.get("token") or payment_tx.external_intent_id,
        },
    )


@require_http_methods(["GET", "POST"])
@csrf_exempt
def afterpay_callback_view(request: HttpRequest) -> HttpResponse:
    """
    Handle return from Afterpay (or Afterpay simulator).
    """
    from orders.models import Order, OrderStatus
    from payments.models import PaymentTransaction
    from payments.services import confirm_payment_success, confirm_payment_failed
    from django.shortcuts import redirect
    from django.contrib import messages

    status = (request.GET.get("status") or request.POST.get("status") or "").upper()
    order_token = request.GET.get("orderToken") or request.POST.get("orderToken") or ""
    order_id = request.GET.get("order_id") or request.POST.get("order_id") or request.session.get("afterpay_order_pk")

    order = None
    if order_id:
        order = Order.objects.filter(pk=order_id).first()
    elif request.user.is_authenticated:
        order = Order.objects.filter(user=request.user).last()

    if not order:
        return redirect("checkout:checkout")

    payment_tx = PaymentTransaction.objects.filter(order=order, gateway_key="afterpay").last()
    if not payment_tx:
        return redirect("checkout:checkout")

    if order.order_status != OrderStatus.CHECKOUT_PENDING:
        request.session.pop("afterpay_order_pk", None)
        return redirect("checkout:confirmation", order_id=order.id)

    if status == "SUCCESS":
        is_sim = (
            payment_tx.metadata.get("is_simulation", False)
            or order_token.startswith("afterpay_sim")
            or order_token.startswith("sim_")
        )
        if is_sim:
            #sandbox simulator instant approval
            confirm_payment_success(payment_transaction=payment_tx, external_transaction_id=order_token or f"sim_tx_{order.pk}")
            request.session.pop("afterpay_order_pk", None)
            return redirect("checkout:confirmation", order_id=order.id)
        else:
            #live / sandbox Afterpay Direct API capture
            from payments.adapters.concrete import AfterpayAdapter
            adapter = AfterpayAdapter()
            capture_resp = adapter.capture_order(order_token=order_token, order_id=str(order.pk))
            capture_status = capture_resp.get("status", "").upper()

            if capture_status in ("APPROVED", "CAPTURED"):
                confirm_payment_success(
                    payment_transaction=payment_tx,
                    external_transaction_id=capture_resp.get("id", order_token),
                )
                request.session.pop("afterpay_order_pk", None)
                return redirect("checkout:confirmation", order_id=order.id)
            else:
                confirm_payment_failed(payment_transaction=payment_tx)
                err_msg = capture_resp.get("message") or "Afterpay payment authorization was declined."
                messages.error(request, err_msg)
                return redirect("checkout:checkout")

    elif status == "CANCELLED":
        messages.info(request, "Afterpay payment was cancelled. Please choose a payment method to complete your purchase.")
        return redirect("checkout:checkout")
    else:
        confirm_payment_failed(payment_transaction=payment_tx)
        messages.error(request, "Afterpay payment could not be completed.")
        return redirect("checkout:checkout")


@never_cache
@require_GET
def stripe_pay_view(request: HttpRequest, order_id: int) -> HttpResponse:
    """Render the Stripe Payment Element page for an order this session placed."""
    from django.shortcuts import get_object_or_404, redirect
    from orders.models import Order, OrderStatus
    from payments.models import PaymentTransaction

    order = get_object_or_404(Order.objects.select_related("customer_profile__user", "currency"), pk=order_id)
    if not can_access_order(request=request, order=order):
        raise Http404("Order not found.")
    if order.order_status != OrderStatus.CHECKOUT_PENDING:
        return redirect("checkout:confirmation", order_id=order.pk)

    payment_tx = PaymentTransaction.objects.filter(order=order, gateway_key="stripe").last()
    if not payment_tx or not payment_tx.external_intent_id:
        return redirect("checkout:checkout")

    from payments.adapters.stripe import _get_stripe_credentials, retrieve_payment_intent
    import stripe

    pub_key, _, _ = _get_stripe_credentials()
    client_secret = ""
    error_code = ""
    if not pub_key:
        error_code = "not_configured"
    else:
        # The client_secret is never stored; fetch it from Stripe for this render only.
        try:
            intent = retrieve_payment_intent(payment_tx.external_intent_id)
        except (stripe.StripeError, ValueError):
            logger.exception("Could not load Stripe intent for order %s", order.pk)
            error_code = "unavailable"
        else:
            if intent.get("status") in ("requires_payment_method", "requires_confirmation", "requires_action"):
                client_secret = intent.get("client_secret", "")
            elif intent.get("status") in ("succeeded", "processing"):
                return redirect("checkout:confirmation", order_id=order.pk)
            else:
                error_code = "intent_closed"

    return render(
        request,
        "checkout/stripe_pay.html",
        {
            "order": order,
            "stripe_publishable_key": pub_key,
            "client_secret": client_secret,
            "stripe_config": {
                "publishableKey": pub_key,
                "clientSecret": client_secret,
                "returnUrl": request.build_absolute_uri(
                    reverse("checkout:confirmation", kwargs={"order_id": order.pk})
                ),
            },
            "error_code": error_code,
            "return_url": request.build_absolute_uri(
                reverse("checkout:confirmation", kwargs={"order_id": order.pk})
            ),
        },
    )
