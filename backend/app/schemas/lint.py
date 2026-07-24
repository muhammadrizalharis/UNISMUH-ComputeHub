"""Skema untuk endpoint lint (analisis kode statik / error lens)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class LintRequest(BaseModel):
    code: str = Field(default="", max_length=200_000)
    # Kode sel-sel SEBELUMNYA (notebook) sebagai konteks: nama/impor di sel awal
    # dikenali sehingga tidak salah ditandai 'undefined name'. Diagnostik yang
    # dikembalikan HANYA untuk `code` (nomor baris relatif ke `code`).
    prefix: str = Field(default="", max_length=200_000)


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


class CompleteRequest(BaseModel):
    code: str = Field(default="", max_length=100_000)
    line: int = Field(ge=1, description="Baris kursor (1-based)")
    column: int = Field(ge=0, description="Kolom kursor (0-based)")


class CompletionItem(BaseModel):
    label: str
    type: str = "text"
    insert: str = ""


class CompleteResponse(BaseModel):
    items: list[CompletionItem]
