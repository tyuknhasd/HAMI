from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import get_current_admin
from ..config import settings
from ..database import get_db
from ..link_builder import (
    ANTI_FILTER_FRAGMENT_JSON, build_connect_url, high_speed_mux_json, qr_png_base64,
)
from ..models import ProxyLink
from ..schemas import LinkCreate, LinkOut, LinkUpdate
from ..xray_manager import apply_config

router = APIRouter(prefix="/api/links", tags=["links"], dependencies=[Depends(get_current_admin)])


def _to_out(link: ProxyLink, with_qr: bool = False) -> LinkOut:
    url = build_connect_url(link)
    return LinkOut(
        id=link.id, uuid=link.uuid, label=link.label, protocol=link.protocol,
        client_id=link.client_id, traffic_limit_bytes=link.traffic_limit_bytes,
        traffic_used_bytes=link.traffic_used_bytes, expires_at=link.expires_at,
        is_active=link.is_active, created_at=link.created_at, connect_url=url,
        qr_png_base64=qr_png_base64(url) if with_qr else None,
        anti_filter=link.anti_filter,
        high_speed=link.high_speed,
        sub_id=link.sub_id,
        sub_url=f"https://{settings.SUB_DOMAIN or settings.PUBLIC_DOMAIN}/sub/{link.sub_id}",
        fragment_json=ANTI_FILTER_FRAGMENT_JSON if link.anti_filter else None,
        mux_json=high_speed_mux_json(link),
    )


@router.get("", response_model=list[LinkOut])
def list_links(db: Session = Depends(get_db)):
    links = db.query(ProxyLink).order_by(ProxyLink.created_at.desc()).all()
    return [_to_out(l) for l in links]


@router.post("", response_model=LinkOut)
def create_link(payload: LinkCreate, db: Session = Depends(get_db)):
    link = ProxyLink(
        label=payload.label,
        protocol=payload.protocol,
        traffic_limit_bytes=int(payload.traffic_limit_gb * (1024 ** 3)),
        expires_at=(datetime.utcnow() + timedelta(days=payload.expires_in_days))
        if payload.expires_in_days else None,
        anti_filter=payload.anti_filter,
        high_speed=payload.high_speed,
    )
    if payload.sub_id:
        # join an existing subscription group -- verify it's a real group
        # first so a typo doesn't silently create an orphaned one-off group.
        if not db.query(ProxyLink).filter(ProxyLink.sub_id == payload.sub_id).first():
            raise HTTPException(404, "sub_id not found -- omit it to start a new subscription group")
        link.sub_id = payload.sub_id
    db.add(link)
    db.commit()
    db.refresh(link)
    apply_config(db)
    return _to_out(link, with_qr=True)


@router.get("/{link_id}", response_model=LinkOut)
def get_link(link_id: int, db: Session = Depends(get_db)):
    link = db.query(ProxyLink).get(link_id)
    if not link:
        raise HTTPException(404, "Link not found")
    return _to_out(link, with_qr=True)


@router.patch("/{link_id}", response_model=LinkOut)
def update_link(link_id: int, payload: LinkUpdate, db: Session = Depends(get_db)):
    link = db.query(ProxyLink).get(link_id)
    if not link:
        raise HTTPException(404, "Link not found")

    if payload.label is not None:
        link.label = payload.label
    if payload.is_active is not None:
        link.is_active = payload.is_active
    if payload.traffic_limit_gb is not None:
        link.traffic_limit_bytes = int(payload.traffic_limit_gb * (1024 ** 3))
    if payload.expires_in_days is not None:
        link.expires_at = (datetime.utcnow() + timedelta(days=payload.expires_in_days)) \
            if payload.expires_in_days > 0 else None
    if payload.anti_filter is not None:
        link.anti_filter = payload.anti_filter
    if payload.high_speed is not None:
        link.high_speed = payload.high_speed

    db.commit()
    db.refresh(link)
    apply_config(db)
    return _to_out(link)


@router.delete("/{link_id}")
def delete_link(link_id: int, db: Session = Depends(get_db)):
    link = db.query(ProxyLink).get(link_id)
    if not link:
        raise HTTPException(404, "Link not found")
    db.delete(link)
    db.commit()
    apply_config(db)
    return {"ok": True}


@router.post("/{link_id}/toggle", response_model=LinkOut)
def toggle_link(link_id: int, db: Session = Depends(get_db)):
    link = db.query(ProxyLink).get(link_id)
    if not link:
        raise HTTPException(404, "Link not found")
    link.is_active = not link.is_active
    db.commit()
    db.refresh(link)
    apply_config(db)
    return _to_out(link)
