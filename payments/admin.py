"""Django admin registrations for the payments app."""

from __future__ import annotations

from django.contrib import admin

from payments.models import PaymentTransaction


@admin.register(PaymentTransaction)
class PaymentTransactionAdmin(admin.ModelAdmin):
    list_display = ("pk", "order", "gateway_key", "amount", "status", "created_at")


