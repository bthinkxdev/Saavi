"""Merge the tax-configuration and rebrand branches of the core migration graph.

Both branches added a 0039 migration on top of 0038_market_prices. They touch unrelated
things (tax-rate columns on SiteSettings vs. brand text rows), so this merge has no operations;
it only gives the graph a single leaf. Databases that already applied either 0039 upgrade
cleanly: Django applies whichever one is missing, then this merge.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0039_rebrand_to_saavi_by_neethu"),
        ("core", "0039_sitesettings_uae_tax_rate_percent_and_more"),
    ]

    operations = []
