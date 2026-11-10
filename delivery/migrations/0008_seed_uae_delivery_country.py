from django.db import migrations

def seed_uae_country(apps, schema_editor):
    Country = apps.get_model("delivery", "Country")
    Country.objects.get_or_create(code="AE", defaults={"name": "United Arab Emirates", "is_active": True})

class Migration(migrations.Migration):
    dependencies = [
        ("delivery", "0007_city_estimated_delivery_text"),
    ]
    operations = [
        migrations.RunPython(seed_uae_country, migrations.RunPython.noop),
    ]

