"""ASGI config for sarocchi."""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "sarocchi.settings")

application = get_asgi_application()
