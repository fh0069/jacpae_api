from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    app_env: str = "development"
    host: str = "127.0.0.1"
    port: int = 8000

    class Config:
        env_file = ".env"
