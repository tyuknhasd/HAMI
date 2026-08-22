import base64
import io
import json
from urllib.parse import quote

import qrcode

from .config import settings
from .models import ProxyLink, Protocol
from .xray_manager import INBOUND_PORTS

# --- Anti-filter (DPI-resistance) defaults -----------------------------
# Same utls fingerprint + cipher suite order real Chrome uses, so the TLS
# ClientHello doesn't stand out to SNI-based filtering. Only meaningful on
# security=tls transports (ws/xhttp/trojan-ws) -- reality already randomizes
# its own handshake and shadowsocks isn't TLS at all.
ANTI_FILTER_FP = "chrome"
ANTI_FILTER_CS = (
    "TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256:TLS_AES_128_GCM_SHA256:"
    "TLS_ECDHE_ECDSA_WITH_AES_256_GCM_SHA384:TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384:"
    "TLS_ECDHE_ECDSA_WITH_AES_128_GCM_SHA256:TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256:"
    "TLS_ECDHE_ECDSA_WITH_CHACHA20_POLY1305_SHA256:TLS_ECDHE_RSA_WITH_CHACHA20_POLY1305_SHA256:"
    "TLS_ECDHE_ECDSA_WITH_AES_256_CBC_SHA:TLS_ECDHE_RSA_WITH_AES_256_CBC_SHA:"
    "TLS_ECDHE_ECDSA_WITH_AES_128_CBC_SHA256:TLS_ECDHE_RSA_WITH_AES_128_CBC_SHA256"
)

# fp/cs above travel fine inside the vless:// URI itself. TLS-record
# fragmentation, however, is an outbound-app setting (Xray core reads it from
# each client's own config, not from the share link) so it can't be embedded
# in the URL. We hand it back as a copy-pasteable JSON blob instead -- the
# admin pastes this into the client's advanced/fragment settings once.
ANTI_FILTER_FRAGMENT_JSON = json.dumps({
    "fragment": {
        "packets": "tlshello",
        "length": "5-94",
        "interval": "1-1",
    }
}, ensure_ascii=False)

# --- High-speed (protocol strengthening) defaults -----------------------
# Mux is a client-side setting too (Xray reads it from the *client's* own
# outbound config, same limitation as fragment above) -- handed back as a
# copy-pasteable blob just like ANTI_FILTER_FRAGMENT_JSON.
HIGH_SPEED_MUX_JSON = json.dumps({
    "mux": {
        "enabled": True,
        "concurrency": 8,
        "xudpConcurrency": 16,
        "xudpProxyUDP443": "reject",
    }
}, ensure_ascii=False)


def _apply_anti_filter(params: dict) -> None:
    params["fp"] = ANTI_FILTER_FP
    params["cs"] = ANTI_FILTER_CS


def _qs(params: dict) -> str:
    # keep %2F-style encoding used elsewhere in this file; only cs/host/sni
    # need escaping and none of their characters collide with '&' or '='.
    return "&".join(f"{k}={quote(v, safe='')}" for k, v in params.items())


def build_connect_url(link: ProxyLink) -> str:
    host = settings.PUBLIC_DOMAIN
    worker_sni = getattr(settings, "WORKER_SNI", "").strip()
    sni_val = worker_sni if worker_sni else host
    host_header = worker_sni if worker_sni else host
    label = quote(link.label or "HAMI")
    public_port = settings.PUBLIC_PORT
    anti_filter = bool(getattr(link, "anti_filter", False))
    high_speed = bool(getattr(link, "high_speed", False))

    # FIX: WS/XHTTP/Trojan-WS go through the TLS edge (443 / PUBLIC_PORT)
    if link.protocol == Protocol.vless_ws:
        params = {"type": "ws", "security": "tls", "path": "/hami-ws", "host": host_header, "sni": sni_val}
        if anti_filter:
            _apply_anti_filter(params)
        return f"vless://{link.client_id}@{host}:{public_port}?{_qs(params)}#{label}"

    if link.protocol == Protocol.vless_xhttp:
        params = {"type": "xhttp", "security": "tls", "path": "/hami-xhttp", "host": host_header, "sni": sni_val}
        if anti_filter:
            _apply_anti_filter(params)
        return f"vless://{link.client_id}@{host}:{public_port}?{_qs(params)}#{label}"

    if link.protocol == Protocol.trojan_ws:
        params = {"type": "ws", "security": "tls", "path": "/hami-trojan-ws", "host": host_header, "sni": sni_val}
        if anti_filter:
            _apply_anti_filter(params)
        return f"trojan://{link.client_id}@{host}:{public_port}?{_qs(params)}#{label}"

    # Reality / Shadowsocks are exposed directly by Xray on their own ports
    # (VPS deployment). On Railway these stay internal -- only WS/XHTTP work
    # through the single public port.
    if link.protocol == Protocol.vless_reality:
        port = INBOUND_PORTS[Protocol.vless_reality]
        sni = settings.REALITY_SERVER_NAMES.split(",")[0].strip()
        params = {
            "type": "tcp", "security": "reality", "pbk": settings.REALITY_PUBLIC_KEY,
            "sid": settings.REALITY_SHORT_ID, "sni": sni, "fp": "chrome",
        }
        if high_speed:
            # Vision must match the server's inbound flow exactly -- see
            # xray_manager._client_block, which sets this for the same link.
            params["flow"] = "xtls-rprx-vision"
        return f"vless://{link.client_id}@{host}:{port}?{_qs(params)}#{label}"

    if link.protocol == Protocol.trojan_reality:
        port = INBOUND_PORTS[Protocol.trojan_reality]
        sni = settings.REALITY_SERVER_NAMES.split(",")[0].strip()
        return (f"trojan://{link.client_id}@{host}:{port}"
                f"?type=tcp&security=reality&pbk={settings.REALITY_PUBLIC_KEY}"
                f"&sid={settings.REALITY_SHORT_ID}&sni={sni}&fp=chrome#{label}")

    if link.protocol == Protocol.shadowsocks:
        port = INBOUND_PORTS[Protocol.shadowsocks]
        userinfo = base64.urlsafe_b64encode(
            f"chacha20-ietf-poly1305:{link.client_id}".encode()
        ).decode().rstrip("=")
        return f"ss://{userinfo}@{host}:{port}#{label}"

    return ""


def high_speed_mux_json(link: ProxyLink) -> str | None:
    """Mux only helps transports that go through the WS/XHTTP edge -- for
    Reality, Vision (set via the flow param, both server- and URL-side)
    already gets the speed win and mixing in mux on top of Vision is not
    recommended by Xray upstream. Trojan-Reality/Shadowsocks get neither."""
    if not getattr(link, "high_speed", False):
        return None
    if link.protocol in (Protocol.vless_ws, Protocol.vless_xhttp, Protocol.trojan_ws):
        return HIGH_SPEED_MUX_JSON
    return None


def build_mtproto_url(secret: str) -> str:
    host = settings.PUBLIC_DOMAIN
    secret = secret or settings.MTG_SECRET
    return f"tg://proxy?server={host}&port={settings.MTG_PORT}&secret={secret}"


def qr_png_base64(data: str) -> str:
    img = qrcode.make(data)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def build_subscription_content(links: list[ProxyLink]) -> str:
    """Base64 body for a subscription URL: newline-joined connect URLs for
    every link, standard-base64 -- this is exactly what v2rayNG/NekoRay/etc
    expect at a `sub://` / subscription-URL endpoint."""
    urls = [build_connect_url(l) for l in links if l.is_active]
    body = "\n".join(u for u in urls if u)
    return base64.b64encode(body.encode()).decode()


def _fmt_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.2f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n:.2f} PB"


def build_subscription_page_html(links: list[ProxyLink], sub_id: str) -> str:
    """Human-friendly subscription page: served instead of the raw base64
    body when a browser (not a proxy client) opens the sub URL. Shows real
    usage/expiry per link plus a QR + copy button for the sub URL itself."""
    active = [l for l in links if l.is_active]
    total_used = sum(l.traffic_used_bytes for l in active)
    total_limit = sum(l.traffic_limit_bytes for l in active)
    expiries = [l.expires_at for l in active if l.expires_at]
    nearest_expiry = min(expiries) if expiries else None
    sub_url = f"https://{settings.SUB_DOMAIN or settings.PUBLIC_DOMAIN}/sub/{sub_id}"
    qr_b64 = qr_png_base64(sub_url)

    rows = ""
    for l in active:
        pct = (l.traffic_used_bytes / l.traffic_limit_bytes * 100) if l.traffic_limit_bytes else 0
        limit_txt = _fmt_bytes(l.traffic_limit_bytes) if l.traffic_limit_bytes else "نامحدود"
        badges = "".join([
            '<span class="tag">🛡 ضد فیلتر</span>' if l.anti_filter else "",
            '<span class="tag">⚡ پرسرعت</span>' if l.high_speed else "",
        ])
        url = build_connect_url(l)
        rows += f"""
        <div class="link-card">
          <div class="link-head">
            <strong>{l.label or 'بی‌نام'}</strong>
            <span class="proto">{l.protocol.value}</span>
            {badges}
          </div>
          <div class="link-meta">{_fmt_bytes(l.traffic_used_bytes)} از {limit_txt}
            {f'· انقضا {l.expires_at.strftime("%Y-%m-%d")}' if l.expires_at else ''}</div>
          {f'<div class="bar"><span style="width:{min(pct,100):.1f}%"></span></div>' if l.traffic_limit_bytes else ''}
          <input class="mono link-input" readonly value="{url}" onclick="this.select()">
        </div>"""

    if not active:
        rows = '<div class="empty">هیچ لینک فعالی در این ساب نیست.</div>'

    total_used_txt = _fmt_bytes(total_used)
    total_limit_txt = _fmt_bytes(total_limit) if total_limit else "نامحدود"
    expiry_txt = nearest_expiry.strftime("%Y-%m-%d") if nearest_expiry else "هیچوقت"

    return f"""<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>HAMI · اشتراک</title>
<style>
  :root {{
    --bg:#0a0e13; --bg-elev:#10161d; --surface:#141b23; --border:#232e3b;
    --text:#e7eef4; --muted:#7c8b9c; --teal:#4fe8cf; --violet:#a78bfa; --radius:16px;
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--text); font-family:Tahoma,"Segoe UI",sans-serif;
          padding:28px 16px; }}
  .wrap {{ max-width:520px; margin:0 auto; }}
  .brand {{ display:flex; align-items:center; gap:12px; margin-bottom:22px; }}
  .brand-mark {{ width:38px; height:38px; border-radius:11px;
                 background:linear-gradient(145deg, var(--teal), var(--violet)); }}
  .brand-name {{ font-size:19px; font-weight:700; }}
  .brand-sub {{ font-size:11.5px; color:var(--muted); }}
  .card {{ background:linear-gradient(180deg, var(--surface), var(--bg-elev));
           border:1px solid var(--border); border-radius:var(--radius); padding:18px; margin-bottom:14px; }}
  .qr-box {{ text-align:center; }}
  .qr-box img {{ width:170px; height:170px; border-radius:12px; background:#fff; padding:8px; }}
  .stats {{ display:flex; gap:10px; margin-top:14px; }}
  .stat {{ flex:1; text-align:center; background:var(--bg-elev); border:1px solid var(--border);
           border-radius:10px; padding:10px 6px; }}
  .stat b {{ display:block; font-size:14px; color:var(--teal); }}
  .stat span {{ font-size:10.5px; color:var(--muted); }}
  .mono {{ font-family:ui-monospace,Menlo,Consolas,monospace; direction:ltr; text-align:left; }}
  .link-input {{ width:100%; margin-top:8px; background:var(--bg-elev); border:1px solid var(--border);
                 color:var(--text); border-radius:8px; padding:9px 10px; font-size:11.5px; }}
  .btn {{ display:block; width:100%; text-align:center; padding:12px; border-radius:11px; border:none;
          background:linear-gradient(90deg, var(--teal), var(--violet)); color:#08110e; font-weight:700;
          cursor:pointer; font-size:14px; margin-top:6px; }}
  .link-card {{ border:1px solid var(--border); border-radius:12px; padding:12px; margin-top:10px; background:var(--bg-elev); }}
  .link-head {{ display:flex; align-items:center; gap:8px; flex-wrap:wrap; }}
  .proto {{ font-size:10.5px; color:var(--muted); border:1px solid var(--border); border-radius:6px; padding:1px 6px; }}
  .tag {{ font-size:10.5px; color:var(--teal); border:1px solid var(--teal); border-radius:6px; padding:1px 6px; }}
  .link-meta {{ font-size:11.5px; color:var(--muted); margin-top:4px; }}
  .bar {{ height:5px; background:var(--border); border-radius:4px; overflow:hidden; margin-top:8px; }}
  .bar span {{ display:block; height:100%; background:linear-gradient(90deg, var(--teal), var(--violet)); }}
  .empty {{ text-align:center; color:var(--muted); padding:20px; }}
  .footer {{ text-align:center; font-size:11px; color:var(--muted); margin-top:18px; }}
</style>
</head>
<body>
<div class="wrap">
  <div class="brand">
    <div class="brand-mark"></div>
    <div>
      <div class="brand-name">HAMI</div>
      <div class="brand-sub">صفحه اشتراک</div>
    </div>
  </div>

  <div class="card qr-box">
    <img src="data:image/png;base64,{qr_b64}" alt="QR">
    <input class="mono link-input" readonly value="{sub_url}" onclick="this.select()" style="margin-top:14px;">
    <button class="btn" onclick="navigator.clipboard.writeText('{sub_url}'); this.textContent='کپی شد ✓'">کپی لینک اشتراک</button>
    <div class="stats">
      <div class="stat"><b>{total_used_txt}</b><span>مصرف‌شده</span></div>
      <div class="stat"><b>{total_limit_txt}</b><span>سقف</span></div>
      <div class="stat"><b>{expiry_txt}</b><span>انقضا</span></div>
      <div class="stat"><b>{len(active)}</b><span>لینک فعال</span></div>
    </div>
  </div>

  <div class="card">
    <strong>لینک‌های این اشتراک</strong>
    {rows}
  </div>

  <div class="footer">این آدرس رو در v2rayNG / NekoRay / Hiddify و... به‌عنوان ساب اضافه کن؛ خودکار به‌روز می‌شه.</div>
</div>
</body>
</html>"""