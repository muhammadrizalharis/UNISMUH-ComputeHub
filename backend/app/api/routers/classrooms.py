"""Router RUANG KELAS (A1).

- Dosen & admin membuat kelas; pembuatnya otomatis menjadi pengajar.
- Mahasiswa bergabung memakai kode kelas; pengajar juga bisa menambah anggota manual.
- Satu kelas boleh punya beberapa pengajar; pengajar terakhir tidak bisa dikeluarkan.
- Admin melihat & mengelola semua kelas. Mahasiswa hanya melihat kelasnya sendiri,
  dan dari anggota lain hanya daftar pengajar (privasi sesama mahasiswa).
"""

from __future__ import annotations

import re
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, get_db, require_roles
from app.models.classroom import ROLE_STUDENT, ROLE_TEACHER, ClassMember, Classroom
from app.models.notification import Notification
from app.models.user import User, UserRole
from app.schemas.classroom import (
    CandidateOut,
    ClassroomCreate,
    ClassroomDetail,
    ClassroomJoin,
    ClassroomOut,
    ClassroomUpdate,
    MemberOut,
    MemberRoleUpdate,
    MembersAdd,
    MembersAddResult,
)
from app.services import audit as audit_svc

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
    }


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
    await session.execute(delete(ClassMember).where(ClassMember.classroom_id == room.id))
    await session.delete(room)
    await session.commit()


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
