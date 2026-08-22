"""
Xray-core controller: builds config.json from active links, reloads the
running process, and reads back per-user traffic counters.
"""
import json
import os
import secrets as _secrets
import subprocess
from typing import List

from sqlalchemy.orm import Session

from .config import settings
from .models import ProxyLink, Protocol

INBOUND_PORTS = {
    Protocol.vless_ws: 8443,
    Protocol.vless_reality: 8444,
    Protocol.vless_xhttp: 8445,
    Protocol.trojan_ws: 8446,
    Protocol.trojan_reality: 8447,
    Protocol.shadowsocks: 8448,
}


def _client_block(link: ProxyLink) -> dict:
    if link.protocol == Protocol.vless_reality:
        # Vision only works when Xray itself terminates the TLS/Reality
        # handshake (true here -- Reality is never behind the Nginx edge).
        # It's VLESS-only; Trojan has no flow field at all.
        flow = "xtls-rprx-vision" if getattr(link, "high_speed", False) else ""
        return {"id": link.client_id, "email": link.uuid, "flow": flow}
    if link.protocol in (Protocol.vless_ws, Protocol.vless_xhttp):
        return {"id": link.client_id, "email": link.uuid, "flow": ""}
    if link.protocol in (Protocol.trojan_ws, Protocol.trojan_reality):
        return {"password": link.client_id, "email": link.uuid}
    if link.protocol == Protocol.shadowsocks:
        return {"password": link.client_id, "email": link.uuid, "method": "chacha20-ietf-poly1305"}
    return {}


def build_config(active_links: List[ProxyLink]) -> dict:
    grouped: dict = {p: [] for p in Protocol}
    for link in active_links:
        grouped[link.protocol].append(link)

    inbounds = []

    def make_inbound(protocol_key: Protocol, xray_protocol: str, stream: dict, extra: dict = None):
        clients = [_client_block(l) for l in grouped[protocol_key]]
        if not clients:
            return None
        settings_block = {"clients": clients, "decryption": "none"} if xray_protocol == "vless" else \
                          {"clients": clients} if xray_protocol == "trojan" else \
                          {"clients": clients, "network": "tcp,udp"}
        if extra:
            settings_block.update(extra)
        return {
            "tag": f"in-{protocol_key.value}",
            "listen": "0.0.0.0",
            "port": INBOUND_PORTS[protocol_key],
            "protocol": xray_protocol,
            "settings": settings_block,
            "streamSettings": stream,
        }

    # FIX: TLS is terminated by Nginx / Railway edge before it reaches Xray,
    # so every internal inbound is plain (security:"none"). No cert files
    # are needed inside the container anymore.
    ws_stream = {
        "network": "ws",
        "wsSettings": {"path": "/hami-ws"},
        "security": "none",
    }
    # FIX: Trojan-WS gets its own path so VLESS-WS and Trojan-WS don't
    # collide on /hami-ws (they are different inbound tags on the same port).
    trojan_ws_stream = {
        "network": "ws",
        "wsSettings": {"path": "/hami-trojan-ws"},
        "security": "none",
    }
    xhttp_stream = {
        "network": "xhttp",
        "xhttpSettings": {"path": "/hami-xhttp", "mode": "auto"},
        "security": "none",
    }
    reality_stream = {
        "network": "tcp",
        "security": "reality",
        "realitySettings": {
            "show": False,
            "dest": settings.REALITY_DEST,
            "xver": 0,
            "serverNames": [s.strip() for s in settings.REALITY_SERVER_NAMES.split(",") if s.strip()],
            "privateKey": settings.REALITY_PRIVATE_KEY,
            "shortIds": [settings.REALITY_SHORT_ID] if settings.REALITY_SHORT_ID else [""],
        },
    }
    plain_stream = {"network": "tcp"}

    inbounds.append(make_inbound(Protocol.vless_ws, "vless", ws_stream))
    # FIX (CRITICAL): xray crashes at startup with 'empty "privateKey"' when
    # REALITY_PRIVATE_KEY is unset -- which kills EVERY protocol (even WS).
    # Only add Reality inbounds when the keys are actually configured.
    if settings.REALITY_PRIVATE_KEY:
        inbounds.append(make_inbound(Protocol.vless_reality, "vless", reality_stream))
        inbounds.append(make_inbound(Protocol.trojan_reality, "trojan", reality_stream))
    else:
        inbounds.append(None)
        inbounds.append(None)
    inbounds.append(make_inbound(Protocol.vless_xhttp, "vless", xhttp_stream))
    inbounds.append(make_inbound(Protocol.trojan_ws, "trojan", trojan_ws_stream))
    inbounds.append(make_inbound(Protocol.shadowsocks, "shadowsocks", plain_stream))
    inbounds = [i for i in inbounds if i]

    # Always-on Xray API inbound so the panel can query live traffic stats.
    inbounds.append({
        "tag": "api-in",
        "listen": "127.0.0.1",
        "port": settings.XRAY_API_PORT,
        "protocol": "dokodemo-door",
        "settings": {"address": "127.0.0.1"},
    })

    config = {
        "log": {"loglevel": "warning"},
        "api": {"tag": "api", "services": ["StatsService", "HandlerService"]},
        "stats": {},
        "policy": {
            "levels": {"0": {"statsUserUplink": True, "statsUserDownlink": True}},
            "system": {"statsInboundUplink": True, "statsInboundDownlink": True},
        },
        "inbounds": inbounds,
        "outbounds": [
            {"protocol": "freedom", "tag": "direct"},
            {"protocol": "blackhole", "tag": "blocked"},
        ],
        "routing": {
            "rules": [
                {"type": "field", "inboundTag": ["api-in"], "outboundTag": "api"},
            ]
        },
    }
    return config


def apply_config(db: Session):
    active = db.query(ProxyLink).filter(ProxyLink.is_active == True).all()  # noqa: E712
    config = build_config(active)
    try:
        os.makedirs(os.path.dirname(settings.XRAY_CONFIG_PATH), exist_ok=True)
        with open(settings.XRAY_CONFIG_PATH, "w") as f:
            json.dump(config, f, indent=2)
        _reload_xray()
    except OSError:
        # Local dev without the /etc/xray path -- just skip writing.
        pass


def _reload_xray():
    """Restart the xray process. In the Docker image this is managed by
    supervisord, so we signal it to restart the xray program."""
    try:
        subprocess.run(["supervisorctl", "restart", "xray"], check=False, timeout=10)
    except FileNotFoundError:
        # local dev without supervisor -- no-op
        pass


# --- MTProto secret sync (used by the panel API) ---

def write_mtg_secret_list(secrets: List[str]):
    """Write a valid TOML config for mtg with the FIRST active secret (mtg
    only supports one secret per process), then restart mtg so the new secret
    is loaded. Works on Railway (mtg inside container, supervised) and VPS
    (mtg sidecar mounting the same config file)."""
    try:
        import secrets as _secrets  # module; param is named `secrets`
        secret = secrets[0] if secrets else settings.MTG_SECRET
        if not secret:
            secret = "ee" + _secrets.token_hex(16) + (
                settings.REALITY_SERVER_NAMES.split(",")[0].strip() or "www.microsoft.com"
            ).encode().hex()
        os.makedirs(os.path.dirname(settings.MTG_CONFIG_PATH), exist_ok=True)
        with open(settings.MTG_CONFIG_PATH, "w") as f:
            f.write(f'secret = "{secret}"\n')
            f.write(f'bind-to = "0.0.0.0:{settings.MTG_PORT}"\n')
        _restart_mtg()
    except OSError:
        pass


def _restart_mtg():
    try:
        subprocess.run(["supervisorctl", "restart", "mtg"], check=False, timeout=10)
    except FileNotFoundError:
        pass


def read_stats() -> dict:
    """Returns {email: bytes_total} using the xray api statsquery CLI.
    Falls back to an empty dict if xray/api isn't reachable (e.g. local dev)."""
    try:
        out = subprocess.run(
            [settings.XRAY_BIN, "api", "statsquery",
             f"--server=127.0.0.1:{settings.XRAY_API_PORT}"],
            capture_output=True, text=True, timeout=10,
        )
        data = json.loads(out.stdout or "{}")
    except Exception:
        return {}

    result: dict = {}
    for stat in data.get("stat", []):
        # name format: "user>>>{email}>>>traffic>>>{uplink|downlink}"
        parts = stat["name"].split(">>>")
        if len(parts) == 4 and parts[0] == "user":
            email = parts[1]
            result[email] = result.get(email, 0) + int(stat.get("value", 0))
    return result

# --- Network tuning (TCP BBR) --------------------------------------------
# Congestion-control choice affects throughput/latency for every protocol
# equally -- it's a kernel setting, nothing to do with Xray itself. Only
# works when the panel process can actually touch the host's sysctl, i.e.
# a VPS deployment with root (or a privileged container sharing the host
# net namespace). On Railway/managed hosting this will correctly report
# itself as unavailable -- there's no host kernel to reach.

_SYSCTL_CONF_LINE_QDISC = "net.core.default_qdisc = fq"
_SYSCTL_CONF_LINE_CC = "net.ipv4.tcp_congestion_control = bbr"
_SYSCTL_CONF_PATH = "/etc/sysctl.d/99-hami-bbr.conf"


def get_network_status() -> dict:
    try:
        with open("/proc/sys/net/ipv4/tcp_congestion_control") as f:
            current = f.read().strip()
    except OSError:
        return {"available": False, "current": None, "bbr_active": False, "reason": "no /proc access"}

    try:
        with open("/proc/sys/net/ipv4/tcp_available_congestion_control") as f:
            available_algos = f.read().strip().split()
    except OSError:
        available_algos = []

    return {
        "available": True,
        "current": current,
        "bbr_active": current == "bbr",
        "bbr_loadable": "bbr" in available_algos,
    }


def enable_bbr() -> dict:
    """Best-effort: load the bbr module, flip the two sysctls, and persist
    them so the choice survives a reboot. Returns what actually happened
    instead of raising, since failure here is expected on non-root/managed
    hosts and the panel should keep working either way."""
    try:
        subprocess.run(["modprobe", "tcp_bbr"], check=False, timeout=10)

        subprocess.run(
            ["sysctl", "-w", "net.core.default_qdisc=fq"],
            check=True, timeout=10, capture_output=True,
        )
        subprocess.run(
            ["sysctl", "-w", "net.ipv4.tcp_congestion_control=bbr"],
            check=True, timeout=10, capture_output=True,
        )

        try:
            with open(_SYSCTL_CONF_PATH, "w") as f:
                f.write(_SYSCTL_CONF_LINE_QDISC + "\n" + _SYSCTL_CONF_LINE_CC + "\n")
            persisted = True
        except OSError:
            persisted = False  # applied for this boot, but won't survive a restart

        return {"ok": True, "persisted": persisted, **get_network_status()}
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError, PermissionError) as e:
        return {"ok": False, "error": str(e), **get_network_status()}
