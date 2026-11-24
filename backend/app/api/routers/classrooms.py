"""Router RUANG KELAS (A1).

- Dosen & admin membuat kelas; pembuatnya otomatis menjadi pengajar.
- Mahasiswa bergabung memakai kode kelas; pengajar juga bisa menambah anggota manual.
- Satu kelas boleh punya beberapa pengajar; pengajar terakhir tidak bisa dikeluarkan.
- Admin melihat & mengelola semua kelas. Mahasiswa hanya melihat kelasnya sendiri,
  dan dari anggota lain hanya daftar pengajar (privasi sesama mahasiswa).
"""

from __future__ import annotations

import asyncio
import datetime as dt
import re
import secrets
import shutil
import time

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, get_db, require_roles
from app.core.config import settings
from app.models.classroom import (
    ROLE_STUDENT,
    ROLE_TEACHER,
    ClassMaterial,
    ClassMaterialCopy,
    ClassMember,
    Classroom,
)
from app.models.notification import Notification
from app.models.user import User, UserRole
from app.schemas.classroom import (
    CandidateOut,
    ClassroomCreate,
    ClassroomDetail,
    ClassroomJoin,
    ClassroomOut,
    ClassroomUpdate,
    GpuBonusUpdate,
    MaterialCopyResult,
    MaterialCreate,
    MaterialOut,
    MemberOut,
    MemberRoleUpdate,
    MembersAdd,
    MembersAddResult,
)
from app.services import audit as audit_svc
from app.services import class_materials as materials_svc
from app.services import policy as policy_svc
from app.services import quota as quota_svc
from app.services import storage_guard
from app.services import user_policy as user_policy_svc

router = APIRouter()

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # tanpa 0/O/1/I agar mudah didikte
CODE_LEN = 8
MAX_CLASSES_PER_CREATOR = 50
MAX_MEMBERS = 500
# Anti tebak kode: maks. percobaan gagal per user dalam jendela waktu.
JOIN_FAIL_LIMIT = 10
JOIN_FAIL_WINDOW = 15 * 60
_join_failures: dict[int, list[float]] = {}

require_creator = require_roles(UserRole.admin, UserRole.dosen)


def _new_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LEN))


def normalize_code(raw: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (raw or "").upper())


def _is_admin(user: User) -> bool:
    return user.role == UserRole.admin


def _display(u: User) -> str:
    return (u.name or u.username or u.email or f"#{u.id}").strip()


async def _membership(session: AsyncSession, class_id: int, user_id: int) -> ClassMember | None:
    return await session.scalar(
        select(ClassMember).where(
            ClassMember.classroom_id == class_id, ClassMember.user_id == user_id
        )
    )


async def _load(session: AsyncSession, class_id: int, user: User) -> tuple[Classroom, str]:
    """Kelas + peran user di dalamnya. 404 bila tidak ada / bukan anggota (non-admin)."""
    room = await session.get(Classroom, class_id)
    mem = await _membership(session, class_id, user.id) if room else None
    if room is None or (mem is None and not _is_admin(user)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Kelas tidak ditemukan.")
    return room, (mem.role if mem else "admin")


def _can_manage(my_role: str) -> bool:
    return my_role in (ROLE_TEACHER, "admin")


async def _load_manage(session: AsyncSession, class_id: int, user: User) -> Classroom:
    room, my_role = await _load(session, class_id, user)
    if not _can_manage(my_role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Hanya pengajar kelas yang boleh mengubah."
        )
    return room


async def _members(session: AsyncSession, class_ids: list[int]) -> dict[int, list[tuple[ClassMember, User]]]:
    out: dict[int, list[tuple[ClassMember, User]]] = {cid: [] for cid in class_ids}
    if not class_ids:
        return out
    rows = await session.execute(
        select(ClassMember, User)
        .join(User, User.id == ClassMember.user_id)
        .where(ClassMember.classroom_id.in_(class_ids))
        .order_by(ClassMember.role, func.lower(User.name))
    )
    for mem, u in rows.all():
        out[mem.classroom_id].append((mem, u))
    return out


def _summary(room: Classroom, my_role: str, rows: list[tuple[ClassMember, User]]) -> dict:
    teachers = [u for m, u in rows if m.role == ROLE_TEACHER]
    manage = _can_manage(my_role)
    return {
        "id": room.id,
        "name": room.name,
        "description": room.description or "",
        "my_role": my_role,
        "can_manage": manage,
        "code": room.code if manage else None,
        "join_enabled": room.join_enabled,
        "archived": room.archived,
        "teachers": [_display(u) for u in teachers],
        "student_count": sum(1 for m, _ in rows if m.role == ROLE_STUDENT),
        "teacher_count": len(teachers),
        "created_at": room.created_at,
        "gpu_bonus_seconds": room.gpu_bonus_seconds or 0,
        "gpu_bonus_start": room.gpu_bonus_start,
        "gpu_bonus_end": room.gpu_bonus_end,
        "gpu_bonus_active": _bonus_active(room),
        "gpu_bonus_max_seconds": policy_svc.get().class_gpu_bonus_max_seconds if manage else None,
    }


def _bonus_active(room: Classroom) -> bool:
    if room.archived or not room.gpu_bonus_seconds or room.gpu_bonus_end is None:
        return False
    today = quota_svc.local_today()
    return room.gpu_bonus_end >= today and (room.gpu_bonus_start is None or room.gpu_bonus_start <= today)


def _member_out(m: ClassMember, u: User, with_contact: bool) -> MemberOut:
    return MemberOut(
        user_id=u.id,
        name=_display(u),
        username=u.username if with_contact else None,
        email=u.email if with_contact else None,
        account_role=u.role.value,
        role=m.role,
        joined_at=m.joined_at,
    )


async def _detail(session: AsyncSession, room: Classroom, my_role: str) -> ClassroomDetail:
    rows = (await _members(session, [room.id]))[room.id]
    manage = _can_manage(my_role)
    members = [
        _member_out(m, u, manage) for m, u in rows if manage or m.role == ROLE_TEACHER
    ]
    return ClassroomDetail(**_summary(room, my_role, rows), members=members)


def _notify(session: AsyncSession, user_id: int, room: Classroom, title: str, body: str) -> None:
    session.add(Notification(
        user_id=user_id, type="info", title=title[:200], body=body, link=f"/kelas/{room.id}",
    ))


@router.get("", response_model=list[ClassroomOut])
async def list_classrooms(
    scope: str = Query("mine", pattern="^(mine|all)$"),
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> list[dict]:
    mine = dict(
        (await session.execute(
            select(ClassMember.classroom_id, ClassMember.role).where(
                ClassMember.user_id == current_user.id
            )
        )).all()
    )
    stmt = select(Classroom).order_by(Classroom.archived, Classroom.created_at.desc())
    if not (scope == "all" and _is_admin(current_user)):
        if not mine:
            return []
        stmt = stmt.where(Classroom.id.in_(list(mine)))
    rooms = list((await session.scalars(stmt)).all())
    members = await _members(session, [r.id for r in rooms])
    return [_summary(r, mine.get(r.id, "admin"), members[r.id]) for r in rooms]


@router.post("", response_model=ClassroomDetail, status_code=status.HTTP_201_CREATED)
async def create_classroom(
    payload: ClassroomCreate,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_creator),
) -> ClassroomDetail:
    owned = await session.scalar(
        select(func.count()).select_from(Classroom).where(
            Classroom.created_by == current_user.id, Classroom.archived.is_(False)
        )
    )
    if (owned or 0) >= MAX_CLASSES_PER_CREATOR:
        raise HTTPException(
            status_code=400,
            detail=f"Batas {MAX_CLASSES_PER_CREATOR} kelas aktif tercapai. Arsipkan kelas lama dulu.",
        )
    for _ in range(5):
        code = _new_code()
        if not await session.scalar(select(Classroom.id).where(Classroom.code == code)):
            break
    room = Classroom(
        name=payload.name.strip(),
        description=payload.description.strip(),
        code=code,
        created_by=current_user.id,
    )
    session.add(room)
    await session.flush()
    session.add(ClassMember(
        classroom_id=room.id, user_id=current_user.id, role=ROLE_TEACHER, added_by=current_user.id,
    ))
    await audit_svc.log(session, current_user, "class.create", "classroom", room.id, room.name)
    await session.commit()
    return await _detail(session, room, ROLE_TEACHER)


@router.post("/join", response_model=ClassroomOut)
async def join_classroom(
    payload: ClassroomJoin,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    now = time.monotonic()
    fails = [t for t in _join_failures.get(current_user.id, []) if now - t < JOIN_FAIL_WINDOW]
    _join_failures[current_user.id] = fails
    if len(fails) >= JOIN_FAIL_LIMIT:
        raise HTTPException(
            status_code=429, detail="Terlalu banyak kode salah. Coba lagi 15 menit lagi."
        )
    room = await session.scalar(select(Classroom).where(Classroom.code == normalize_code(payload.code)))
    if room is None:
        fails.append(now)
        raise HTTPException(status_code=404, detail="Kode kelas tidak ditemukan. Periksa lagi kodenya.")
    mem = await _membership(session, room.id, current_user.id)
    if mem is None:
        if room.archived or not room.join_enabled:
            raise HTTPException(
                status_code=403, detail="Kelas ini sedang tidak menerima anggota baru. Hubungi pengajarnya."
            )
        count = await session.scalar(
            select(func.count()).select_from(ClassMember).where(ClassMember.classroom_id == room.id)
        )
        if (count or 0) >= MAX_MEMBERS:
            raise HTTPException(status_code=400, detail="Kelas sudah penuh.")
        mem = ClassMember(classroom_id=room.id, user_id=current_user.id, role=ROLE_STUDENT)
        session.add(mem)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            mem = await _membership(session, room.id, current_user.id)
    rows = (await _members(session, [room.id]))[room.id]
    return _summary(room, mem.role if mem else ROLE_STUDENT, rows)


@router.get("/{class_id}", response_model=ClassroomDetail)
async def get_classroom(
    class_id: int,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ClassroomDetail:
    room, my_role = await _load(session, class_id, current_user)
    return await _detail(session, room, my_role)


@router.patch("/{class_id}", response_model=ClassroomDetail)
async def update_classroom(
    class_id: int,
    payload: ClassroomUpdate,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ClassroomDetail:
    room = await _load_manage(session, class_id, current_user)
    changes = payload.model_dump(exclude_none=True)
    for key, value in changes.items():
        setattr(room, key, value.strip() if isinstance(value, str) else value)
    if changes:
        await audit_svc.log(
            session, current_user, "class.update", "classroom", room.id,
            f"{room.name}: " + ", ".join(sorted(changes)),
        )
        await session.commit()
    _, my_role = await _load(session, class_id, current_user)
    return await _detail(session, room, my_role)


MAX_BONUS_PERIOD_DAYS = 366


def _hours(seconds: int) -> str:
    return f"{seconds / 3600:g} jam"


@router.put("/{class_id}/gpu-bonus", response_model=ClassroomDetail)
async def set_gpu_bonus(
    class_id: int,
    body: GpuBonusUpdate,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ClassroomDetail:
    """A3: tambahan kuota GPU harian peserta selama periode praktikum."""
    room = await _load_manage(session, class_id, current_user)

    def bad(msg: str) -> HTTPException:
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)

    if body.seconds == 0:
        start = end = None
    else:
        if not _is_admin(current_user):
            cap = policy_svc.get().class_gpu_bonus_max_seconds
            if cap <= 0:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Admin belum mengizinkan dosen memberi tambahan kuota GPU kelas.",
                )
            if body.seconds > cap:
                raise bad(f"Maksimal tambahan untuk dosen {_hours(cap)} per hari.")
        today = quota_svc.local_today()
        start = body.start or today
        end = body.end
        if end is None:
            raise bad("Isi tanggal berakhir periode praktikum.")
        if end < start:
            raise bad("Tanggal berakhir harus sesudah tanggal mulai.")
        if end < today:
            raise bad("Periode sudah lewat.")
        if (end - start).days + 1 > MAX_BONUS_PERIOD_DAYS:
            raise bad("Periode maksimal satu tahun.")
    changed = (room.gpu_bonus_seconds, room.gpu_bonus_start, room.gpu_bonus_end) != (body.seconds, start, end)
    room.gpu_bonus_seconds, room.gpu_bonus_start, room.gpu_bonus_end = body.seconds, start, end
    if changed:
        detail = (
            f"{room.name}: +{_hours(body.seconds)}/hari {start}..{end}" if body.seconds
            else f"{room.name}: tambahan kuota dihapus"
        )
        await audit_svc.log(session, current_user, "class.gpu_bonus", "classroom", room.id, detail)
        if body.seconds:
            students = (await session.scalars(
                select(ClassMember.user_id).where(
                    ClassMember.classroom_id == room.id, ClassMember.role == ROLE_STUDENT
                )
            )).all()
            for uid in students:
                _notify(
                    session, uid, room, f"Tambahan kuota GPU dari {room.name}",
                    f"Kuota GPU harian Anda bertambah {_hours(body.seconds)} per hari "
                    f"dari {start:%d-%m-%Y} sampai {end:%d-%m-%Y}.",
                )
        await session.commit()
    _, my_role = await _load(session, class_id, current_user)
    return await _detail(session, room, my_role)


@router.post("/{class_id}/code", response_model=ClassroomDetail)
async def regenerate_code(
    class_id: int,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ClassroomDetail:
    room = await _load_manage(session, class_id, current_user)
    for _ in range(5):
        code = _new_code()
        if not await session.scalar(select(Classroom.id).where(Classroom.code == code)):
            break
    room.code = code
    await audit_svc.log(session, current_user, "class.code", "classroom", room.id, f"{room.name}: kode baru")
    await session.commit()
    _, my_role = await _load(session, class_id, current_user)
    return await _detail(session, room, my_role)


@router.delete("/{class_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_classroom(
    class_id: int,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> None:
    room = await _load_manage(session, class_id, current_user)
    await audit_svc.log(session, current_user, "class.delete", "classroom", room.id, room.name)
    mids = select(ClassMaterial.id).where(ClassMaterial.classroom_id == room.id)
    await session.execute(delete(ClassMaterialCopy).where(ClassMaterialCopy.material_id.in_(mids)))
    await session.execute(delete(ClassMaterial).where(ClassMaterial.classroom_id == room.id))
    await session.execute(delete(ClassMember).where(ClassMember.classroom_id == room.id))
    await session.delete(room)
    await session.commit()
    await asyncio.to_thread(materials_svc.remove_class, room.id)


@router.post("/{class_id}/leave", status_code=status.HTTP_204_NO_CONTENT)
async def leave_classroom(
    class_id: int,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> None:
    room = await session.get(Classroom, class_id)
    mem = await _membership(session, class_id, current_user.id) if room else None
    if mem is None:
        raise HTTPException(status_code=404, detail="Anda bukan anggota kelas ini.")
    if mem.role == ROLE_TEACHER and await _teacher_count(session, class_id) <= 1:
        raise HTTPException(
            status_code=400,
            detail="Anda pengajar terakhir. Tambahkan pengajar lain atau hapus kelasnya.",
        )
    await session.delete(mem)
    await session.commit()


async def _teacher_count(session: AsyncSession, class_id: int) -> int:
    return await session.scalar(
        select(func.count()).select_from(ClassMember).where(
            ClassMember.classroom_id == class_id, ClassMember.role == ROLE_TEACHER
        )
    ) or 0


def _like(q: str) -> str:
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


@router.get("/{class_id}/candidates", response_model=list[CandidateOut])
async def search_candidates(
    class_id: int,
    q: str = Query(..., min_length=2, max_length=100),
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> list[CandidateOut]:
    room = await _load_manage(session, class_id, current_user)
    pola = _like(q.strip().lower())
    sudah = select(ClassMember.user_id).where(ClassMember.classroom_id == room.id)
    users = (await session.scalars(
        select(User)
        .where(
            User.is_active.is_(True),
            User.id.not_in(sudah),
            or_(
                func.lower(User.name).like(pola, escape="\\"),
                func.lower(User.email).like(pola, escape="\\"),
                func.lower(User.username).like(pola, escape="\\"),
            ),
        )
        .order_by(func.lower(User.name))
        .limit(10)
    )).all()
    return [
        CandidateOut(id=u.id, name=_display(u), username=u.username, email=u.email, account_role=u.role.value)
        for u in users
    ]


async def _resolve(session: AsyncSession, ident: str) -> list[User]:
    key = ident.strip().lower()
    if not key:
        return []
    found = (await session.scalars(
        select(User).where(
            User.is_active.is_(True),
            or_(func.lower(User.email) == key, func.lower(User.username) == key),
        )
    )).all()
    if found or "@" in key:
        return list(found)
    # Bagian depan email (mis. NIM) — hanya dipakai bila cocok tepat satu akun.
    return list((await session.scalars(
        select(User).where(
            User.is_active.is_(True),
            func.lower(User.email).like(_like(key)[1:-1] + "@%", escape="\\"),
        ).limit(2)
    )).all())


@router.post("/{class_id}/members", response_model=MembersAddResult)
async def add_members(
    class_id: int,
    payload: MembersAdd,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> MembersAddResult:
    room = await _load_manage(session, class_id, current_user)
    result = MembersAddResult(added=[], already=[], not_found=[], ambiguous=[])
    targets: dict[int, tuple[str, User]] = {}
    for ident in dict.fromkeys(i.strip() for i in payload.identifiers if i.strip()):
        users = await _resolve(session, ident)
        if not users:
            result.not_found.append(ident)
        elif len(users) > 1:
            result.ambiguous.append(ident)
        else:
            targets.setdefault(users[0].id, (ident, users[0]))
    for uid in dict.fromkeys(payload.user_ids):
        u = await session.get(User, uid)
        if u is None or not u.is_active:
            result.not_found.append(f"#{uid}")
        else:
            targets.setdefault(u.id, (_display(u), u))
    existing = set((await session.scalars(
        select(ClassMember.user_id).where(ClassMember.classroom_id == room.id)
    )).all())
    room_left = MAX_MEMBERS - len(existing)
    label = "pengajar" if payload.role == ROLE_TEACHER else "anggota"
    for uid, (ident, u) in targets.items():
        if uid in existing:
            result.already.append(ident)
            continue
        if room_left <= 0:
            result.not_found.append(f"{ident} (kelas penuh)")
            continue
        session.add(ClassMember(
            classroom_id=room.id, user_id=uid, role=payload.role, added_by=current_user.id,
        ))
        room_left -= 1
        result.added.append(ident)
        if uid != current_user.id:
            _notify(
                session, uid, room, f"Anda ditambahkan ke kelas {room.name}",
                f"{_display(current_user)} menambahkan Anda sebagai {label} kelas {room.name}.",
            )
    if result.added:
        await audit_svc.log(
            session, current_user, "class.member_add", "classroom", room.id,
            f"{room.name}: +{len(result.added)} {label}",
        )
        await session.commit()
    return result


@router.patch("/{class_id}/members/{user_id}", response_model=ClassroomDetail)
async def update_member_role(
    class_id: int,
    user_id: int,
    payload: MemberRoleUpdate,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ClassroomDetail:
    room = await _load_manage(session, class_id, current_user)
    mem = await _membership(session, class_id, user_id)
    if mem is None:
        raise HTTPException(status_code=404, detail="Anggota tidak ditemukan.")
    if mem.role == ROLE_TEACHER and payload.role != ROLE_TEACHER and await _teacher_count(session, class_id) <= 1:
        raise HTTPException(status_code=400, detail="Kelas harus punya minimal satu pengajar.")
    if mem.role != payload.role:
        mem.role = payload.role
        await audit_svc.log(
            session, current_user, "class.member_role", "classroom", room.id,
            f"{room.name}: user #{user_id} -> {payload.role}",
        )
        await session.commit()
    _, my_role = await _load(session, class_id, current_user)
    return await _detail(session, room, my_role)


@router.delete("/{class_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    class_id: int,
    user_id: int,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> None:
    room = await _load_manage(session, class_id, current_user)
    mem = await _membership(session, class_id, user_id)
    if mem is None:
        raise HTTPException(status_code=404, detail="Anggota tidak ditemukan.")
    if mem.role == ROLE_TEACHER and await _teacher_count(session, class_id) <= 1:
        raise HTTPException(status_code=400, detail="Kelas harus punya minimal satu pengajar.")
    await session.delete(mem)
    await audit_svc.log(
        session, current_user, "class.member_remove", "classroom", room.id,
        f"{room.name}: user #{user_id}",
    )
    await session.commit()


# ---------------------------------------------------------------- MATERI (A2)

MAX_MATERIALS_PER_CLASS = 200


async def _material_out(
    session: AsyncSession, mats: list[ClassMaterial], user: User, manage: bool
) -> list[MaterialOut]:
    if not mats:
        return []
    ids = [m.id for m in mats]
    mine = {
        c.material_id: c
        for c in (await session.scalars(
            select(ClassMaterialCopy).where(
                ClassMaterialCopy.material_id.in_(ids), ClassMaterialCopy.user_id == user.id
            )
        )).all()
    }
    counts: dict[int, int] = {}
    if manage:
        counts = dict((await session.execute(
            select(ClassMaterialCopy.material_id, func.count())
            .where(ClassMaterialCopy.material_id.in_(ids))
            .group_by(ClassMaterialCopy.material_id)
        )).all())
    creator_ids = {m.created_by for m in mats if m.created_by}
    names = {
        u.id: _display(u)
        for u in (await session.scalars(select(User).where(User.id.in_(creator_ids)))).all()
    } if creator_ids else {}
    out = []
    for m in mats:
        c = mine.get(m.id)
        out.append(MaterialOut(
            id=m.id, title=m.title, description=m.description or "", kind=m.kind, name=m.name,
            size_bytes=m.size_bytes, file_count=m.file_count,
            created_by=names.get(m.created_by), created_at=m.created_at,
            my_copy_path=c.dest_path if c else None, my_copied_at=c.copied_at if c else None,
            copy_count=counts.get(m.id, 0) if manage else None,
        ))
    return out


async def _load_material(session: AsyncSession, room: Classroom, material_id: int) -> ClassMaterial:
    mat = await session.get(ClassMaterial, material_id)
    if mat is None or mat.classroom_id != room.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Materi tidak ditemukan.")
    return mat


@router.get("/{class_id}/materials", response_model=list[MaterialOut])
async def list_materials(
    class_id: int,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> list[MaterialOut]:
    room, my_role = await _load(session, class_id, current_user)
    mats = list((await session.scalars(
        select(ClassMaterial).where(ClassMaterial.classroom_id == room.id)
        .order_by(ClassMaterial.created_at.desc(), ClassMaterial.id.desc())
    )).all())
    return await _material_out(session, mats, current_user, _can_manage(my_role))


@router.post("/{class_id}/materials", response_model=MaterialOut, status_code=status.HTTP_201_CREATED)
async def share_material(
    class_id: int,
    body: MaterialCreate,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> MaterialOut:
    room = await _load_manage(session, class_id, current_user)
    if room.archived:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Kelas diarsipkan.")
    n = await session.scalar(
        select(func.count()).select_from(ClassMaterial).where(ClassMaterial.classroom_id == room.id)
    )
    if (n or 0) >= MAX_MATERIALS_PER_CLASS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Batas {MAX_MATERIALS_PER_CLASS} materi per kelas tercapai. Hapus materi lama dulu.",
        )
    try:
        src, kind, size, files = await asyncio.to_thread(
            materials_svc.inspect_source, current_user.id, body.path
        )
        used = await asyncio.to_thread(materials_svc.class_usage, room.id)
        if used + size > materials_svc.MAX_CLASS_BYTES:
            raise materials_svc.MaterialError("Total materi kelas melebihi 5 GB. Hapus materi lama dulu.")
        store = materials_svc.store_root()
        store.mkdir(parents=True, exist_ok=True)
        free = shutil.disk_usage(str(store)).free
        if free - size < settings.UPLOAD_DISK_HEADROOM_MB * 1024 * 1024:
            raise materials_svc.MaterialError("Ruang disk server tidak cukup untuk materi ini.")
    except (materials_svc.MaterialError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    mat = ClassMaterial(
        classroom_id=room.id, title=(body.title.strip() or src.name)[:160],
        description=body.description.strip(), kind=kind, name=src.name,
        size_bytes=size, file_count=files, created_by=current_user.id,
    )
    session.add(mat)
    await session.flush()
    try:
        await asyncio.to_thread(materials_svc.snapshot, src, room.id, mat.id)
    except Exception as exc:  # noqa: BLE001
        await session.rollback()
        await asyncio.to_thread(materials_svc.remove_material, room.id, mat.id)
        detail = str(exc) if isinstance(exc, materials_svc.MaterialError) else "Gagal menyalin materi."
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)
    await audit_svc.log(
        session, current_user, "class.material_add", "classroom", room.id,
        f"{room.name}: {mat.title} ({body.path})",
    )
    students = (await session.scalars(
        select(ClassMember.user_id).where(
            ClassMember.classroom_id == room.id, ClassMember.role == ROLE_STUDENT
        )
    )).all()
    for uid in students:
        _notify(session, uid, room, f"Materi baru di {room.name}",
                f"{_display(current_user)} membagikan \"{mat.title}\". Buka kelas lalu klik Ambil salinan.")
    await session.commit()
    return (await _material_out(session, [mat], current_user, True))[0]


@router.delete("/{class_id}/materials/{material_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_material(
    class_id: int,
    material_id: int,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> None:
    room = await _load_manage(session, class_id, current_user)
    mat = await _load_material(session, room, material_id)
    await audit_svc.log(
        session, current_user, "class.material_delete", "classroom", room.id, f"{room.name}: {mat.title}"
    )
    await session.execute(delete(ClassMaterialCopy).where(ClassMaterialCopy.material_id == mat.id))
    await session.delete(mat)
    await session.commit()
    await asyncio.to_thread(materials_svc.remove_material, room.id, material_id)


@router.post("/{class_id}/materials/{material_id}/copy", response_model=MaterialCopyResult)
async def copy_material(
    class_id: int,
    material_id: int,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> MaterialCopyResult:
    room, my_role = await _load(session, class_id, current_user)
    mat = await _load_material(session, room, material_id)
    eff = await user_policy_svc.effective(session, current_user.id)
    limit = await storage_guard.upload_limit_bytes(current_user.id, eff.max_storage_mb)
    if mat.size_bytes > limit:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Sisa kuota penyimpanan Anda tidak cukup untuk materi ini. Kosongkan Penyimpanan dulu.",
        )
    try:
        dest = await asyncio.to_thread(
            materials_svc.deliver, room.id, mat.id, mat.name, current_user.id,
            materials_svc.folder_name(room.name, room.id),
        )
    except materials_svc.MaterialError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except OSError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Gagal menyalin materi.")
    storage_guard.adjust_usage(current_user.id, mat.size_bytes)
    rec = await session.scalar(
        select(ClassMaterialCopy).where(
            ClassMaterialCopy.material_id == mat.id, ClassMaterialCopy.user_id == current_user.id
        )
    )
    if rec is None:
        session.add(ClassMaterialCopy(material_id=mat.id, user_id=current_user.id, dest_path=dest))
    else:
        rec.dest_path = dest
        rec.copied_at = dt.datetime.now(dt.timezone.utc)
    await session.commit()
    out = (await _material_out(session, [mat], current_user, _can_manage(my_role)))[0]
    return MaterialCopyResult(path=dest, material=out)
