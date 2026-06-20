from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from config import settings

engine = create_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def set_tenant(db, tenant_id: str) -> None:
    """Call after auth, before any tenant-scoped query."""
    db.execute(text("SET LOCAL app.current_tenant_id = :tid"), {"tid": tenant_id})
