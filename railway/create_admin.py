"""Create the first staff account, once, from the deploy-time variables.

Saleor ships no first-run wizard and no default credentials: a freshly migrated database
has no staff user at all and the dashboard cannot be opened. This closes that gap
without ever handing the internet a known password.

It runs on every deploy and does nothing after the first: the guard is "does *any*
superuser exist", not "does this email exist", so rotating ``SALEOR_ADMIN_EMAIL`` later
does not quietly mint a second administrator, and changing the password in the dashboard
is never reverted by a redeploy.
"""

import os
import sys

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "railway_settings")
django.setup()

from django.core.management import call_command  # noqa: E402
from django.db import transaction  # noqa: E402

from saleor.account.models import User  # noqa: E402


def main() -> int:
    email = os.environ.get("SALEOR_ADMIN_EMAIL", "").strip()
    password = os.environ.get("SALEOR_ADMIN_PASSWORD", "")

    if not email or not password:
        print(
            "create_admin: SALEOR_ADMIN_EMAIL / SALEOR_ADMIN_PASSWORD are unset, "
            "skipping. Create staff with `manage.py createsuperuser`."
        )
        return 0

    with transaction.atomic():
        if User.objects.filter(is_superuser=True).exists():
            print("create_admin: a staff superuser already exists, leaving it alone")
            return 0

        os.environ["DJANGO_SUPERUSER_PASSWORD"] = password
        try:
            call_command("createsuperuser", interactive=False, email=email)
        finally:
            os.environ.pop("DJANGO_SUPERUSER_PASSWORD", None)

    print(f"create_admin: created the first staff superuser {email}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
