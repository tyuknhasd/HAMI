"""API endpoints to configure and control the Telegram bot from the panel UI."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import get_current_admin
from ..database import get_db
from .. import bot_service

router = APIRouter(prefix="/api/bot", tags=["bot"], dependencies=[Depends(get_current_admin)])


@router.get("/status")
def bot_status():
    return bot_service.get_status()


@router.post("/start")
def bot_start():
    ok = bot_service.start_bot()
    if not ok:
        raise HTTPException(status_code=400, detail="Bot token is not set. Save the token first.")
    return bot_service.get_status()


@router.post("/stop")
def bot_stop():
    bot_service.stop_bot()
    return {"ok": True, "running": False}


@router.post("/config")
def bot_config(payload: dict, db: Session = Depends(get_db)):
    """Save bot token + admin ids. Token is validated against the Telegram API."""
    token = (payload.get("token") or "").strip()
    admin_ids = (payload.get("admin_ids") or "").strip()

    if token:
        # quick validation before persisting
        import httpx
        try:
            with httpx.Client(timeout=15) as c:
                r = c.post(f"https://api.telegram.org/bot{token}/getMe")
                data = r.json()
            if not data.get("ok"):
                raise HTTPException(status_code=400, detail=f"Invalid token: {data.get('description', 'getMe failed')}")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Could not reach Telegram API: {e}")

    if token:
        bot_service.set_setting(db, "TELEGRAM_BOT_TOKEN", token)
    if admin_ids:
        bot_service.set_setting(db, "TELEGRAM_ADMIN_IDS", admin_ids)

    # if the bot was already running, restart it with the new token so the
    # change takes effect immediately
    if bot_service.STATE["running"]:
        bot_service.start_bot(force=True)

    return {"ok": True, "running": bot_service.STATE["running"], **bot_service.get_status()}