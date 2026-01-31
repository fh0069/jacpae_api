from fastapi import FastAPI
from .api.health import router as health_router
from .core.logging import configure_logging
from .core.config import Settings

configure_logging()
settings = Settings()

app = FastAPI(title="jacpae_api", version="0.1.0")
app.include_router(health_router)
