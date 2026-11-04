"""Domain exceptions for the orders app."""

from __future__ import annotations


class InvalidOrderStatusTransitionError(Exception):
    """Raised when an order status change is not allowed."""
