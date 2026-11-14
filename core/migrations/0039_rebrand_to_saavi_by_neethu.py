"""Replace the old "Sarocchi" brand text stored in the database with "Saavi By Neethu".

Idempotent and safe on any database: only rows that still contain the old name are touched.
The Instagram URL in Site Settings and the admin audit log are intentionally left alone.
"""

import re

from django.db import migrations

BRAND = "Saavi By Neethu"
OLD = re.compile(r"sarocchi(?:\s+luxe)?(?:\s+designs)?", re.IGNORECASE)


def _rebrand(text: str) -> str:
    return OLD.sub(BRAND, text)


def rebrand(apps, schema_editor):
    Brand = apps.get_model("catalog", "Brand")
    Category = apps.get_model("catalog", "Category")
    Specification = apps.get_model("catalog", "ProductSpecification")
    Section = apps.get_model("cms", "HomepageSection")

    for brand in Brand.objects.filter(name__icontains="sarocchi") | Brand.objects.filter(slug__icontains="sarocchi"):
        brand.name = _rebrand(brand.name)
        brand.slug = "saavi-by-neethu" if "sarocchi" in brand.slug.lower() else brand.slug
        brand.save(update_fields=["name", "slug"])

    for cat in Category.objects.filter(meta_title__icontains="sarocchi") | Category.objects.filter(meta_description__icontains="sarocchi"):
        cat.meta_title = _rebrand(cat.meta_title)
        cat.meta_description = _rebrand(cat.meta_description)
        cat.save(update_fields=["meta_title", "meta_description"])

    for spec in Specification.objects.filter(value__icontains="sarocchi"):
        spec.value = _rebrand(spec.value)
        spec.save(update_fields=["value"])

    for section in Section.objects.all():
        config = section.config if isinstance(section.config, dict) else {}
        changed = False
        if "sarocchi" in (section.title or "").lower():
            section.title = _rebrand(section.title)
            changed = True
        for slide in config.get("slides", []) if isinstance(config.get("slides"), list) else []:
            if isinstance(slide, dict) and "sarocchi" in str(slide.get("title", "")).lower():
                slide["title"] = _rebrand(slide["title"])
                changed = True
        # The old promo banner image had the previous brand name baked into the artwork.
        if str(config.get("image_url", "")).endswith("promotions/bannerb.png"):
            config.pop("image_url")
            changed = True
        if changed:
            section.config = config
            section.save(update_fields=["title", "config"])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0038_market_prices"),
        ("catalog", "0033_collection_homepage_fields"),
        ("cms", "0013_alter_homepagesection_section_type"),
    ]

    operations = [
        migrations.RunPython(rebrand, migrations.RunPython.noop),
    ]
