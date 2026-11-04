"""
Per-browser ownership of freshly placed orders.

Order ids are sequential integers, so possession of an id proves nothing. Whoever
places an order is granted access to it for their session; the payment and
confirmation pages require that grant (or being the signed-in owner). This also
covers guest checkout, where there is no account to compare against.
"""

from __future__ import annotations

from django.http import HttpRequest

SESSION_KEY = "checkout_owned_order_ids"
MAX_REMEMBERED_ORDERS = 25


def grant_order_access(*, request: HttpRequest, order) -> None:
    """Remember in this browser session that it placed ``order``."""
    owned = [oid for oid in request.session.get(SESSION_KEY, []) if oid != order.pk]
    owned.append(order.pk)
    request.session[SESSION_KEY] = owned[-MAX_REMEMBERED_ORDERS:]


def can_access_order(*, request: HttpRequest, order) -> bool:
    """True if this request's session placed the order, or the signed-in user owns it."""
    if order.pk in request.session.get(SESSION_KEY, []):
        return True
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated and order.customer_profile_id:
        return order.customer_profile.user_id == user.pk
    return False
