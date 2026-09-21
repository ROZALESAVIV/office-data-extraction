"""Insert a development tenant and user.

Seeding writes to `tenants`, which the application role is deliberately not
granted, so this runs on the admin connection. It is idempotent — re-running it
updates the existing dev user's password rather than tripping the unique
constraint — and exits non-zero on failure so CI can tell.

Usage: python seed.py
"""

import sys

import bcrypt

from app.core.database import admin_session
from app.models.models import Tenant, User

TENANT_NAME = "Test Firm"
USER_EMAIL = "admin@testfirm.com"
USER_PASSWORD = "secret123"


def main() -> int:
    with admin_session() as db:
        try:
            tenant = db.query(Tenant).filter(Tenant.name == TENANT_NAME).first()
            if tenant is None:
                tenant = Tenant(name=TENANT_NAME)
                db.add(tenant)
                db.flush()
                print(f"Created tenant: {tenant.id}")
            else:
                print(f"Tenant already exists: {tenant.id}")

            password_hash = bcrypt.hashpw(
                USER_PASSWORD.encode(), bcrypt.gensalt()
            ).decode()

            user = (
                db.query(User)
                .filter(User.tenant_id == tenant.id, User.email == USER_EMAIL)
                .first()
            )
            if user is None:
                user = User(
                    tenant_id=tenant.id,
                    email=USER_EMAIL,
                    full_name="Admin User",
                    role="owner",
                    password_hash=password_hash,
                )
                db.add(user)
                print(f"Created user:   {USER_EMAIL} / {USER_PASSWORD}")
            else:
                user.password_hash = password_hash
                user.is_active = True
                print(f"Reset password: {USER_EMAIL} / {USER_PASSWORD}")

            db.commit()
            return 0
        except Exception as exc:
            db.rollback()
            print(f"Seed failed: {exc}", file=sys.stderr)
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
