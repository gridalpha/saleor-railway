# Sourced, not executed. Puts the shared RSA signing key in the environment.
#
# Saleor will not start with DEBUG=False unless RSA_PRIVATE_KEY holds a PEM key, and the
# API, worker and beat must all hold the *same* one. See railway/bootstrap_key.py for
# why no Railway variable can carry it.

if [ -n "${RSA_PRIVATE_KEY:-}" ]; then
  printf '[railway] RSA_PRIVATE_KEY supplied by the operator\n'
else
  printf '[railway] electing the shared RSA signing key through the database\n'
  RSA_PRIVATE_KEY="$(python3 /app/railway/bootstrap_key.py)"
  export RSA_PRIVATE_KEY
  printf '[railway] RSA signing key loaded (%s bytes)\n' "${#RSA_PRIVATE_KEY}"
fi
