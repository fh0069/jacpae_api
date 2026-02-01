from fastapi import FastAPI
from .api.health import router as health_router
from .api.me import router as me_router
from .core.logging import configure_logging, RequestLoggingMiddleware
configure_logging()

app = FastAPI(title="jacpae_api", version="0.1.0")
# Register middleware for structured request logging
app.add_middleware(RequestLoggingMiddleware)

app.include_router(health_router)
app.include_router(me_router)
