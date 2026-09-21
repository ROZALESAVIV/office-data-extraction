from datetime import UTC, datetime, timedelta

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from jose import jwt
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.deps import get_current_user
from app.models.models import User
from app.schemas import TokenResponse, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


def _create_token(user: User) -> str:
    expire = datetime.now(UTC) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {"sub": str(user.id), "tenant_id": str(user.tenant_id), "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


_DUMMY_HASH = "$2b$12$KIXEKvHR5CqGGmYwIDjdpOmBBZzX9GEt0tCa/EIfPh5JJt3VzGIBW"

# bcrypt itself only ever considers the first 72 bytes, and raises on anything
# longer. Truncating here keeps that an authentication failure rather than an
# unauthenticated 500 that any client can trigger at will.
_BCRYPT_MAX_BYTES = 72


def _password_matches(password: str, stored_hash: str) -> bool:
    try:
        return bcrypt.checkpw(
            password.encode()[:_BCRYPT_MAX_BYTES], stored_hash.encode()
        )
    except ValueError:
        # Malformed or empty stored hash — treat as a failed login, not a crash.
        return False


@router.post("/login", response_model=TokenResponse)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    # users has no RLS — query before setting tenant context
    user = db.query(User).filter(User.email == form.username).first()
    # Always run bcrypt even when user not found — prevents timing-based email enumeration
    stored_hash = user.password_hash if (user and user.is_active) else _DUMMY_HASH
    password_ok = _password_matches(form.password, stored_hash)
    if not user or not user.is_active or not password_ok:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    return TokenResponse(access_token=_create_token(user))


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return current_user
