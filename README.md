# saleor-railway

A thin wrapper that makes [Saleor](https://github.com/saleor/saleor) deployable on
Railway as a published template. It is `FROM ghcr.io/saleor/saleor:3.23` plus one
entrypoint — Saleor itself is never rebuilt.

One image serves three roles, chosen by `SALEOR_ROLE`:

| `SALEOR_ROLE` | Process | Port |
|---|---|---|
| `api` | `uvicorn saleor.asgi:application` | `8000` |
| `worker` | `celery … worker` + the health daemon | `8080` |
| `beat` | `celery … beat` (DatabaseScheduler) + the health daemon | `8080` |

## What the wrapper adds, and why

**`railway/bootstrap_key.py` — the RSA signing key.** Saleor refuses to start with
`DEBUG=False` unless `RSA_PRIVATE_KEY` holds a PEM private key, and it signs every
access token and JWKS entry with it. That value is multi-line (template variables
replace values of that shape with placeholder text), shared by all three roles (no
service can write another's environment), and must stay stable across restarts. So the
first container to boot generates it and writes it to the shared Postgres with
`ON CONFLICT DO NOTHING`; the rest read the row back. Set `RSA_PRIVATE_KEY` yourself and
this is skipped entirely.

**`railway/predeploy.sh` — migrations and the first staff account.** Both run before the
container starts, so a first boot spending minutes on Saleor's schema never eats the
health check window. The API owns the schema; the worker and beat wait for it. The staff
account is created only while *no* superuser exists, so a password changed in the
dashboard is never reverted by a redeploy.

**`railway/healthd.py` — an HTTP health endpoint for Celery.** Celery serves none, so a
worker that dies at boot would otherwise leave a green deployment behind. Both Celery
roles run their process and the daemon side by side; whichever exits first takes the
container down.

**`railway_settings.py` — WhiteNoise.** The published image collects `STATIC_ROOT` and
then serves nothing from it, so the shop logo every transactional email links to 404s.
This is the only setting not expressible as an environment variable.

**Celery concurrency.** Celery sizes its prefork pool from the *host's* core count,
which on Railway is 48. The entrypoint pins it to 4; raise it with `CELERY_CONCURRENCY`.

## Layout

```
Dockerfile              FROM the published Saleor image
railway.json            health check, pre-deploy command; applies to all three roles
railway_settings.py     DJANGO_SETTINGS_MODULE — Saleor's settings plus WhiteNoise
railway/entrypoint.sh   role dispatch
railway/predeploy.sh    migrations + first staff account (API only)
railway/rsa_key.sh      sourced by both; exports RSA_PRIVATE_KEY
railway/bootstrap_key.py
railway/create_admin.py
railway/healthd.py
```

Saleor is BSD-3-Clause. This wrapper carries no credentials; every secret arrives as a
Railway variable.
