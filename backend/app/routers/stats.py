from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..auth import get_current_admin
from ..database import get_db
from ..models import ProxyLink, TrafficSample
from ..schemas import OverviewStats

router = APIRouter(prefix="/api/stats", tags=["stats"], dependencies=[Depends(get_current_admin)])

GB = 1024 ** 3


@router.get("/overview", response_model=OverviewStats)
def overview(db: Session = Depends(get_db)):
    total_links = db.query(ProxyLink).count()
    active_links = db.query(ProxyLink).filter(ProxyLink.is_active == True).count()  # noqa: E712
    total_used = db.query(func.coalesce(func.sum(ProxyLink.traffic_used_bytes), 0)).scalar()

    since = datetime.utcnow() - timedelta(days=1)
    today_bytes = db.query(func.coalesce(func.sum(TrafficSample.bytes_delta), 0)) \
        .filter(TrafficSample.recorded_at >= since).scalar()

    return OverviewStats(
        total_links=total_links,
        active_links=active_links,
        total_traffic_used_gb=round(total_used / GB, 3),
        total_traffic_today_gb=round(today_bytes / GB, 3),
    )


@router.get("/timeseries")
def timeseries(days: int = 7, db: Session = Depends(get_db)):
    since = datetime.utcnow() - timedelta(days=days)
    rows = db.query(
        func.date(TrafficSample.recorded_at).label("day"),
        func.coalesce(func.sum(TrafficSample.bytes_delta), 0).label("bytes"),
    ).filter(TrafficSample.recorded_at >= since).group_by("day").order_by("day").all()

    return [{"day": str(r.day), "gb": round(r.bytes / GB, 3)} for r in rows]
