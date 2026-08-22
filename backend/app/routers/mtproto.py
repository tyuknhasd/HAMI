import secrets

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import get_current_admin
from ..config import settings
from ..database import get_db
from ..link_builder import build_mtproto_url
from ..models import MTProtoLink
from ..schemas import MTProtoCreate, MTProtoOut
from ..xray_manager import write_mtg_secret_list

router = APIRouter(prefix="/api/mtproto", tags=["mtproto"], dependencies=[Depends(get_current_admin)])


def _get_secret() -> str:
    """Prefers MTG_SECRET from env; if empty, builds a fresh fake-TLS secret."""
    if settings.MTG_SECRET:
        return settings.MTG_SECRET
    domain = (settings.REALITY_SERVER_NAMES.split(",")[0].strip() or "www.microsoft.com")
    return "ee" + secrets.token_hex(16) + domain.encode().hex()


def _to_out(m: MTProtoLink) -> MTProtoOut:
    secret = m.secret or _get_secret()
    return MTProtoOut(
        id=m.id, label=m.label, secret=secret, is_active=m.is_active,
        connect_url=build_mtproto_url(secret)
    )


def _sync_mtg_secrets(db: Session):
    """Write every active secret to the file mtg reads and restart mtg so new
    links work immediately (Railway: mtg runs inside the same container;
    VPS: the sidecar mtg mounts the same secrets file)."""
    active = db.query(MTProtoLink).filter(MTProtoLink.is_active == True).all()  # noqa: E712
    write_mtg_secret_list([m.secret or _get_secret() for m in active])


@router.get("", response_model=list[MTProtoOut])
def list_mtproto(db: Session = Depends(get_db)):
    return [_to_out(m) for m in db.query(MTProtoLink).all()]


@router.post("", response_model=MTProtoOut)
def create_mtproto(payload: MTProtoCreate, db: Session = Depends(get_db)):
    secret = _get_secret()
    m = MTProtoLink(label=payload.label, secret=secret)
    db.add(m)
    db.commit()
    db.refresh(m)
    _sync_mtg_secrets(db)
    return _to_out(m)


@router.delete("/{mtproto_id}")
def delete_mtproto(mtproto_id: int, db: Session = Depends(get_db)):
    m = db.query(MTProtoLink).get(mtproto_id)
    if not m:
        raise HTTPException(404, "Not found")
    db.delete(m)
    db.commit()
    _sync_mtg_secrets(db)
    return {"ok": True}