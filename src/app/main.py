import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .api.health import router as health_router
from .api.me import router as me_router
from .api.invoices import router as invoices_router
from .api.invoice_pdf import router as invoice_pdf_router
from .core.logging import configure_logging, RequestLoggingMiddleware
from .core.config import settings
from .core.mariadb import close_pools

configure_logging()
logger = logging.getLogger(__name__)

# ── Scheduler (lazy init) ────────────────────────────────────

_scheduler = None


def _setup_scheduler():
    """Create and configure the APScheduler instance."""
    global _scheduler
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger

    from .jobs.giro_job import run_giro_job

    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        run_giro_job,
        trigger=CronTrigger(
            hour=settings.giro_job_hour,
            minute=settings.giro_job_minute,
            timezone="Europe/Madrid",
        ),
        id="giro_job_daily",
        name="Daily giro notification job",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info(
        "Giro job scheduled at %02d:%02d Europe/Madrid",
        settings.giro_job_hour,
        settings.giro_job_minute,
    )


# ── Lifespan ──────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    if settings.giro_job_enabled:
        _setup_scheduler()
    else:
        logger.info("Giro job disabled (GIRO_JOB_ENABLED=false)")

    yield

    # Shutdown
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler shut down")
    await close_pools()


# ── App ───────────────────────────────────────────────────────

app = FastAPI(title="jacpae_api", version="0.1.0", lifespan=lifespan)
app.add_middleware(RequestLoggingMiddleware)

app.include_router(health_router)
app.include_router(me_router)
app.include_router(invoices_router)
app.include_router(invoice_pdf_router)

# Debug endpoints (development only)
if settings.app_env == "development":
    from .api.debug import router as debug_router
    app.include_router(debug_router)
