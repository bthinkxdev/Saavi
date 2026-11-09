from django.db import migrations

# (code, name, currency code, is_default)
COUNTRIES = [
    ("IN", "India", "INR", True),
    ("AE", "United Arab Emirates", "AED", False),
]


def seed_countries(apps, schema_editor):
    Country = apps.get_model("core", "Country")
    Currency = apps.get_model("core", "Currency")
    for code, name, currency_code, is_default in COUNTRIES:
        Country.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "currency": Currency.objects.filter(code=currency_code).first(),
                "is_default": is_default,
                "is_active": True,
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0036_country_availability"),
    ]

    operations = [
        migrations.RunPython(seed_countries, migrations.RunPython.noop),
    ]
