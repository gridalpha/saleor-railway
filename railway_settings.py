"""Saleor settings for Railway.

Everything Saleor itself exposes stays an environment variable. This module exists only
for the one thing an environment variable cannot express: inserting WhiteNoise into
``MIDDLEWARE`` so ``STATIC_ROOT`` — collected during the image build and otherwise
unserved in production — is reachable. The transactional email templates link the shop
logo out of ``/static/``, so without this every message ships a broken image.
"""

from saleor.settings import *  # noqa: F401,F403
from saleor.settings import MIDDLEWARE as _SALEOR_MIDDLEWARE

_SECURITY = "django.middleware.security.SecurityMiddleware"
_WHITENOISE = "whitenoise.middleware.WhiteNoiseMiddleware"

# WhiteNoise sits directly below SecurityMiddleware, per its own documentation. It only
# answers paths under STATIC_URL; every other request falls through untouched.
MIDDLEWARE = list(_SALEOR_MIDDLEWARE)
if _WHITENOISE not in MIDDLEWARE:
    _at = MIDDLEWARE.index(_SECURITY) + 1 if _SECURITY in MIDDLEWARE else 0
    MIDDLEWARE.insert(_at, _WHITENOISE)

WHITENOISE_MAX_AGE = 86400
