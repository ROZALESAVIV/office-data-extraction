import uuid
from typing import NamedTuple

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import TenantSession, get_db, set_tenant
from app.models.models import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

# Roles allowed to change data. 'staff' may upload and read, but not confirm
# extracted values or create configuration.
WRITE_ROLES = ("owner", "lawyer")


class TenantContext(NamedTuple):
    """Tuple-shaped so existing ``db, user = ctx`` call sites keep working."""

    db: TenantSession
    user: User


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        user_id = payload.get("sub")
        if user_id is None:
            raise credentials_error
        # A non-UUID 'sub' would otherwise reach Postgres and raise DataError,
        # turning a bad token into a 500 instead of a 401.
        user_uuid = uuid.UUID(str(user_id))
    except (JWTError, ValueError, AttributeError):
        # Deliberately not chained: the reason a token is invalid must not be
        # inferable by the caller.
        raise credentials_error from None

    # users has no RLS policy — safe to query before any tenant context exists.
    user = db.query(User).filter(User.id == user_uuid).first()
    if user is None or not user.is_active:
        raise credentials_error
    return user


def get_current_user_with_tenant(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TenantContext:
    set_tenant(db, str(user.tenant_id))
    return TenantContext(db=db, user=user)


def require_write_role(ctx: TenantContext = Depends(get_current_user_with_tenant)) -> TenantContext:
    if ctx.user.role not in WRITE_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )
    return ctx


def require_owner(ctx: TenantContext = Depends(get_current_user_with_tenant)) -> TenantContext:
    if ctx.user.role != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )
    return ctx
