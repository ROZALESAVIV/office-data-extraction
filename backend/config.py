from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    DATABASE_URL: str
    ANTHROPIC_API_KEY: str
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    STORAGE_BACKEND: str = "local"
    LOCAL_STORAGE_PATH: str = "./uploads"

    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_S3_BUCKET: str = ""
    AWS_REGION: str = "us-east-1"

    UDUKENET_API_URL: str = ""
    UDUKENET_API_KEY: str = ""
    UDUKENET_ADAPTER: str = "mock"

    ENVIRONMENT: str = "development"
    MAX_UPLOAD_SIZE_MB: int = 20


settings = Settings()
