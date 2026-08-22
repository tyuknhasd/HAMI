import enum
import secrets
import uuid
from datetime import datetime

from sqlalchemy import (
    Column, String, Integer, BigInteger, Boolean, DateTime, Enum, ForeignKey, Float
)
from sqlalchemy.orm import relationship

from .database import Base


def gen_uuid():
    return str(uuid.uuid4())


def gen_short_id():
    # 8 url-safe chars (~48 bits entropy) -- short enough to type/share,
    # long enough that guessing one isn't practical.
    return secrets.token_urlsafe(6)


class Protocol(str, enum.Enum):
    vless_ws = "vless_ws"
    vless_reality = "vless_reality"
    vless_xhttp = "vless_xhttp"
    trojan_ws = "trojan_ws"
    trojan_reality = "trojan_reality"
    shadowsocks = "shadowsocks"


class ProxyLink(Base):
    __tablename__ = "proxy_links"

    id = Column(Integer, primary_key=True, index=True)
    uuid = Column(String, unique=True, index=True, default=gen_uuid)
    label = Column(String, default="")
    protocol = Column(Enum(Protocol), nullable=False)

    # client credential (vless/trojan uuid or ss password)
    client_id = Column(String, unique=True, index=True, default=gen_uuid)

    # limits
    traffic_limit_bytes = Column(BigInteger, default=0)   # 0 = unlimited
    traffic_used_bytes = Column(BigInteger, default=0)
    expires_at = Column(DateTime, nullable=True)           # null = never

    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_synced_bytes = Column(BigInteger, default=0)  # last raw counter read from xray stats

    # when true, connect URLs are built with fp/cs anti-DPI hardening params
    # (see link_builder.ANTI_FILTER_FP / ANTI_FILTER_CS)
    anti_filter = Column(Boolean, default=False)

    # groups multiple links (e.g. reality + ws + ss for the same person)
    # under one subscription URL: GET /sub/{sub_id}
    sub_id = Column(String, index=True, default=gen_short_id)

    # XTLS Vision (vless_reality only) + client-side Mux for ws/xhttp/trojan-ws.
    # See link_builder.py / xray_manager.py for what each protocol actually gets.
    high_speed = Column(Boolean, default=False)


class TrafficSample(Base):
    __tablename__ = "traffic_samples"

    id = Column(Integer, primary_key=True, index=True)
    link_id = Column(Integer, ForeignKey("proxy_links.id"))
    bytes_delta = Column(BigInteger, default=0)
    recorded_at = Column(DateTime, default=datetime.utcnow)

    link = relationship("ProxyLink")


class MTProtoLink(Base):
    __tablename__ = "mtproto_links"

    id = Column(Integer, primary_key=True, index=True)
    label = Column(String, default="")
    secret = Column(String, nullable=False)       # fake-tls secret (ee + hex + domain)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Admin(Base):
    """Single admin account stored in the DB so the password can be changed
    from the panel UI without touching Railway env vars."""
    __tablename__ = "admins"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Setting(Base):
    """Generic key/value store for panel settings (e.g. Telegram bot config)
    that must survive a redeploy and be editable from the UI."""
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String, unique=True, index=True, nullable=False)
    value = Column(String, default="")
