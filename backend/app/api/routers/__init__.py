"""Agregasi semua router API v1."""

from fastapi import APIRouter

from app.api.routers import (
    admin,
    alerts,
    assistant,
    auth,
    interactive,
    jobs,
    lint,
    monitoring,
    system,
    users,
)

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
api_router.include_router(lint.router, prefix="/lint", tags=["lint"])
api_router.include_router(interactive.router, prefix="/interactive", tags=["interactive"])
api_router.include_router(assistant.router, prefix="/assistant", tags=["assistant"])
api_router.include_router(monitoring.router, prefix="/monitoring", tags=["monitoring"])
api_router.include_router(system.router, prefix="/system", tags=["system"])
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
api_router.include_router(alerts.router, prefix="/admin/alerts", tags=["alerts"])
