import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .api.health import router as health_router
from .api.me import router as me_router
from .api.invoices import router as invoices_router
from .api.invoice_pdf import router as invoice_pdf_router
from .api.notifications import router as notifications_router
from .core.logging import configure_logging, RequestLoggingMiddleware
from .core.config import settings
from .core.mariadb import close_pools

configure_logging()
logger = logging.getLogger(__name__)

# ── Scheduler (lazy init) ────────────────────────────────────

_scheduler = None


def _setup_scheduler():
    """Create and configure the APScheduler instance with enabled jobs."""
    global _scheduler
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger

    _scheduler = AsyncIOScheduler()

    if settings.giro_job_enabled:
        from .jobs.giro_job import run_giro_job

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
        logger.info(
            "Giro job scheduled at %02d:%02d Europe/Madrid",
            settings.giro_job_hour,
            settings.giro_job_minute,
        )

    if settings.reparto_job_enabled:
        from .jobs.reparto_job import run_reparto_job

        _scheduler.add_job(
            run_reparto_job,
            trigger=CronTrigger(
                hour=settings.reparto_job_hour,
                minute=settings.reparto_job_minute,
                timezone="Europe/Madrid",
            ),
            id="reparto_job_daily",
            name="Daily reparto notification job",
            replace_existing=True,
        )
        logger.info(
            "Reparto job scheduled at %02d:%02d Europe/Madrid",
            settings.reparto_job_hour,
            settings.reparto_job_minute,
        )

    _scheduler.start()


# ── Lifespan ──────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    any_job_enabled = settings.giro_job_enabled or settings.reparto_job_enabled
    if any_job_enabled:
        _setup_scheduler()
    else:
        logger.info("No scheduled jobs enabled")

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
app.include_router(notifications_router)

# Debug endpoints (development only)
if settings.app_env == "development":
    from .api.debug import router as debug_router
    app.include_router(debug_router)
