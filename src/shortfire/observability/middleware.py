"""ASGI correlation-id middleware installer.

Mounts CorrelationIdMiddleware on a FastAPI app. Per request:
- Reads X-Request-ID header (if present and valid UUID4)
- Generates a fresh UUID4 if header absent or malformed
- Sets the asgi-correlation-id contextvar so structlog's add_correlation_id processor
  can inject request_id into every log line emitted during that request scope.

Pattern 5 from RESEARCH.md — minimal one-liner wrapper so every entrypoint uses the
same installation path and the middleware is easy to test via TestClient.

Usage:
    from shortfire.observability.middleware import install_correlation_middleware

    install_correlation_middleware(app)  # call once after app = FastAPI(...)
"""

from asgi_correlation_id import CorrelationIdMiddleware
from fastapi import FastAPI


def install_correlation_middleware(app: FastAPI) -> None:
    """Add CorrelationIdMiddleware to the given FastAPI app.

    The middleware generates a UUID4 per request if no X-Request-ID header is provided
    (or if the provided value is not a valid UUID4 — server-side generated IDs are trusted;
    client-provided IDs are accepted only if valid).

    The correlation ID is stored in an asyncio contextvar provided by asgi-correlation-id.
    structlog's add_correlation_id processor reads this contextvar on every log call.
    """
    app.add_middleware(CorrelationIdMiddleware)
