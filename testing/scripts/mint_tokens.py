"""Mint token QA (NON-DESTRUKTIF) untuk injeksi storageState Playwright.

Membuat token akses untuk 1 admin + 1 mahasiswa yang SUDAH ADA di DB dengan
me-reuse `users.session_token` mereka sebagai klaim `sid` (TIDAK merotasi sesi,
jadi tidak mengeluarkan/ mengganggu user manusia yang sedang login).

Output (argv[1] = folder .auth):
  admin.json    -> storageState Playwright (localStorage unismuh_token)
  student.json  -> storageState Playwright
  info.json     -> metadata {admin:{id,email,username}, student:{...}, origin}

Dijalankan oleh global-setup.ts dengan cwd = backend dan venv python.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from sqlalchemy import func, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token
from app.models.user import User

ORIGIN = "http://127.0.0.1:8088"
TOKEN_KEY = "unismuh_token"
EXPIRES_MIN = 180  # cukup untuk satu sesi pengujian penuh


def _state(token: str) -> dict:
    return {
        "cookies": [],
        "origins": [
            {
                "origin": ORIGIN,
                "localStorage": [{"name": TOKEN_KEY, "value": token}],
            }
        ],
    }


async def _pick(session, *, role: str, prefer_username: str | None = None) -> User | None:
    if prefer_username:
        u = (
            await session.execute(
                select(User).where(User.username == prefer_username)
            )
        ).scalars().first()
        # Hanya pakai akun pilihan bila ROLE-nya cocok (akun bisa berubah role;
        # mis. CHunismuhcomputehub kini admin -> jangan dipakai sbg 'mahasiswa').
        if u is not None and u.role == role:
            return u
    # Utamakan user yang SUDAH login (punya session_token) agar token uji sah
    # (sid cocok). Bila tak ada, ambil yang pertama per id.
    return (
        await session.execute(
            select(User)
            .where(User.role == role)
            .order_by(User.session_token.is_(None), User.id)
        )
    ).scalars().first()


async def main(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    async with AsyncSessionLocal() as session:
        # Admin uji = akun sekunder "Uji ComputeHub" (BUKAN super admin yang
        # dipakai user aktif) agar sesi-tunggal tidak menggugurkan token uji saat
        # user login di browser selama pengujian berjalan.
        admin = await _pick(session, role="admin", prefer_username="CHunismuhcomputehub")
        # Akun QA khusus (non-admin) agar test tak menyentuh data mahasiswa nyata.
        student = await _pick(
            session, role="mahasiswa", prefer_username="CHqastudent"
        )
        # Akun QA dosen khusus (peran 'dosen') agar sisi dosen bisa diuji end-to-end.
        dosen = await _pick(session, role="dosen", prefer_username="CHqadosen")
        # Super admin (email = FIRST_ADMIN_EMAIL) — HANYA untuk uji yang butuh hak
        # super (mis. set kuota/policy). Permukaan kecil; sisanya pakai admin stabil.
        super_email = (settings.FIRST_ADMIN_EMAIL or "").strip().lower()
        superadmin = None
        if super_email:
            superadmin = (
                await session.execute(
                    select(User).where(func.lower(User.email) == super_email)
                )
            ).scalars().first()
        if admin is None:
            raise SystemExit("Tidak ada user admin di DB.")
        if student is None:
            # fallback: pakai admin juga sebagai 'student' agar suite tetap jalan
            student = admin
        if superadmin is None:
            superadmin = admin  # fallback (kurang ideal utk uji policy)

        info = {"origin": ORIGIN, "expires_min": EXPIRES_MIN}
        pairs = [("admin", admin), ("superadmin", superadmin), ("student", student)]
        if dosen is not None:
            pairs.append(("dosen", dosen))  # token dosen hanya bila akun dosen tersedia
        # SELF-HEALING sesi: token hanya sah bila klaim `sid` == users.session_token
        # (sesi tunggal). Akun QA yang BELUM punya sesi (session_token=None = tidak ada
        # yang sedang login) -> provisikan sid baru. AMAN: tidak menendang siapa pun
        # (tak ada sesi aktif yang ditimpa); login manusia berikutnya tetap merotasi sid.
        import secrets

        from app.api.deps import invalidate_auth_cache

        changed = False
        for _, u in pairs:
            if not u.session_token:
                u.session_token = secrets.token_urlsafe(24)
                session.add(u)
                invalidate_auth_cache(u.id)
                changed = True
        if changed:
            await session.commit()
        for label, u in pairs:
            token = create_access_token(
                str(u.id), u.role, session_id=u.session_token, expires_minutes=EXPIRES_MIN
            )
            (out_dir / f"{label}.json").write_text(json.dumps(_state(token)), "utf-8")
            info[label] = {
                "id": u.id,
                "email": u.email,
                "username": u.username,
                "role": u.role,
            }
        (out_dir / "info.json").write_text(json.dumps(info, indent=2), "utf-8")
        print("MINT_OK", json.dumps({k: info[k] for k, _ in pairs}))


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".auth")
    asyncio.run(main(target))
