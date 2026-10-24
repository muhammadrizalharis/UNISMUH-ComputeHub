"""Kelola kunci API gerbang Ollama (admin): daftar, buat, ubah, cabut.

Kunci mentah HANYA dikembalikan sekali saat pembuatan. Semua aksi dicatat di audit.
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.core.database import get_db
from app.models.ollama_key import OllamaApiKey
from app.models.user import User
from app.services import audit as audit_svc
from app.services import ollama_gateway as gw

router = APIRouter(tags=["ollama-keys"])


class OllamaKeyCreate(BaseModel):
    name: str = Field(default="", max_length=120)
    owner_user_id: int | None = None
    allowed_models: list[str] = Field(default_factory=list)
    max_concurrent: int = Field(default=2, ge=0, le=64)
    rate_per_min: int = Field(default=30, ge=0, le=100000)
    max_tokens: int = Field(default=4096, ge=0, le=1000000)
    expires_at: dt.datetime | None = None
    note: str = Field(default="", max_length=2000)


class OllamaKeyUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    allowed_models: list[str] | None = None
    max_concurrent: int | None = Field(default=None, ge=0, le=64)
    rate_per_min: int | None = Field(default=None, ge=0, le=100000)
    max_tokens: int | None = Field(default=None, ge=0, le=1000000)
    enabled: bool | None = None
    expires_at: dt.datetime | None = None
    note: str | None = Field(default=None, max_length=2000)


def _dict(k: OllamaApiKey) -> dict:
    return {
        "id": k.id,
        "created_at": k.created_at,
        "name": k.name,
        "key_prefix": k.key_prefix,
        "allowed_models": k.models_list(),
        "max_concurrent": k.max_concurrent,
        "rate_per_min": k.rate_per_min,
        "max_tokens": k.max_tokens,
        "enabled": k.enabled,
        "expires_at": k.expires_at,
        "last_used_at": k.last_used_at,
        "request_count": k.request_count,
        "created_by_email": k.created_by_email,
        "note": k.note,
        "owner_user_id": k.owner_user_id,
        "owner_name": k.owner_name,
        "owner_email": k.owner_email,
        "owner_role": k.owner_role,
        "owner_nim": k.owner_nim,
    }


def _derive_nim(email: str, role: str) -> str:
    """NIM mahasiswa = bagian lokal email (sebelum '@'). Kosong bila bukan mahasiswa
    atau email tak punya bagian lokal yang jelas."""
    if role != "mahasiswa":
        return ""
    local = (email or "").split("@", 1)[0].strip()
    return local


@router.get("")
async def list_keys(
    session: AsyncSession = Depends(get_db), _: User = Depends(require_admin)
) -> list[dict]:
    rows = (
        await session.scalars(select(OllamaApiKey).order_by(OllamaApiKey.created_at.desc()))
    ).all()
    return [_dict(k) for k in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_key(
    payload: OllamaKeyCreate,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> dict:
    raw, prefix, key_hash = gw.generate_key()
    owner_name = ""
    owner_email = ""
    owner_role = ""
    owner_nim = ""
    owner_user_id = payload.owner_user_id
    if owner_user_id is not None:
        owner = await session.get(User, owner_user_id)
        if owner is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Pengguna pemilik tidak ditemukan")
        owner_name = owner.name or ""
        owner_email = owner.email or ""
        owner_role = owner.role.value if owner.role else ""
        owner_nim = _derive_nim(owner_email, owner_role)
    # Nama tampilan kunci: pakai nama pemilik bila kolom nama tak diisi manual.
    display_name = payload.name.strip() or owner_name
    k = OllamaApiKey(
        name=display_name,
        key_prefix=prefix,
        key_hash=key_hash,
        allowed_models="\n".join(m.strip() for m in payload.allowed_models if m.strip()),
        max_concurrent=payload.max_concurrent,
        rate_per_min=payload.rate_per_min,
        max_tokens=payload.max_tokens,
        expires_at=payload.expires_at,
        note=payload.note.strip(),
        created_by_id=current_user.id,
        created_by_email=current_user.email or "",
        owner_user_id=owner_user_id,
        owner_name=owner_name,
        owner_email=owner_email,
        owner_role=owner_role,
        owner_nim=owner_nim,
    )
    session.add(k)
    await session.flush()
    await audit_svc.log(
        session, current_user, "ollama_key.create", "ollama_key", k.id,
        f"buat kunci '{k.name}' ({len(k.models_list())} model)",
    )
    await session.commit()
    out = _dict(k)
    out["key"] = raw  # HANYA sekali ini.
    return out


@router.patch("/{key_id}")
async def update_key(
    key_id: int,
    payload: OllamaKeyUpdate,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> dict:
    k = await session.get(OllamaApiKey, key_id)
    if k is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kunci tidak ditemukan")
    data = payload.model_dump(exclude_unset=True)
    if "allowed_models" in data and data["allowed_models"] is not None:
        k.allowed_models = "\n".join(m.strip() for m in data.pop("allowed_models") if m.strip())
    for field in ("name", "max_concurrent", "rate_per_min", "max_tokens", "enabled", "expires_at", "note"):
        if field in data and data[field] is not None:
            setattr(k, field, data[field].strip() if isinstance(data[field], str) else data[field])
    await audit_svc.log(
        session, current_user, "ollama_key.update", "ollama_key", k.id,
        f"ubah kunci '{k.name}'",
    )
    await session.commit()
    return _dict(k)


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_key(
    key_id: int,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> None:
    k = await session.get(OllamaApiKey, key_id)
    if k is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kunci tidak ditemukan")
    nama = k.name
    await session.delete(k)
    await audit_svc.log(
        session, current_user, "ollama_key.delete", "ollama_key", key_id,
        f"cabut kunci '{nama}'",
    )
    await session.commit()


@router.get("/models/available")
async def available_models(
    _: User = Depends(require_admin),
) -> list[str]:
    """Daftar nama model yang tersedia di Ollama server (untuk pilihan di UI)."""
    import httpx

    from app.core.config import settings

    url = settings.OLLAMA_BASE_URL.rstrip("/") + "/api/tags"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0)) as client:
            r = await client.get(url)
        data = r.json()
    except Exception:  # noqa: BLE001
        return []
    return sorted({m.get("name") or m.get("model") for m in data.get("models", []) if m.get("name") or m.get("model")})
