"""Create/refresh the Saavi storefront currencies (INR base, AED, USD, EUR)."""

from decimal import Decimal

from django.core.management.base import BaseCommand

from core.models import Currency

CURRENCIES = [
    # code, symbol, base units (INR) per 1 unit — starting values, refreshed daily
    ("INR", "₹", Decimal("1"), True),
    ("AED", "AED", Decimal("23.90"), False),
    ("USD", "$", Decimal("87.80"), False),
    ("EUR", "€", Decimal("101.50"), False),
]


class Command(BaseCommand):
    help = "Seed INR (base/default), AED, USD and EUR and fetch today's exchange rates."

    def add_arguments(self, parser):
        parser.add_argument("--no-fetch", action="store_true", help="Skip the live exchange-rate fetch.")

    def handle(self, *args, **options):
        for code, symbol, rate, is_default in CURRENCIES:
            obj, created = Currency.objects.get_or_create(
                code=code,
                defaults={"symbol": symbol, "exchange_rate_to_base": rate, "is_default": is_default, "is_active": True},
            )
            if not created:
                obj.symbol = symbol
                obj.is_active = True
                if code == "INR":
                    obj.exchange_rate_to_base = Decimal("1")
                    obj.is_default = True
                elif obj.exchange_rate_to_base == 1:
                    obj.exchange_rate_to_base = rate
                obj.save()
            self.stdout.write(f"{'Created' if created else 'Updated'} {code}")
        Currency.objects.exclude(code__in=[c[0] for c in CURRENCIES]).update(is_active=False, is_default=False)
        if not options["no_fetch"]:
            from core.currency import update_exchange_rates

            self.stdout.write(f"Live rates: {update_exchange_rates() or 'fetch failed, kept defaults'}")
