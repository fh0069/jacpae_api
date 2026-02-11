from pathlib import Path
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve .env from project root (3 levels up from this file)
_ENV_FILE = Path(__file__).resolve().parent.parent.parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        extra="ignore",
    )

    app_env: str = "development"
    host: str = "127.0.0.1"
    port: int = 8000

    # Supabase / Auth
    supabase_url: str | None = None
    supabase_iss: str
    supabase_jwks_url: str
    supabase_aud: str = "authenticated"
    supabase_service_role_key: SecretStr | None = None
    jwks_cache_ttl: int = 3600
    jwks_ready_timeout: int = 2  # seconds for readiness check

    # PDF / NAS
    pdf_base_dir: str = "./_pdfs/invoices_issued"

    # MariaDB (required - no defaults)
    mariadb_host: str = "127.0.0.1"
    mariadb_port: int = 3306
    mariadb_user: str
    mariadb_password: SecretStr
    mariadb_db: str


settings = Settings()
