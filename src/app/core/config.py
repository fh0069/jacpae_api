from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    app_env: str = "development"
    host: str = "127.0.0.1"
    port: int = 8000

    # Supabase / Auth
    supabase_url: str | None = None
    supabase_iss: str 
    supabase_jwks_url: str
    supabase_aud: str = "authenticated"
    jwks_cache_ttl: int = 3600
    jwks_ready_timeout: int = 2  # seconds for readiness check
    
    class Config:
        env_file = ".env"

settings = Settings()