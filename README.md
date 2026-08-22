# HAMI

Multi-protocol tunnel management panel (VLESS / Trojan / Reality / XHTTP / Shadowsocks) plus a Telegram MTProto proxy with fake-TLS and sponsor channel support.

The tunneling engine runs on official Xray-core; the panel builds config, reads stats, and manages links.

## Features

- Protocols: VLESS+WS, VLESS+Reality, VLESS+XHTTP, Trojan+WS, Trojan+Reality, Shadowsocks
- Separate Telegram MTProto proxy (via mtg) — fake-TLS + optional MTG_ADTAG (sponsor channel from @MTProxybot)
- Admin login with JWT, live stats (total links, active, total usage, last 24h usage) plus a 7-day chart
- Per-link traffic limit (GB), expiry date, instant enable/disable, QR code
- Automatic link deactivation on quota or expiry (checked every minute)
- PostgreSQL storage
- No external font/CDN dependencies

## Architecture

```
             ┌────────────┐
   Users →   │   Nginx    │  (TLS + path-based routing)
             └─────┬──────┘
        ┌──────────┼───────────┐
        ▼          ▼           ▼
   Panel (FastAPI)  Xray-core   mtg (MTProto)
        │             │
        └────► PostgreSQL
```

- Railway: only exposes one public port per container and terminates TLS itself. Inside the image, a lightweight Nginx multiplexes the panel and the `/hami-ws` / `/hami-xhttp` paths on that same port. Reality and Shadowsocks need a dedicated TCP port, which Railway doesn't provide for free — use the VPS mode for those, or Railway's paid TCP Proxy add-on.
- VPS: brought up with docker-compose, Nginx terminates TLS on 443 with a real certificate (Let's Encrypt), and the Reality/Shadowsocks ports are exposed directly. This is the more complete mode.

## Deploy on Railway (WS/XHTTP only)

1. Push this repo to your own GitHub.
2. Railway → New Project → Deploy from GitHub repo.
3. Railway picks up `railway.json` and builds from `backend/Dockerfile`.
4. Set environment variables from `.env.example`: `SECRET_KEY`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `PUBLIC_DOMAIN`.
5. Add a PostgreSQL plugin — Railway injects `DATABASE_URL` automatically.
6. Enable Public Domain and set its value in `PUBLIC_DOMAIN`.
7. Open `https://your-app.up.railway.app/dashboard`.

## Deploy on a VPS (all protocols)

```bash
git clone <repo-url> && cd hami-panel
cp .env.example .env

sudo apt install certbot -y
sudo certbot certonly --standalone -d your-domain.com

docker run --rm ghcr.io/xtls/xray-core x25519
# put the Private/Public key in .env

docker run --rm nineseconds/mtg:2 generate-secret --hex your-domain.com

docker compose up -d --build
```

Open `https://your-domain.com/dashboard`.

## Environment variables

| Variable | Description |
|---|---|
| `PUBLIC_DOMAIN` | Domain used to build outgoing connection links |
| `REALITY_PRIVATE_KEY` / `REALITY_PUBLIC_KEY` | Generate with `xray x25519` |
| `REALITY_SERVER_NAMES` | Target site Reality impersonates (must actually support TLS 1.3) |
| `MTG_SECRET` | Fake-TLS secret for MTProto |
| `MTG_ADTAG` | Sponsor channel tag from @MTProxybot (optional) |

## Open items for future work

- Hot-reload the Xray config via gRPC HandlerService instead of restarting the process
- Full MTG_ADTAG wiring and multi-secret management from the panel
- Multiple admins with separate permission levels
- TON payment integration for automated link sales
- Live connection graph (WebSocket push instead of polling)
