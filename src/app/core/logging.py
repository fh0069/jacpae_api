import logging
import time
import uuid
import json
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request


def configure_logging():
    # Minimal, structured logging via JSON messages for key events
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        logger = logging.getLogger("app.request")
        start = time.time()
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        # Attach to request state for other handlers
        request.state.request_id = request_id

        try:
            response = await call_next(request)
        except Exception as exc:
            latency_ms = int((time.time() - start) * 1000)
            payload = {
                "request_id": request_id,
                "path": request.url.path,
                "method": request.method,
                "status_code": 500,
                "latency_ms": latency_ms,
            }
            logger.exception(json.dumps(payload))
            raise

        latency_ms = int((time.time() - start) * 1000)
        payload = {
            "request_id": request_id,
            "path": request.url.path,
            "method": request.method,
            "status_code": response.status_code,
            "latency_ms": latency_ms,
        }
        logger.info(json.dumps(payload))
        # Include request id in response header for tracing
        response.headers["X-Request-ID"] = request_id
        return response
