from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from .config import settings

url = settings.DATABASE_URL
if url.startswith("postgres://"):
    # FIX: SQLAlchemy 2.x dropped support for the postgres:// scheme
    # (Railway hands you exactly this URL) -- must be postgresql://
    url = url.replace("postgres://", "postgresql://", 1)

connect_args = {}
if url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(url, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def run_light_migrations():
    """No Alembic in this project -- Base.metadata.create_all() only creates
    tables that don't exist yet, it never ALTERs existing ones. This adds any
    columns that newer code expects but an older deployed DB is missing, so
    upgrading doesn't require a manual migration or DB wipe."""
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    if "proxy_links" not in inspector.get_table_names():
        return  # fresh DB, create_all() already built the up-to-date schema

    existing = {col["name"] for col in inspector.get_columns("proxy_links")}
    wanted = {
        "anti_filter": "BOOLEAN DEFAULT FALSE",
        "sub_id": "VARCHAR",
        "high_speed": "BOOLEAN DEFAULT FALSE",
    }
    with engine.begin() as conn:
        for col, ddl_type in wanted.items():
            if col not in existing:
                conn.execute(text(f"ALTER TABLE proxy_links ADD COLUMN {col} {ddl_type}"))

    # backfill sub_id for rows created before this column existed, so every
    # link is subscribable even after an upgrade (each gets its own group).
    if "sub_id" not in existing:
        import secrets as _secrets
        with engine.begin() as conn:
            rows = conn.execute(text("SELECT id FROM proxy_links WHERE sub_id IS NULL")).fetchall()
            for (row_id,) in rows:
                conn.execute(
                    text("UPDATE proxy_links SET sub_id = :sid WHERE id = :rid"),
                    {"sid": _secrets.token_urlsafe(6), "rid": row_id},
                )