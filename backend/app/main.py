from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from .config import settings
from .database import Base, engine, SessionLocal, run_light_migrations
from .models import ProxyLink, TrafficSample
from .routers import auth, links, stats, mtproto, sub, system, bot
from .xray_manager import read_stats, apply_config

Base.metadata.create_all(bind=engine)
run_light_migrations()

# Ensure the admin account exists (admin / 123456 by default)
from .auth import get_or_create_admin  # noqa: E402

with SessionLocal() as boot_db:
    get_or_create_admin(boot_db)

app = FastAPI(title=settings.PROJECT_NAME)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(links.router)
app.include_router(stats.router)
app.include_router(mtproto.router)
app.include_router(sub.router)
app.include_router(system.router)
app.include_router(bot.router)

app.mount("/static", StaticFiles(directory="/app/frontend/static"), name="static")


@app.get("/")
def root():
    return FileResponse("/app/frontend/index.html")


@app.get("/dashboard")
def dashboard():
    return FileResponse("/app/frontend/dashboard.html")


def sync_traffic_job():
    """Runs every minute: pulls per-user byte counters from Xray, records
    the delta as a TrafficSample (for the chart) and updates each link's
    running total. Deactivates + re-applies config for anyone over quota
    or past their expiry date."""
    db = SessionLocal()
    try:
        live = read_stats()  # {email(=link.uuid): total_bytes}
        links = db.query(ProxyLink).all()
        changed = False
        for link in links:
            total = live.get(link.uuid)
            if total is None:
                continue
            delta = max(0, total - link.last_synced_bytes)
            if delta:
                db.add(TrafficSample(link_id=link.id, bytes_delta=delta))
                link.traffic_used_bytes += delta
                link.last_synced_bytes = total

            over_quota = link.traffic_limit_bytes and link.traffic_used_bytes >= link.traffic_limit_bytes
            expired = link.expires_at and datetime.utcnow() >= link.expires_at
            if (over_quota or expired) and link.is_active:
                link.is_active = False
                changed = True

        db.commit()
        if changed:
            apply_config(db)
    finally:
        db.close()


scheduler = BackgroundScheduler()
scheduler.add_job(sync_traffic_job, "interval", minutes=1)


@app.on_event("startup")
def on_startup():
    # Make sure the xray config on disk matches the DB the moment we boot.
    db = SessionLocal()
    try:
        apply_config(db)
    finally:
        db.close()
    scheduler.start()
    # Auto-start the Telegram bot if a token is configured
    from . import bot_service
    bot_service.start_bot()


@app.on_event("shutdown")
def on_shutdown():
    scheduler.shutdown(wait=False)
