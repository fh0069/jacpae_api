from fastapi import FastAPI
from .api.health import router as health_router
from .api.me import router as me_router
from .api.invoices import router as invoices_router
from .core.logging import configure_logging, RequestLoggingMiddleware
from .core.config import settings
configure_logging()

app = FastAPI(title="jacpae_api", version="0.1.0")
# Register middleware for structured request logging
app.add_middleware(RequestLoggingMiddleware)

app.include_router(health_router)
app.include_router(me_router)
app.include_router(invoices_router)

# Debug endpoints (development only)
if settings.app_env == "development":
    from .api.debug import router as debug_router
    app.include_router(debug_router)
