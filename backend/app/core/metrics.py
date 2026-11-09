"""Observability: metrik Prometheus untuk ComputeHub.

Mengekspos metrik proses (CPU/RAM/GC via prometheus_client default) plus metrik
HTTP tingkat aplikasi (jumlah request, latensi, status) lewat middleware ringan.
Endpoint /metrics digerbang token opsional (settings.METRICS_TOKEN).

Desain sengaja minimal & tanpa dependensi berat: hanya `prometheus_client`.
Label `path` dinormalisasi ke template route (bukan URL mentah) agar kardinalitas
metrik tetap rendah meski ada ID dinamis di jalur.
"""

from __future__ import annotations

import time

from fastapi import FastAPI, Request, Response
from starlette.responses import PlainTextResponse
from starlette.routing import Match

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from prometheus_client import (
    GCCollector,
    PlatformCollector,
    ProcessCollector,
)

from app.core.config import settings

# Registry global proses (satu worker uvicorn). Bila kelak multiprocess (gunicorn),
# prometheus_client membaca PROMETHEUS_MULTIPROC_DIR; di sini single-process.
_REGISTRY = CollectorRegistry()

# Metrik proses standar (CPU detik, RSS/VMS, fd terbuka, GC, info platform/python)
# didaftarkan ke registry kustom agar ikut terekspos di /metrics.
ProcessCollector(registry=_REGISTRY)
PlatformCollector(registry=_REGISTRY)
GCCollector(registry=_REGISTRY)

REQUESTS = Counter(
    "computehub_http_requests_total",
    "Total request HTTP yang diproses",
    labelnames=("method", "path", "status"),
    registry=_REGISTRY,
)
LATENCY = Histogram(
    "computehub_http_request_duration_seconds",
    "Durasi pemrosesan request HTTP (detik)",
    labelnames=("method", "path"),
    registry=_REGISTRY,
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)
IN_PROGRESS = Gauge(
    "computehub_http_requests_in_progress",
    "Jumlah request HTTP yang sedang diproses",
    registry=_REGISTRY,
)
INFO = Gauge(
    "computehub_app_info",
    "Info aplikasi (label statis; nilai selalu 1)",
    labelnames=("version",),
    registry=_REGISTRY,
)

# Prefix yang dilewati dari metrik HTTP (noise/kardinalitas tinggi, tak informatif).
_SKIP_PREFIXES = ("/metrics", "/health", "/assets/")


def _route_template(request: Request) -> str:
    """Kembalikan template route (mis. /api/v1/jobs/{id}) alih-alih URL mentah,
    supaya label path tidak meledak oleh ID dinamis. Fallback: path apa adanya
    untuk rute statis/SPA, atau '<other>' bila tak match agar aman."""
    for route in request.app.router.routes:
        try:
            match, _ = route.matches(request.scope)
        except Exception:
            continue
        if match == Match.FULL:
            return getattr(route, "path", request.url.path)
    path = request.url.path
    # Batasi kardinalitas untuk path tak dikenal (mis. probe/scanner).
    if path.startswith("/api/"):
        return "<unmatched-api>"
    return "<other>"


def setup_metrics(app: FastAPI, *, version: str) -> None:
    """Pasang middleware pencatat metrik + endpoint /metrics bila diaktifkan."""
    if not settings.METRICS_ENABLED:
        return

    try:
        INFO.labels(version=version).set(1)
    except Exception:
        pass

    @app.middleware("http")
    async def _metrics_middleware(request: Request, call_next):
        path = request.url.path
        if any(path.startswith(p) for p in _SKIP_PREFIXES):
            return await call_next(request)

        IN_PROGRESS.inc()
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            elapsed = time.perf_counter() - start
            IN_PROGRESS.dec()
            template = _route_template(request)
            method = request.method
            try:
                LATENCY.labels(method=method, path=template).observe(elapsed)
                REQUESTS.labels(
                    method=method, path=template, status=str(status)
                ).inc()
            except Exception:
                pass

    @app.get("/metrics", include_in_schema=False)
    async def metrics(request: Request) -> Response:
        token = settings.METRICS_TOKEN
        if token:
            auth = request.headers.get("authorization", "")
            supplied = ""
            if auth.lower().startswith("bearer "):
                supplied = auth[7:].strip()
            if not supplied:
                supplied = request.query_params.get("token", "")
            if supplied != token:
                return PlainTextResponse("forbidden", status_code=403)
        data = generate_latest(_REGISTRY)
        return Response(content=data, media_type=CONTENT_TYPE_LATEST)
