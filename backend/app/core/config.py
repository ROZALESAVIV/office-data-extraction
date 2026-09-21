from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Connection used by the application. This must be a role that is NOT the
    # owner of the tables and does NOT have BYPASSRLS, otherwise Postgres
    # exempts it from the tenant_isolation policies and multi-tenancy silently
    # stops being enforced.
    database_url: str

    # Owner connection. Used only by Alembic and by the stalled-job sweeper,
    # which runs at startup when no tenant context exists. Falls back to
    # database_url so existing dev setups keep working.
    database_admin_url: str = ""

    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 480

    supabase_url: str = ""
    supabase_service_key: str = ""
    supabase_bucket: str = "case-documents"

    anthropic_api_key: str = ""

    # Name and password of the non-owner role the application connects as.
    # When set, the rls_hardening migration creates and grants it. Leave empty
    # if the role is managed outside Alembic (e.g. created by hand in the
    # Supabase SQL editor) — the migration then only hardens the policies.
    app_db_role: str = ""
    app_db_password: str = ""

    # Comma-separated list of browser origins allowed to call the API.
    cors_origins: str = "http://localhost:5173"

    @property
    def admin_database_url(self) -> str:
        return self.database_admin_url or self.database_url

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
