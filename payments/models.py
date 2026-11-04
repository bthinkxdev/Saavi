"""Data layer for the payments app — models only, no business logic."""

from __future__ import annotations

from django.db import models

from core.models import TimeStampedModel


class PaymentStatus(models.TextChoices):
    """Payment transaction lifecycle."""

    PENDING = "pending", "Pending"
    SUCCESS = "success", "Success"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"
    REFUNDED = "refunded", "Refunded"


class PaymentTransaction(TimeStampedModel):
    """Record of a payment attempt for an order."""

    order = models.ForeignKey(
        "orders.Order",
        on_delete=models.CASCADE,
        related_name="payment_transactions",
        verbose_name="Order",
    )
    gateway_key = models.CharField(max_length=40, db_index=True, verbose_name="Gateway key")
    amount = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Amount")
    currency = models.ForeignKey(
        "core.Currency",
        on_delete=models.PROTECT,
        related_name="payment_transactions",
        verbose_name="Currency",
    )
    status = models.CharField(
        max_length=20,
        choices=PaymentStatus.choices,
        default=PaymentStatus.PENDING,
        db_index=True,
        verbose_name="Status",
    )
    external_intent_id = models.CharField(
        max_length=120,
        blank=True,
        db_index=True,
        verbose_name="External intent ID",
    )
    external_transaction_id = models.CharField(
        max_length=120,
        blank=True,
        verbose_name="External transaction ID",
    )
    metadata = models.JSONField(default=dict, verbose_name="Metadata")

    class Meta:
        verbose_name = "Payment transaction"
        verbose_name_plural = "Payment transactions"
        indexes = [
            models.Index(fields=["order", "status"], name="pay_tx_order_status_idx"),
            models.Index(fields=["gateway_key", "status"], name="pay_tx_gateway_status_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.gateway_key} {self.amount} ({self.status})"
