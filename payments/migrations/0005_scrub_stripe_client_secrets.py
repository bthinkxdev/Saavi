from django.db import migrations


def scrub_client_secrets(apps, schema_editor):
    """client_secret is a browser-only credential; stop retaining it in the DB."""
    PaymentTransaction = apps.get_model("payments", "PaymentTransaction")
    for tx in PaymentTransaction.objects.filter(gateway_key="stripe").iterator():
        metadata = tx.metadata or {}
        if "client_secret" in metadata or "publishable_key" in metadata:
            metadata.pop("client_secret", None)
            metadata.pop("publishable_key", None)
            tx.metadata = metadata
            tx.save(update_fields=["metadata"])


class Migration(migrations.Migration):

    dependencies = [
        ("payments", "0004_alter_razorpaywebhookevent_status"),
    ]

    operations = [
        migrations.RunPython(scrub_client_secrets, migrations.RunPython.noop),
    ]
