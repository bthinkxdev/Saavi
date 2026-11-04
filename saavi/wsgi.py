"""WSGI config for saavi."""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "saavi.settings")

application = get_wsgi_application()
