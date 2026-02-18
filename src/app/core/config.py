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

    # MariaDB contabilidad (misma instancia, distinto schema)
    mariadb_finan_db: str = "g4finan"

    # Giro notification job
    giro_job_enabled: bool = False
    giro_job_hour: int = 8
    giro_job_minute: int = 0
    giro_default_dias_aviso: int = 5

    # Reparto notification job
    reparto_job_enabled: bool = False
    reparto_job_hour: int = 8
    reparto_job_minute: int = 0
    reparto_default_dias_aviso: int = 2

    # Offer notification job
    offer_job_enabled: bool = False
    offer_job_hour: int = 8
    offer_job_minute: int = 5


settings = Settings()
