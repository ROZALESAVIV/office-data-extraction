"""
Run once to insert a test tenant + user into the database.
Usage: py -3 seed.py
"""
import uuid
import bcrypt
from database import SessionLocal
from models.models import Tenant, User

if __name__ == "__main__":
    db = SessionLocal()
    try:
        tenant = Tenant(id=uuid.uuid4(), name="Test Firm")
        db.add(tenant)
        db.flush()

        user = User(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            email="admin@testfirm.com",
            full_name="Admin User",
            role="owner",
            password_hash=bcrypt.hashpw(b"secret123", bcrypt.gensalt()).decode(),
        )
        db.add(user)
        db.commit()

        print(f"Created tenant: {tenant.id}")
        print(f"Created user:   {user.email} / secret123")
    except Exception as e:
        db.rollback()
        print(f"Seed failed: {e}")
    finally:
        db.close()
