from .config import settings
import json
import logging
import time
import uuid
from prometheus_client import Counter, Gauge, Histogram, generate_latest, CONTENT_TYPE_LATEST
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

logger = logging.getLogger("ai_trader")
REQUESTS = Counter("trader_http_requests_total", "HTTP requests", ["method", "path", "status"])
REQUEST_LATENCY = Histogram("trader_http_request_duration_seconds", "HTTP request duration", ["method", "path"])
ORDERS = Counter("trader_orders_total", "Orders by mode/status", ["mode", "status"])
EQUITY = Gauge("trader_equity", "Current account equity")
DRAWDOWN = Gauge("trader_drawdown", "Current equity drawdown")
OPEN_POSITIONS = Gauge("trader_open_positions", "Number of non-zero positions")


class TelemetryMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        start = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - start
        path = request.url.path
        REQUESTS.labels(request.method, path, str(response.status_code)).inc()
        REQUEST_LATENCY.labels(request.method, path).observe(elapsed)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        if str(settings.environment).lower() == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
            response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'"
        logger.info(json.dumps({"request_id": request_id, "method": request.method, "path": path,
                                "status": response.status_code, "duration_ms": round(elapsed * 1000, 2)}))
        return response


def metrics_response():
    return generate_latest(), CONTENT_TYPE_LATEST
