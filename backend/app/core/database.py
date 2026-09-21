from contextlib import contextmanager

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)

# Owner connection. Only for migrations and the startup sweeper — never for
# request handling, because it is exempt from row-level security.
admin_engine = create_engine(settings.admin_database_url, pool_pre_ping=True)


class TenantSession(Session):
    """A Session that remembers its tenant and re-applies it to every transaction.

    ``set_config(..., is_local => true)`` is scoped to the current transaction,
    so a plain ``SET LOCAL`` is wiped by the first ``commit()``. Any query after
    that commit — a ``refresh()``, a second write — would then run with no tenant
    context at all. Binding the value to the Session and re-applying it on
    ``after_begin`` keeps every transaction of the request correctly scoped.
    """

    tenant_id: str | None = None


SessionLocal = sessionmaker(
    bind=engine, class_=TenantSession, autocommit=False, autoflush=False
)

AdminSessionLocal = sessionmaker(bind=admin_engine, autocommit=False, autoflush=False)


@event.listens_for(TenantSession, "after_begin")
def _apply_tenant(session, transaction, connection):
    tenant_id = getattr(session, "tenant_id", None)
    if tenant_id:
        connection.exec_driver_sql(
            "SELECT set_config('app.current_tenant_id', %s, true)", (str(tenant_id),)
        )


def get_db():
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def set_tenant(db: TenantSession, tenant_id: str) -> None:
    """Scope this session to a tenant, for this and every later transaction."""
    db.tenant_id = str(tenant_id)
    db.execute(
        text("SELECT set_config('app.current_tenant_id', :tid, true)"),
        {"tid": str(tenant_id)},
    )


@contextmanager
def admin_session():
    """Session that BYPASSES tenant isolation. Startup recovery only.

    Every use must be justified by the absence of a request context. Grep for
    this name before adding another caller.
    """
    db = AdminSessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
