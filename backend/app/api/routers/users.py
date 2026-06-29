"""Router users (manajemen user oleh admin)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_current_active_user,
    get_user_by_email,
    invalidate_auth_cache,
    require_admin,
)
from app.core.database import get_db
from app.core.security import hash_password
from app.models.user import User, UserRole
from app.schemas.user import UserCreate, UserCreateResult, UserOut, UserUpdate
from app.services import accounts as accounts_svc
from app.services.interactive import kernel_manager

router = APIRouter()


@router.get("", response_model=list[UserOut])
async def list_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> list[User]:
    result = await session.scalars(
        select(User).order_by(User.id).offset(skip).limit(limit)
    )
    return list(result.all())


@router.post("", response_model=UserCreateResult, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> UserCreateResult:
    # Hanya administrator utama yang boleh membuat akun admin (cegah eskalasi hak).
    if payload.role == UserRole.admin and not current_user.is_superadmin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Hanya administrator utama yang boleh membuat akun admin.",
        )
    if await get_user_by_email(session, payload.email) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email sudah terdaftar."
        )

    # Admin cukup input nama + email + role. Username & password di-generate otomatis.
    username = await accounts_svc.generate_unique_username(session, payload.email)
    generated = payload.password is None
    plain_password = payload.password or accounts_svc.generate_password()

    user = User(
        name=payload.name,
        email=payload.email,
        username=username,
        hashed_password=hash_password(plain_password),
        role=payload.role,
        is_active=True,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)

    # Kirim kredensial ke email user (best-effort) hanya bila password di-generate.
    email_sent = False
    if generated:
        email_sent = await accounts_svc.send_credentials_email(
            to=user.email, name=user.name, username=username, password=plain_password
        )

    result = UserCreateResult.model_validate(user)
    # Password plaintext dikembalikan HANYA sekali (untuk ditampilkan ke admin).
    result.generated_password = plain_password if generated else None
    result.email_sent = email_sent
    return result


@router.get("/{user_id}", response_model=UserOut)
async def get_user(
    user_id: int,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> User:
    # Admin boleh lihat siapa pun; user lain hanya dirinya.
    if current_user.role != UserRole.admin and current_user.id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Akses ditolak.")
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User tidak ditemukan.")
    return user


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: int,
    payload: UserUpdate,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> User:
    is_admin = current_user.role == UserRole.admin
    if not is_admin and current_user.id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Akses ditolak.")

    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User tidak ditemukan.")

    # --- Proteksi hierarki saat mengubah AKUN ORANG LAIN (berlaku SEMUA kolom) ---
    # Admin biasa hanya boleh mengelola dosen & mahasiswa. Akun admin (biasa maupun
    # utama) hanya boleh diubah oleh administrator utama. Akun admin utama hanya
    # boleh diubah oleh dirinya sendiri.
    if current_user.id != user_id:
        if user.is_superadmin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Akun administrator utama hanya dapat diubah oleh dirinya sendiri.",
            )
        if user.role == UserRole.admin and not current_user.is_superadmin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin biasa tidak boleh mengubah akun admin lain (hanya administrator utama).",
            )

    if payload.name is not None:
        user.name = payload.name
    if payload.password is not None:
        if current_user.id == user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Ubah password sendiri lewat menu 'Ubah Password' (butuh password lama).",
            )
        user.hashed_password = hash_password(payload.password)
    # Ubah role / status aktif: hanya admin, dengan proteksi tambahan.
    if payload.role is not None or payload.is_active is not None:
        if not is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Hanya admin boleh ubah role/status.",
            )
        if user.is_superadmin:
            # Administrator utama tidak boleh diturunkan / dinonaktifkan.
            if payload.role is not None and payload.role != UserRole.admin:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Role administrator utama tidak dapat diubah.",
                )
            if payload.is_active is not None and not payload.is_active:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Administrator utama tidak dapat dinonaktifkan.",
                )
        # Hanya administrator utama yang boleh mengangkat akun menjadi admin.
        if payload.role == UserRole.admin and not current_user.is_superadmin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Hanya administrator utama yang boleh menjadikan akun sebagai admin.",
            )
    if payload.role is not None:
        user.role = payload.role
    if payload.is_active is not None:
        user.is_active = payload.is_active

    await session.commit()
    await session.refresh(user)
    # Akun dinonaktifkan -> hentikan sesi interaktif aktifnya (bebaskan GPU + slot).
    if payload.is_active is False:
        await kernel_manager.drop_user_sessions(user_id)
    return user


@router.post("/{user_id}/reset-password", response_model=UserCreateResult)
async def reset_password(
    user_id: int,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> UserCreateResult:
    """Admin reset password user: generate password baru (di-hash), kembalikan SEKALI
    + kirim email. Sesi aktif user digugurkan (wajib login ulang)."""
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User tidak ditemukan."
        )
    # Proteksi hierarki (selaras update/delete): admin utama hanya oleh dirinya;
    # admin biasa tak boleh reset admin lain.
    if current_user.id != user_id:
        if user.is_superadmin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Password administrator utama hanya dapat direset oleh dirinya sendiri.",
            )
        if user.role == UserRole.admin and not current_user.is_superadmin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin biasa tidak boleh mereset password admin lain.",
            )

    new_password = accounts_svc.generate_password()
    user.hashed_password = hash_password(new_password)
    # Password berubah -> gugurkan sesi aktif (token lama tak boleh dipakai lagi).
    user.session_token = None
    session.add(user)
    await session.commit()
    await session.refresh(user)
    invalidate_auth_cache(user.id)
    await kernel_manager.drop_user_sessions(user_id)

    email_sent = await accounts_svc.send_credentials_email(
        to=user.email,
        name=user.name,
        username=user.username or user.email,
        password=new_password,
    )
    result = UserCreateResult.model_validate(user)
    result.generated_password = new_password
    result.email_sent = email_sent
    return result


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: int,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> None:
    if current_user.id == user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tidak bisa menghapus akun sendiri.",
        )
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User tidak ditemukan.")
    # Administrator utama dilindungi dari penghapusan.
    if user.is_superadmin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator utama tidak dapat dihapus.",
        )
    # Hanya administrator utama yang boleh menghapus akun admin lain.
    if user.role == UserRole.admin and not current_user.is_superadmin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Hanya administrator utama yang boleh menghapus akun admin lain.",
        )
    # Hentikan sesi interaktif user SEBELUM hapus (bebaskan GPU/slot; job ter-cascade).
    await kernel_manager.drop_user_sessions(user_id)
    await session.delete(user)
    await session.commit()
