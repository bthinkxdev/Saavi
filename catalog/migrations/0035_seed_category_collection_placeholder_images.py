"""Give every existing category and collection a named placeholder image.

Only blank images are filled, so anything already uploaded in the dashboard is left alone.
Replace these in Dashboard -> Categories / Collections whenever real artwork is ready.
"""

import os

from django.conf import settings
from django.db import migrations

CATEGORY_SLUGS = [
    "sarees", "silk-sarees", "cotton-sarees", "bridal-sarees", "party-wear-sarees", "designer-sarees",
    "menskurta", "cotton-kurta", "linen-kurta", "silk-kurta", "festive-kurta", "wedding-kurta",
]
COLLECTION_SLUGS = [
    "gifting-edit", "twinning-edit", "wedding-season", "royal-heritage", "bridal-trousseau",
    "grooms-collection", "festive-celebrations", "party-cocktail-edit", "mens-festive-edit",
    "handloom-classics", "summer-linen-cotton", "diwali-edit", "eid-edit", "designer-statement",
    "everyday-essentials",
]


def _fill(model, folder, slugs):
    for obj in model.objects.filter(slug__in=slugs):
        if obj.image:
            continue
        rel = f"{folder}/placeholders/{obj.slug}.png"
        # Only point at a file that exists, so a deployment missing the media folder stays blank.
        if os.path.exists(os.path.join(settings.MEDIA_ROOT, rel)):
            obj.image = rel
            obj.save(update_fields=["image"])


def seed(apps, schema_editor):
    _fill(apps.get_model("catalog", "Category"), "categories", CATEGORY_SLUGS)
    _fill(apps.get_model("catalog", "Collection"), "collections", COLLECTION_SLUGS)


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0034_category_image_alter_collection_image"),
    ]

    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
