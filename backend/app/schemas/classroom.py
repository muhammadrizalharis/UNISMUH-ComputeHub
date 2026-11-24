"""Skema Ruang Kelas."""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field

MemberRole = Literal["pengajar", "mahasiswa"]


class ClassroomCreate(BaseModel):
    name: str = Field(min_length=3, max_length=120)
    description: str = Field(default="", max_length=1000)


class ClassroomUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=3, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    join_enabled: bool | None = None
    archived: bool | None = None


class ClassroomJoin(BaseModel):
    code: str = Field(min_length=4, max_length=32)


class MembersAdd(BaseModel):
    # Email, username, atau bagian depan email (mis. NIM) — satu per baris.
    identifiers: list[str] = Field(default_factory=list, max_length=200)
    user_ids: list[int] = Field(default_factory=list, max_length=200)
    role: MemberRole = "mahasiswa"


class MemberRoleUpdate(BaseModel):
    role: MemberRole


class MemberOut(BaseModel):
    user_id: int
    name: str
    username: str | None = None
    email: str | None = None
    account_role: str
    role: str
    joined_at: dt.datetime


class ClassroomOut(BaseModel):
    id: int
    name: str
    description: str
    my_role: str  # pengajar | mahasiswa | admin (admin bukan anggota)
    can_manage: bool
    code: str | None = None  # hanya untuk pengajar/admin
    join_enabled: bool
    archived: bool
    teachers: list[str]
    student_count: int
    teacher_count: int
    created_at: dt.datetime


class ClassroomDetail(ClassroomOut):
    # Pengajar/admin: semua anggota. Mahasiswa: hanya daftar pengajar.
    members: list[MemberOut]


class MembersAddResult(BaseModel):
    added: list[str]
    already: list[str]
    not_found: list[str]
    ambiguous: list[str]


class CandidateOut(BaseModel):
    id: int
    name: str
    username: str | None = None
    email: str
    account_role: str


class MaterialCreate(BaseModel):
    # Path relatif di workspace (/persist) pengajar.
    path: str = Field(min_length=1, max_length=1024)
    title: str = Field(default="", max_length=160)
    description: str = Field(default="", max_length=2000)


class MaterialOut(BaseModel):
    id: int
    title: str
    description: str
    kind: str
    name: str
    size_bytes: int
    file_count: int
    created_by: str | None
    created_at: dt.datetime
    # Salinan milik user yang meminta (None bila belum mengambil).
    my_copy_path: str | None = None
    my_copied_at: dt.datetime | None = None
    # Hanya untuk pengajar/admin.
    copy_count: int | None = None


class MaterialCopyResult(BaseModel):
    path: str
    material: MaterialOut
