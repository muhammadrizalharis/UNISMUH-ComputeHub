"""Skema untuk endpoint lint (analisis kode statik / error lens)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class LintRequest(BaseModel):
    code: str = Field(default="", max_length=200_000)


class LintDiagnostic(BaseModel):
    line: int
    col: int
    severity: str  # 'error' | 'warning'
    message: str
    source: str = "pyflakes"


class LintResponse(BaseModel):
    diagnostics: list[LintDiagnostic]
    error_count: int
    warning_count: int
    ok: bool
