"""Entry point FastAPI: UNISMUH AI Cloud backend."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.routers import api_router
from app.core.config import settings
from app.core.database import AsyncSessionLocal, dispose_db, init_db
from app.core.logging import get_logger
from app.core.runtime_limits import apply_cpu_limits
from app.services import gpu as gpu_svc
from app.services import policy as policy_svc
from app.services.alerts import alert_monitor
from app.services.cleanup import cleanup_service
from app.services.interactive import kernel_manager
from app.services.monitor import monitor
from app.services.scheduler import scheduler
from app.seed import ensure_first_admin
from app.web import mount_frontend

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # --- Startup ---
    logger.info("Memulai %s v%s (env=%s)", settings.PROJECT_NAME, __version__, settings.ENV)

    # Batasi CPU proses platform agar tidak mengganggu user lain di server bersama.
    apply_cpu_limits()

    if settings.ENV == "production" and not settings.is_secret_key_safe:
        logger.warning(
            "SECRET_KEY masih default/lemah! Ganti di .env sebelum dipakai publik."
        )

    gpus = gpu_svc.list_gpus()
    if gpus:
        logger.info(
            "GPU terdeteksi: %s",
            ", ".join(f"#{g.index} {g.name} ({g.mem_total_mb:.0f}MB)" for g in gpus),
        )
    elif settings.ENFORCE_GPU:
        logger.warning(
            "TIDAK ada GPU terdeteksi & ENFORCE_GPU=true -> job tidak akan dijalankan "
            "(CPU tidak diizinkan)."
        )

    await init_db()
    async with AsyncSessionLocal() as session:
        await ensure_first_admin(session)
        await policy_svc.ensure_loaded(session)

    await scheduler.start()
    await monitor.start()
    await alert_monitor.start()
    await cleanup_service.start()
    await kernel_manager.start()

    try:
        yield
    finally:
        # --- Shutdown ---
        logger.info("Menghentikan layanan...")
        await kernel_manager.stop()
        await cleanup_service.stop()
        await alert_monitor.stop()
        await monitor.stop()
        await scheduler.stop()
        gpu_svc.shutdown()
        await dispose_db()
        logger.info("Shutdown selesai.")


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=__version__,
    description=(
        "Platform orkestrasi job GPU untuk lingkungan kampus (user non-admin). "
        "Job WAJIB berjalan di GPU — komputasi CPU tidak diizinkan."
    ),
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# --- CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Security headers (header keamanan dasar + CSP) ---
@app.middleware("http")
async def _security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
    )
    # /docs & /redoc (Swagger/ReDoc) butuh CDN + skrip inline -> tanpa CSP ketat.
    path = request.url.path
    if not (
        path.startswith("/docs")
        or path.startswith("/redoc")
        or path == "/openapi.json"
    ):
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault(
            "Content-Security-Policy", settings.CONTENT_SECURITY_POLICY
        )
    # Aset Vite ber-hash (nama unik per build = immutable) -> cache panjang
    # supaya kunjungan ulang tak mengunduh ulang JS/CSS (mis. react-vendor).
    if path.startswith("/assets/"):
        response.headers.setdefault(
            "Cache-Control", "public, max-age=31536000, immutable"
        )
    return response


# --- Routers ---
app.include_router(api_router, prefix=settings.API_V1_PREFIX)


@app.get("/health", include_in_schema=False)
async def health() -> dict:
    return {"status": "ok"}


# --- Frontend (SPA) ---
# Didaftarkan paling akhir agar catch-all SPA tidak menutupi route API/docs.
mount_frontend(app)
