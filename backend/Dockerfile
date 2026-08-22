FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl unzip supervisor ca-certificates nginx gettext-base \
    && rm -rf /var/lib/apt/lists/*

# --- install Xray-core (official binary) ---
ARG XRAY_VERSION=v25.1.1
RUN curl -L -o /tmp/xray.zip \
    https://github.com/XTLS/Xray-core/releases/download/${XRAY_VERSION}/Xray-linux-64.zip \
    && unzip /tmp/xray.zip -d /usr/local/bin \
    && chmod +x /usr/local/bin/xray \
    && rm /tmp/xray.zip \
    && mkdir -p /etc/xray \
    && echo '{"log":{"loglevel":"warning"},"inbounds":[],"outbounds":[{"protocol":"freedom","tag":"direct"}]}' > /etc/xray/config.json

# --- install mtg (MTProto proxy) so MTProto ALSO works on Railway ---
ARG MTG_VERSION=v2.2.8
RUN curl -L -o /tmp/mtg.tar.gz \
    https://github.com/9seconds/mtg/releases/download/${MTG_VERSION}/mtg-2.2.8-linux-amd64.tar.gz \
    && tar -xzf /tmp/mtg.tar.gz --strip-components=1 -C /usr/local/bin \
    && chmod +x /usr/local/bin/mtg \
    && rm /tmp/mtg.tar.gz \
    && mkdir -p /etc/mtg \
    # Placeholder secret so mtg never crashes on boot with an empty file;
    # the panel rewrites this file whenever MTProto links are created.
    # (fixed hex, no xxd dependency on slim)
    && printf 'secret = "ee0123456789abcdef0123456789abcdef7767772e6d6963726f736f66742e636f6d"\nbind-to = "0.0.0.0:3128"\n' > /etc/mtg/secrets.toml

WORKDIR /app
COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY backend/app /app/app
COPY frontend /app/frontend
COPY backend/supervisord.conf /etc/supervisor/conf.d/hami.conf
COPY backend/nginx-internal.conf.template /app/nginx-internal.conf.template
COPY backend/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

EXPOSE 8000 8443 8444 8445 8446 8447 8448 3128

CMD ["/app/entrypoint.sh"]