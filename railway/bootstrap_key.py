"""Elect one RSA signing key for every Saleor role through the shared database.

Saleor refuses to start with ``DEBUG=False`` unless ``RSA_PRIVATE_KEY`` holds a PEM
private key, and it signs every access token, app JWT and JWKS entry with it. That makes
it three things at once that a Railway variable cannot be:

  * multi-line — template variables replace values of that shape with placeholder text;
  * shared — the API, the worker and beat must load the *same* key, and no service can
    write another service's environment;
  * stable — a key regenerated per container invalidates every token already issued.

So the first container to boot generates the key and writes it with
``ON CONFLICT DO NOTHING``; every other container reads the row back. The result is
printed on stdout for the entrypoint to export.

Set ``RSA_PRIVATE_KEY`` yourself and the entrypoint never calls this.
"""

import os
import sys
import time

import psycopg
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

KEY_NAME = "rsa_private_key"
TABLE = "railway_bootstrap"
ATTEMPTS = 60
BACKOFF_SECONDS = 5


def generate_pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")


def fetch_or_create(dsn: str) -> str:
    with psycopg.connect(dsn, connect_timeout=10) as conn:
        # Held outside Saleor's own tables so `migrate` never sees it.
        conn.execute(
            f"CREATE TABLE IF NOT EXISTS {TABLE} "
            "(key text PRIMARY KEY, value text NOT NULL, "
            "created_at timestamptz NOT NULL DEFAULT now())"
        )
        row = conn.execute(
            f"SELECT value FROM {TABLE} WHERE key = %s", (KEY_NAME,)
        ).fetchone()
        if row:
            return row[0]
        conn.execute(
            f"INSERT INTO {TABLE} (key, value) VALUES (%s, %s) "
            "ON CONFLICT (key) DO NOTHING",
            (KEY_NAME, generate_pem()),
        )
        row = conn.execute(
            f"SELECT value FROM {TABLE} WHERE key = %s", (KEY_NAME,)
        ).fetchone()
        if not row:
            raise RuntimeError("key row missing immediately after insert")
        return row[0]


def main() -> int:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("bootstrap_key: DATABASE_URL is not set", file=sys.stderr)
        return 1

    # There is no service dependency ordering on Railway, so the database may still be
    # starting. Two containers racing the CREATE TABLE also land here.
    last_error: Exception | None = None
    for attempt in range(1, ATTEMPTS + 1):
        try:
            sys.stdout.write(fetch_or_create(dsn))
            return 0
        except Exception as exc:  # noqa: BLE001 — any failure is worth retrying
            last_error = exc
            print(
                f"bootstrap_key: attempt {attempt}/{ATTEMPTS} failed: {exc}",
                file=sys.stderr,
            )
            time.sleep(BACKOFF_SECONDS)

    print(f"bootstrap_key: giving up: {last_error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
