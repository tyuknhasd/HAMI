#!/bin/sh
set -e

# Railway sets PORT when TCP protocol is used; with an HTTP domain attached
# it may instead expose RAILWAY_TCP_PROXY_PORT / RAILWAY_HEALTHCHECK_PORT.
# Detect all of them so nginx always listens on the port the edge forwards to.
if [ -n "${PORT:-}" ]; then
    LISTEN_PORT="$PORT"
elif [ -n "${RAILWAY_TCP_PROXY_PORT:-}" ]; then
    LISTEN_PORT="$RAILWAY_TCP_PROXY_PORT"
elif [ -n "${RAILWAY_HEALTHCHECK_PORT:-}" ]; then
    LISTEN_PORT="$RAILWAY_HEALTHCHECK_PORT"
else
    LISTEN_PORT="8000"
fi

# Render nginx template with the detected port.
export PORT="$LISTEN_PORT"
envsubst '${PORT}' < /app/nginx-internal.conf.template > /etc/nginx/conf.d/default.conf

echo "[entrypoint] nginx listening on PORT=$LISTEN_PORT"
exec supervisord -n -c /etc/supervisor/supervisord.conf