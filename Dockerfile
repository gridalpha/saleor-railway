# Saleor on Railway.
#
# One image serves three roles — the GraphQL API, the Celery worker and the Celery
# beat scheduler — selected at runtime by SALEOR_ROLE. Nothing about Saleor itself is
# rebuilt: this is the published image plus the boot-time steps Railway needs.
#
#   * RSA_PRIVATE_KEY is mandatory when DEBUG=False and is a multi-line PEM, which no
#     Railway variable can express. It is generated once and elected through the shared
#     Postgres so the API, worker and beat all load the same key.
#   * WhiteNoise serves STATIC_ROOT, which the published image collects but never serves.
#   * The worker and beat get a real HTTP health endpoint; Celery serves none.
FROM ghcr.io/saleor/saleor:3.23

USER root
WORKDIR /app

# WhiteNoise serves /static/ (the logo every transactional email links to). Nothing else
# in the image serves it, so those images 404 in every message without this.
RUN python3 -m pip install --no-cache-dir --break-system-packages "whitenoise==6.12.0"

COPY railway_settings.py /app/railway_settings.py
COPY railway/ /app/railway/

RUN chmod +x /app/railway/*.sh \
  && bash -n /app/railway/entrypoint.sh \
  && bash -n /app/railway/predeploy.sh \
  && bash -n /app/railway/rsa_key.sh \
  && python3 -m compileall -q /app/railway_settings.py /app/railway/

ENV DJANGO_SETTINGS_MODULE=railway_settings \
    SALEOR_ROLE=api

EXPOSE 8000
CMD ["/app/railway/entrypoint.sh"]
