"""Telegram bot for HAMI panel.

Long-polling bot (no webhook needed) that mirrors the panel's full control:
list links, create with any protocol + limits, rename, toggle, delete, show
full details (connect URL + QR + sub), stats.

Config (bot token + admin ids) is kept in the DB settings table so it can be
changed from the panel UI without a redeploy; env vars act as defaults.

Run inside the FastAPI process as a daemon thread (started at app startup,
restartable via /api/system/bot endpoints).
"""
from __future__ import annotations

import asyncio
import html
import re
import threading
import time
from datetime import datetime, timedelta

import httpx

from .config import settings as app_settings
from .database import SessionLocal
from .models import MTProtoLink, ProxyLink
from .xray_manager import apply_config

TELEGRAM_API = "https://api.telegram.org/bot{token}"

PROTO_LABEL = {
    "vless_ws": "VLESS + WS",
    "vless_reality": "VLESS + Reality",
    "vless_xhttp": "VLESS + XHTTP",
    "trojan_ws": "Trojan + WS",
    "trojan_reality": "Trojan + Reality",
    "shadowsocks": "Shadowsocks",
}

# --- runtime state -----------------------------------------------------------
STATE = {
    "running": False,
    "thread": None,
    "token_set": False,
    "admin_ids": [],
    "username": "",
    "last_error": "",
    "started_at": None,
    "_token": "",
}


# --- settings helpers ---------------------------------------------------------
def get_setting(db, key: str, default: str = "") -> str:
    from .models import Setting

    row = db.query(Setting).filter(Setting.key == key).first()
    return row.value if row else default


def set_setting(db, key: str, value: str) -> None:
    from .models import Setting

    row = db.query(Setting).filter(Setting.key == key).first()
    if row:
        row.value = value
    else:
        db.add(Setting(key=key, value=value))
    db.commit()


def current_token() -> str:
    db = SessionLocal()
    try:
        return get_setting(db, "TELEGRAM_BOT_TOKEN") or app_settings.TELEGRAM_BOT_TOKEN or ""
    finally:
        db.close()


def current_admin_ids() -> list:
    db = SessionLocal()
    try:
        raw = (
            get_setting(db, "TELEGRAM_ADMIN_IDS")
            or app_settings.TELEGRAM_ADMIN_IDS
            or ""
        )
    finally:
        db.close()
    return [x.strip() for x in raw.replace(";", ",").split(",") if x.strip()]


def is_admin(user_id) -> bool:
    return str(user_id) in current_admin_ids()


# --- telegram API helpers -----------------------------------------------------
def _api(token: str, method: str, **params):
    with httpx.Client(timeout=25) as c:
        r = c.post(f"{TELEGRAM_API.format(token=token)}/{method}", json=params)
        return r.json()


def _send(token: str, chat_id, text: str) -> None:
    """Try HTML first; fall back to plain text if Telegram rejects entities."""
    if chat_id is None:
        return
    try:
        _api(token, "sendMessage", chat_id=chat_id, text=text[:4000], parse_mode="HTML")
    except Exception:
        try:
            plain = html.unescape(text)
            plain = re.sub(r"</?(b|code|i|a)[^>]*>", "", plain)
            _api(token, "sendMessage", chat_id=chat_id, text=plain[:4000])
        except Exception:
            pass


def _fmt_gb(b):
    return f"{b / (1024 ** 3):.2f} GB"


def _parse_expiry(text: str):
    """Accept '10' (days), '10d', '2026-12-01'."""
    t = text.strip().lower()
    if not t:
        return None
    m = re.match(r"^(\d+)\s*d$", t)
    if m:
        return datetime.utcnow() + timedelta(days=int(m.group(1)))
    m = re.match(r"^(\d+)$", t)
    if m:
        return datetime.utcnow() + timedelta(days=int(m.group(1)))
    try:
        return datetime.strptime(t, "%Y-%m-%d")
    except ValueError:
        return None


def _expiry_str(link) -> str:
    if not link.expires_at:
        return "∞"
    return link.expires_at.strftime("%Y-%m-%d")


def _flag(v):
    return "✅" if v else "—"


# --- command handlers ----------------------------------------------------------
async def _handle(msg: dict, token: str) -> None:
    chat_id = msg.get("chat", {}).get("id")
    user = msg.get("from", {})
    uid = user.get("id")
    text = (msg.get("text") or "").strip()
    if not text:
        return

    if not is_admin(uid):
        _send(
            token,
            chat_id,
            "⛔️ شما ادمین پنل نیستید.\n"
            f"آیدی عددی شما: <code>{uid}</code>\n"
            "این آیدی را در پنل → تنظیمات → ربات تلگرام → «آیدی ادمین‌ها» وارد کنید.",
        )
        return

    cmd, _, arg = text.partition(" ")
    cmd = cmd.lower().split("@")[0]
    args = arg.split()

    db = SessionLocal()
    try:
        if cmd in ("/start", "/help"):
            _send(token, chat_id, (
                "🎛 <b>ربات کامل پنل HAMI</b>\n\n"
                "📋 <b>لینک‌ها</b>\n"
                "/links — لیست همه لینک‌ها\n"
                "/link &lt;id&gt; — جزئیات کامل + QR\n"
                "/sub &lt;id&gt; — لینک سابسکریپشن\n\n"
                "➕ <b>ساخت لینک</b>\n"
                "/new &lt;نام&gt; — VLESS+WS (پیش‌فرض)\n"
                "/new_reality &lt;نام&gt; — VLESS+Reality\n"
                "/new_xhttp &lt;نام&gt; — VLESS+XHTTP\n"
                "/new_trojan &lt;نام&gt; — Trojan+WS\n"
                "/new_ss &lt;نام&gt; — Shadowsocks\n"
                "امکانات: <code>l=10g e=30d af hs</code>\n"
                "مثال: <code>/new امیر l=50g e=90d af hs</code>\n\n"
                "⚙️ <b>مدیریت</b>\n"
                "/rename &lt;id&gt; &lt;نام&gt;\n"
                "/toggle &lt;id&gt;\n"
                "/delete &lt;id&gt;\n"
                "/traffic &lt;id&gt; &lt;GB|off&gt;\n"
                "/expire &lt;id&gt; &lt;days|off&gt;\n\n"
                "📊 <b>سایر</b>\n"
                "/stats — آمار پنل\n"
                "/mtproto — لیست پروکسی تلگرام\n"
                "/id — آیدی عددی شما"
            ))
        elif cmd == "/id":
            _send(token, chat_id, f"آیدی عددی شما: <code>{uid}</code>")
        elif cmd == "/links":
            links = db.query(ProxyLink).order_by(ProxyLink.created_at.desc()).all()
            if not links:
                _send(token, chat_id, "📭 هنوز لینکی ساخته نشده.")
                return
            lines = [f"<b>لینک‌ها ({len(links)})</b>"]
            for l in links:
                st = "🟢" if l.is_active else "🔴"
                flag = " 🛡" if l.anti_filter else ""
                hs = " ⚡" if l.high_speed else ""
                lines.append(
                    f"{st} #{l.id} {html.escape(l.label or 'بی‌نام')} — "
                    f"{PROTO_LABEL.get(l.protocol.value, l.protocol.value)}{flag}{hs}"
                )
            _send(token, chat_id, "\n".join(lines))
        elif cmd == "/link":
            try:
                lid = int(args[0])
            except (IndexError, ValueError):
                _send(token, chat_id, "آیدی عددی بفرستید، مثل: /link 3")
                return
            link = db.query(ProxyLink).get(lid)
            if not link:
                _send(token, chat_id, "❌ لینک پیدا نشد.")
                return
            from .link_builder import build_connect_url, qr_png_base64

            url = build_connect_url(link)
            sub_domain = getattr(app_settings, 'SUB_DOMAIN', '') or app_settings.PUBLIC_DOMAIN
            sub = f"https://{sub_domain}/sub/{link.sub_id}"
            _send(token, chat_id, (
                f"🔗 <b>#{link.id} {html.escape(link.label or '')}</b>\n\n"
                f"پروتکل: {PROTO_LABEL.get(link.protocol.value, link.protocol.value)}\n"
                f"وضعیت: {'🟢 فعال' if link.is_active else '🔴 غیرفعال'}\n"
                f"ترافیک: {_fmt_gb(link.traffic_used_bytes)} / "
                f"{_fmt_gb(link.traffic_limit_bytes) if link.traffic_limit_bytes else '∞'}\n"
                f"انقضا: {_expiry_str(link)}\n"
                f"ضد فیلتر: {_flag(link.anti_filter)}  |  پرسرعت: {_flag(link.high_speed)}\n\n"
                f"<code>{html.escape(url)}</code>\n\n"
                f"📎 ساب: <code>{html.escape(sub)}</code>"
            ))
            try:
                qr = qr_png_base64(url)
                _api(token, "sendPhoto", chat_id=chat_id, photo=qr, caption=f"QR لینک #{lid}")
            except Exception:
                pass
        elif cmd == "/sub":
            try:
                lid = int(args[0])
            except (IndexError, ValueError):
                _send(token, chat_id, "آیدی عددی بفرستید، مثل: /sub 3")
                return
            link = db.query(ProxyLink).get(lid)
            if not link:
                _send(token, chat_id, "❌ لینک پیدا نشد.")
                return
            sub_domain = getattr(app_settings, 'SUB_DOMAIN', '') or app_settings.PUBLIC_DOMAIN
            sub = f"https://{sub_domain}/sub/{link.sub_id}"
            _send(token, chat_id, f"📎 ساب لینک #{lid}:\n<code>{html.escape(sub)}</code>")
        elif cmd == "/stats":
            total = db.query(ProxyLink).count()
            active = db.query(ProxyLink).filter(ProxyLink.is_active.is_(True)).count()
            used = sum(l.traffic_used_bytes for l in db.query(ProxyLink).all())
            mt = db.query(MTProtoLink).count()
            _send(token, chat_id, (
                f"📊 <b>آمار پنل</b>\n"
                f"کل لینک‌ها: {total}\n"
                f"فعال: {active}\n"
                f"مصرف کل: {_fmt_gb(used)}\n"
                f"پروکسی تلگرام (MTProto): {mt}"
            ))
        elif cmd == "/mtproto":
            links = db.query(MTProtoLink).all()
            if not links:
                _send(token, chat_id, "📭 پروکسی تلگرام وجود ندارد.")
                return
            lines = [f"<b>پروکسی‌های تلگرام ({len(links)})</b>"]
            for l in links:
                st = "🟢" if l.is_active else "🔴"
                lines.append(f"{st} #{l.id} {html.escape(l.label or '')} — mtproto://...")
            _send(token, chat_id, "\n".join(lines))
        elif cmd in ("/new", "/new_reality", "/new_xhttp", "/new_trojan", "/new_ss"):
            proto_map = {
                "/new": "vless_ws",
                "/new_reality": "vless_reality",
                "/new_xhttp": "vless_xhttp",
                "/new_trojan": "trojan_ws",
                "/new_ss": "shadowsocks",
            }
            proto = proto_map[cmd]
            label = ""
            limit_gb = 0
            days = 0
            anti = False
            hs = False
            # options: l=10g e=30d af hs
            for piece in args:
                if piece.startswith("l="):
                    m = re.match(r"l=(\d+(?:\.\d+)?)\s*g?", piece, re.I)
                    if m:
                        limit_gb = float(m.group(1))
                elif piece.startswith("e="):
                    days = int(re.sub(r"\D", "", piece)) if re.search(r"\d", piece) else 0
                elif piece.lower() == "af":
                    anti = True
                elif piece.lower() == "hs":
                    hs = True
                else:
                    if not label:
                        label = piece
                    else:
                        label += " " + piece
            label = label.strip() or "Telegram"
            link = ProxyLink(
                label=label,
                protocol=proto,
                traffic_limit_bytes=int(limit_gb * (1024 ** 3)) if limit_gb else 0,
                expires_at=(datetime.utcnow() + timedelta(days=days)) if days else None,
                anti_filter=anti,
                high_speed=hs,
            )
            db.add(link)
            db.commit()
            db.refresh(link)
            apply_config(db)
            from .link_builder import build_connect_url

            url = build_connect_url(link)
            sub_domain = getattr(app_settings, 'SUB_DOMAIN', '') or app_settings.PUBLIC_DOMAIN
            sub = f"https://{sub_domain}/sub/{link.sub_id}"
            _send(token, chat_id, (
                f"✅ لینک جدید ساخته شد (#{link.id})\n\n"
                f"نام: {html.escape(link.label)}\n"
                f"پروتکل: {PROTO_LABEL.get(proto, proto)}\n"
                f"ترافیک: {_fmt_gb(link.traffic_limit_bytes) if limit_gb else '∞'}\n"
                f"انقضا: {_expiry_str(link)}\n"
                f"ضد فیلتر: {_flag(anti)}  |  پرسرعت: {_flag(hs)}\n\n"
                f"<code>{html.escape(url)}</code>\n\n"
                f"📎 ساب: <code>{html.escape(sub)}</code>"
            ))
        elif cmd == "/rename":
            try:
                lid = int(args[0])
                new_label = " ".join(args[1:]).strip()
            except (IndexError, ValueError):
                _send(token, chat_id, "مثال: /rename 3 علی")
                return
            link = db.query(ProxyLink).get(lid)
            if not link:
                _send(token, chat_id, "❌ لینک پیدا نشد.")
                return
            if not new_label:
                _send(token, chat_id, "نام جدید را بنویسید: /rename 3 علی")
                return
            link.label = new_label
            db.commit()
            _send(token, chat_id, f"✏️ نام لینک #{lid} شد: {html.escape(new_label)}")
        elif cmd == "/toggle":
            try:
                lid = int(args[0])
            except (IndexError, ValueError):
                _send(token, chat_id, "آیدی عددی بفرستید، مثل: /toggle 3")
                return
            link = db.query(ProxyLink).get(lid)
            if not link:
                _send(token, chat_id, "❌ لینک پیدا نشد.")
                return
            link.is_active = not link.is_active
            db.commit()
            apply_config(db)
            _send(token, chat_id, f"{'🟢 فعال شد' if link.is_active else '🔴 غیرفعال شد'} — #{lid}")
        elif cmd == "/delete":
            try:
                lid = int(args[0])
            except (IndexError, ValueError):
                _send(token, chat_id, "آیدی عددی بفرستید، مثل: /delete 3")
                return
            link = db.query(ProxyLink).get(lid)
            if not link:
                _send(token, chat_id, "❌ لینک پیدا نشد.")
                return
            db.delete(link)
            db.commit()
            apply_config(db)
            _send(token, chat_id, f"🗑 لینک #{lid} حذف شد.")
        elif cmd == "/traffic":
            try:
                lid = int(args[0])
                spec = args[1].lower() if len(args) > 1 else ""
            except (IndexError, ValueError):
                _send(token, chat_id, "مثال: /traffic 3 50g یا /traffic 3 off")
                return
            link = db.query(ProxyLink).get(lid)
            if not link:
                _send(token, chat_id, "❌ لینک پیدا نشد.")
                return
            if not spec:
                _send(token, chat_id, f"سقف فعلی: {_fmt_gb(link.traffic_limit_bytes) if link.traffic_limit_bytes else '∞ (نامحدود)'}.\nمثال: /traffic {lid} 50g")
                return
            if spec in ("off", "0", "0g"):
                link.traffic_limit_bytes = 0
            else:
                m = re.match(r"^(\d+(?:\.\d+)?)\s*g?$", spec)
                if not m:
                    _send(token, chat_id, "فرمت اشتباه. مثال: /traffic 3 50g")
                    return
                link.traffic_limit_bytes = int(float(m.group(1)) * (1024 ** 3))
            db.commit()
            apply_config(db)
            _send(token, chat_id, f"📦 سقف ترافیک #{lid}: {_fmt_gb(link.traffic_limit_bytes) if link.traffic_limit_bytes else '∞ (نامحدود)'}")
        elif cmd == "/expire":
            try:
                lid = int(args[0])
                spec = args[1] if len(args) > 1 else ""
            except (IndexError, ValueError):
                _send(token, chat_id, "مثال: /expire 3 30 یا /expire 3 off")
                return
            link = db.query(ProxyLink).get(lid)
            if not link:
                _send(token, chat_id, "❌ لینک پیدا نشد.")
                return
            if not spec:
                _send(token, chat_id, f"انقضا فعلی: {_expiry_str(link)}.\nمثال: /expire {lid} 30")
                return
            if spec.lower() in ("off", "0", "never", "∞"):
                link.expires_at = None
                _send(token, chat_id, f"⏳ انقضای #{lid} برداشته شد (∞).")
            else:
                days = int(re.sub(r"\D", "", spec)) if re.search(r"\d", spec) else 0
                if not days:
                    _send(token, chat_id, "فرمت اشتباه. مثال: /expire 3 30")
                    return
                link.expires_at = datetime.utcnow() + timedelta(days=days)
                _send(token, chat_id, f"⏳ انقضای #{lid}: {link.expires_at.strftime('%Y-%m-%d')}")
            db.commit()
            apply_config(db)
        else:
            _send(token, chat_id, "دستور ناشناخته. /help بزنید.")
    finally:
        db.close()


# --- polling loop ---------------------------------------------------------------
def _run(token: str) -> None:
    offset = 0
    while STATE["running"]:
        try:
            me = _api(token, "getMe")
            if not me.get("ok"):
                STATE["last_error"] = me.get("description", "getMe failed")
                time.sleep(5)
                continue
            STATE["username"] = me.get("result", {}).get("username", "")
            STATE["last_error"] = ""
            with httpx.Client(timeout=30) as c:
                r = c.get(
                    f"{TELEGRAM_API.format(token=token)}/getUpdates",
                    params={
                        "offset": offset,
                        "timeout": 20,
                        "allowed_updates": ["message"],
                    },
                )
                data = r.json()
                if not data.get("ok"):
                    STATE["last_error"] = data.get("description", "getUpdates failed")
                    time.sleep(3)
                    continue
                for upd in data.get("result", []):
                    offset = upd["update_id"] + 1
                    msg = upd.get("message")
                    if msg:
                        try:
                            asyncio.run(_handle(msg, token))
                        except Exception as e:  # keep polling alive on handler errors
                            STATE["last_error"] = f"handler: {e}"
        except Exception as e:
            STATE["last_error"] = str(e)
            time.sleep(3)


def start_bot(force: bool = False) -> bool:
    """Start the bot thread. Idempotent: if it is already running with the
    same token, it is left alone (prevents double-polling races)."""
    token = current_token()

    thread = STATE["thread"]
    alive = thread is not None and thread.is_alive()
    if alive and STATE["running"] and not force:
        if STATE.get("_token") == token:
            return True
        stop_bot()

    if not token:
        STATE["token_set"] = False
        STATE["running"] = False
        STATE["username"] = ""
        STATE["_token"] = ""
        return False

    if STATE["running"]:
        stop_bot()

    STATE["token_set"] = True
    STATE["running"] = True
    STATE["admin_ids"] = current_admin_ids()
    STATE["_token"] = token
    STATE["started_at"] = time.time()
    STATE["last_error"] = ""
    STATE["thread"] = threading.Thread(target=_run, args=(token,), daemon=True)
    STATE["thread"].start()
    return True


def stop_bot() -> None:
    STATE["running"] = False
    if STATE["thread"]:
        STATE["thread"].join(timeout=3)
    STATE["thread"] = None


def get_status() -> dict:
    thread = STATE["thread"]
    alive = thread is not None and thread.is_alive()
    return {
        "running": STATE["running"] and alive,
        "token_set": STATE["token_set"],
        "admin_ids": current_admin_ids(),
        "username": STATE["username"],
        "last_error": STATE["last_error"],
        "started_at": STATE["started_at"],
    }