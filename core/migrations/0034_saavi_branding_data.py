from django.db import migrations


def rename_site(apps, schema_editor):
    SiteSettings = apps.get_model("core", "SiteSettings")
    for s in SiteSettings.objects.all():
        if not s.site_name or "sarocchi" in s.site_name.lower():
            s.site_name = "Saavi By Neethu"
            s.save(update_fields=["site_name"])


class Migration(migrations.Migration):
    dependencies = [("core", "0033_remove_sitesettings_afterpay_environment_and_more")]
    operations = [migrations.RunPython(rename_site, migrations.RunPython.noop)]
