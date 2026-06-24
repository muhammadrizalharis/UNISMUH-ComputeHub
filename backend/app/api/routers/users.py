"""Router users (manajemen user oleh admin)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, get_user_by_email, require_admin
from app.core.database import get_db
from app.core.security import hash_password
from app.models.user import User, UserRole
from app.schemas.user import UserCreate, UserOut, UserUpdate

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


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> User:
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
    user = User(
        name=payload.name,
        email=payload.email,
        hashed_password=hash_password(payload.password),
        role=payload.role,
        is_active=True,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


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
    return user


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
    await session.delete(user)
    await session.commit()
