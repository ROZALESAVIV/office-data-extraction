from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from jose import jwt
from sqlalchemy.orm import Session

from app.deps import get_current_user
from database import get_db
from app.schemas import TokenResponse, UserOut
from config import settings
from models.models import User

router = APIRouter(prefix="/auth", tags=["auth"])


def _create_token(user: User) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {"sub": str(user.id), "tenant_id": str(user.tenant_id), "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


_DUMMY_HASH = "$2b$12$KIXEKvHR5CqGGmYwIDjdpOmBBZzX9GEt0tCa/EIfPh5JJt3VzGIBW"


@router.post("/login", response_model=TokenResponse)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    # users has no RLS — query before setting tenant context
    user = db.query(User).filter(User.email == form.username).first()
    # Always run bcrypt even when user not found — prevents timing-based email enumeration
    stored_hash = user.password_hash if (user and user.is_active) else _DUMMY_HASH
    password_ok = bcrypt.checkpw(form.password.encode(), stored_hash.encode())
    if not user or not user.is_active or not password_ok:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    return TokenResponse(access_token=_create_token(user))


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return current_user
