"""Router lint: analisis kode statik untuk 'error lens' di editor (tempel kode & notebook)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool

from app.api.deps import get_current_active_user
from app.models.user import User
from app.schemas.lint import (
    CompleteRequest,
    CompleteResponse,
    CompletionItem,
    LintDiagnostic,
    LintRequest,
    LintResponse,
)
from app.services import complete as complete_svc
from app.services import lint as lint_svc

router = APIRouter()


@router.post("", response_model=LintResponse)
async def lint_code(
    payload: LintRequest,
    _user: User = Depends(get_current_active_user),
) -> LintResponse:
    """Periksa kode Python (statik, tanpa eksekusi) dan kembalikan daftar error/peringatan."""
    diagnostics = await run_in_threadpool(lint_svc.lint_code, payload.code)
    error_count = sum(1 for d in diagnostics if d.severity == "error")
    warning_count = len(diagnostics) - error_count
    return LintResponse(
        diagnostics=[
            LintDiagnostic(
                line=d.line,
                col=d.col,
                severity=d.severity,
                message=d.message,
                source=d.source,
            )
            for d in diagnostics
        ],
        error_count=error_count,
        warning_count=warning_count,
        ok=error_count == 0,
    )


@router.post("/complete", response_model=CompleteResponse)
async def complete_code(
    payload: CompleteRequest,
    _user: User = Depends(get_current_active_user),
) -> CompleteResponse:
    """Saran autocomplete Python (jedi, statik — kode TIDAK dieksekusi)."""
    items = await run_in_threadpool(
        complete_svc.complete, payload.code, payload.line, payload.column
    )
    return CompleteResponse(items=[CompletionItem(**it) for it in items])
