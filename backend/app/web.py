"""Melayani frontend (hasil `npm run build`) lewat FastAPI.

Saat produksi, file statis di `frontend/dist` dilayani langsung oleh backend
sehingga cukup 1 port (tidak perlu proses Node terpisah). Bila build belum ada,
root diarahkan ke /docs.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response

from app.core.config import BACKEND_DIR
from app.core.logging import get_logger

logger = get_logger(__name__)

# .../SERVER-KAMPUS/frontend/dist
FRONTEND_DIST = BACKEND_DIR.parent / "frontend" / "dist"

# Prefix yang TIDAK boleh ditangani SPA (milik backend).
_RESERVED = ("api/", "docs", "redoc", "openapi.json", "health")


def mount_frontend(app: FastAPI) -> None:
    index_file = FRONTEND_DIST / "index.html"

    if not index_file.exists():
        logger.info(
            "Frontend build belum ada (%s). UI tidak dilayani; jalankan "
            "`npm run build` di folder frontend.",
            FRONTEND_DIST,
        )

        @app.get("/", include_in_schema=False)
        async def _root_redirect() -> RedirectResponse:
            return RedirectResponse(url="/docs")

        return

    # Aset ber-hash dari Vite.
    assets_dir = FRONTEND_DIST / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def _spa(full_path: str) -> Response:
        if full_path.startswith(_RESERVED):
            return Response(status_code=404)
        candidate = FRONTEND_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        # Fallback ke index.html untuk routing sisi-klien (SPA).
        return FileResponse(index_file)

    logger.info("Frontend dilayani dari %s", FRONTEND_DIST)
