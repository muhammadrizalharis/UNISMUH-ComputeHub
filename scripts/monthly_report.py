#!/usr/bin/env python3
"""Laporan penggunaan BULANAN (PDF) -> email ke semua admin + super admin.

Ringkasannya juga dikirim ke Telegram admin supaya ketahuan kalau laporan
bulanan berhenti terbit (email kampus kerap tersaring ke spam).

Dijalankan systemd timer tiap tanggal 1 (merangkum bulan sebelumnya).
Jalankan manual:
  cd backend && PYTHONPATH=. .venv/bin/python ../scripts/monthly_report.py [YYYY-MM]
Best-effort: kegagalan apa pun hanya tercatat di stdout (exit 0).
"""

from __future__ import annotations

import asyncio
import datetime as dt
import subprocess
import sys
import tempfile
from pathlib import Path

from fpdf import FPDF
from sqlalchemy import Integer, String, case, cast, func, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.alert import Alert
from app.models.job import Job, JobDevice, JobStatus
from app.models.llm_conn import LlmConnSample
from app.models.usage_history import OsUserSample
from app.models.user import User, UserRole
from app.services import email as email_svc

NOTIFY_TELEGRAM = Path(__file__).resolve().parent / "notify_telegram.py"


def _telegram(judul: str, isi: str) -> None:
    """Best-effort; skrip pemanggil selalu exit 0 sehingga tidak bisa menggagalkan."""
    try:
        subprocess.run([sys.executable, str(NOTIFY_TELEGRAM), judul, isi], timeout=30)
    except Exception as exc:  # noqa: BLE001
        print(f"Gagal kirim Telegram: {exc!r}")


def _telegram_doc(caption: str, path: Path) -> None:
    """Kirim PDF laporan sebagai DOKUMEN ke Telegram (best-effort)."""
    try:
        subprocess.run(
            [sys.executable, str(NOTIFY_TELEGRAM), "--doc", str(path), caption], timeout=120
        )
    except Exception as exc:  # noqa: BLE001
        print(f"Gagal kirim dokumen Telegram: {exc!r}")


def _period(arg: str | None) -> tuple[dt.datetime, dt.datetime, str]:
    """Rentang [awal, akhir) bulan target. Default = bulan LALU."""
    if arg:
        y, m = map(int, arg.split("-"))
        start = dt.datetime(y, m, 1, tzinfo=dt.timezone.utc)
    else:
        now = dt.datetime.now(dt.timezone.utc)
        first_this = dt.datetime(now.year, now.month, 1, tzinfo=dt.timezone.utc)
        start = (first_this - dt.timedelta(days=1)).replace(day=1)
    end = (start + dt.timedelta(days=32)).replace(day=1)
    label = start.strftime("%B %Y")
    return start, end, label


def _fmt_jam(seconds: float) -> str:
    h = seconds / 3600
    return f"{h:.1f} jam" if h >= 0.1 else f"{int(seconds)} dtk"


def _san(s: str) -> str:
    return (s or "").encode("latin-1", "replace").decode("latin-1")


def _role(r) -> str:
    return getattr(r, "value", None) or str(r)


def _mib(mb) -> str:
    v = float(mb or 0.0)
    if v <= 0:
        return "-"
    return f"{v / 1024:.1f} GB" if v >= 1024 else f"{int(v)} MB"


def _hm(t) -> str:
    try:
        return t.strftime("%m-%d %H:%M")
    except Exception:  # noqa: BLE001
        return str(t)[:16]


def _fit(s, w_mm: float) -> str:
    """Potong teks agar muat di lebar kolom (perkiraan ~1.75 mm/karakter, font 8)."""
    s = str(s)
    maxc = max(3, int(w_mm / 1.75))
    return s if len(s) <= maxc else s[: maxc - 1] + "."


class _PDF(FPDF):
    judul = ""

    def header(self) -> None:
        self.set_fill_color(31, 102, 242)
        self.rect(0, 0, 210, 18, "F")
        self.set_text_color(255, 255, 255)
        self.set_font("helvetica", "B", 12)
        self.set_xy(10, 5)
        self.cell(0, 8, _san(f"UNISMUH ComputeHub - Laporan Penggunaan {self.judul}"))
        self.set_text_color(30, 41, 59)
        self.set_y(23)

    def footer(self) -> None:
        self.set_y(-12)
        self.set_font("helvetica", "I", 7)
        self.set_text_color(120, 116, 139)
        self.cell(
            0, 6,
            _san(
                f"Halaman {self.page_no()}/{{nb}} - dibuat "
                f"{dt.datetime.now().strftime('%Y-%m-%d %H:%M')} - "
                f"{settings.public_base_url or 'ComputeHub'}"
            ),
            align="C",
        )


def _section(pdf: _PDF, title: str, sub: str = "") -> None:
    if pdf.get_y() > pdf.h - pdf.b_margin - 26:
        pdf.add_page()
    pdf.ln(2)
    pdf.set_font("helvetica", "B", 12)
    pdf.set_text_color(31, 102, 242)
    pdf.cell(0, 7, _san(title), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(60, 70, 85)
    if sub:
        pdf.set_font("helvetica", "", 8.5)
        pdf.set_text_color(110, 120, 135)
        pdf.multi_cell(0, 4.6, _san(sub))
        pdf.set_text_color(30, 41, 59)
    pdf.ln(1)


def _tbl(pdf: _PDF, headers, widths, rows, aligns=None) -> None:
    aligns = aligns or ["L"] * len(headers)

    def head() -> None:
        pdf.set_font("helvetica", "B", 8)
        pdf.set_fill_color(226, 232, 240)
        pdf.set_text_color(30, 41, 59)
        for w, h in zip(widths, headers):
            pdf.cell(w, 6, _san(str(h)), border=1, align="C", fill=True)
        pdf.ln()
        pdf.set_font("helvetica", "", 8)

    head()
    if not rows:
        pdf.set_font("helvetica", "I", 8)
        pdf.set_text_color(110, 120, 135)
        pdf.cell(0, 6, _san("(tidak ada data pada periode ini)"), new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(30, 41, 59)
        pdf.ln(1)
        return
    fill = False
    for row in rows:
        if pdf.get_y() > pdf.h - pdf.b_margin - 6:
            pdf.add_page()
            head()
        pdf.set_fill_color(247, 249, 252)
        for w, val, al in zip(widths, row, aligns):
            pdf.cell(w, 5.4, _san(_fit(val, w)), border=1, align=al, fill=fill)
        pdf.ln()
        fill = not fill
    pdf.ln(2)


def _build_pdf(label: str, D: dict) -> bytes:
    t = D["totals"]
    pdf = _PDF()
    pdf.judul = label
    pdf.set_auto_page_break(auto=True, margin=16)
    pdf.alias_nb_pages()
    pdf.add_page()

    _section(pdf, "1. Ringkasan Platform")
    pdf.set_font("helvetica", "", 10)
    bm = t.get("bm", {})
    ringkas = [
        f"Periode              : {label}",
        f"Total job selesai    : {t['jobs']} (sukses {t['jobs'] - t['failed']}, gagal {t['failed']})",
        f"Total waktu GPU      : {_fmt_jam(t['gpu_seconds'])}",
        f"Pengguna aktif       : {t['users']}",
        f"Total pelanggaran    : {t['breaches']}"
        + (
            f"  (cpu {bm.get('cpu', 0)}, ram {bm.get('ram', 0)}, "
            f"vram {bm.get('vram', 0)}, disk {bm.get('disk', 0)})"
            if t["breaches"]
            else ""
        ),
    ]
    for line in ringkas:
        pdf.cell(0, 6, _san(line), new_x="LMARGIN", new_y="NEXT")

    _section(
        pdf, "2. Pelanggaran Batas Sumber Daya (siapa saja)",
        "Tiap baris = satu kali sebuah metrik melewati ambang (tabel alerts). "
        "Nilai = angka terukur saat itu; Ambang = batas yang dilanggar.",
    )
    _tbl(
        pdf,
        ["Waktu", "Lingkup", "Subjek (siapa)", "Metrik", "Nilai", "Ambang", "Pesan"],
        [22, 20, 40, 14, 18, 18, 48],
        D["breaches"],
        ["L", "L", "L", "C", "R", "R", "L"],
    )

    _section(pdf, "3. Ringkasan Pelanggaran per Pengguna (jumlah per metrik)")
    _tbl(
        pdf,
        ["Subjek (siapa)", "Total", "CPU", "RAM", "VRAM", "Disk"],
        [72, 22, 22, 22, 22, 22],
        D["breach_sum"],
        ["L", "R", "R", "R", "R", "R"],
    )

    _section(pdf, "4. Rincian per Pengguna (job ComputeHub, urut waktu GPU)")
    _tbl(
        pdf,
        ["Nama", "Peran", "Job", "Sukses", "Gagal", "Waktu GPU", "VRAM pk", "RAM pk", "CPU pk"],
        [44, 20, 14, 18, 16, 26, 18, 18, 16],
        D["per_user"],
        ["L", "L", "R", "R", "R", "R", "R", "R", "R"],
    )

    _section(
        pdf, "5. Penggunaan Harian per Pengguna (ComputeHub)",
        "Job & waktu GPU tiap pengguna untuk setiap tanggal pada periode ini.",
    )
    _tbl(
        pdf,
        ["Tanggal", "Pengguna", "Peran", "Job", "Sukses", "Gagal", "Waktu GPU", "VRAM pk"],
        [24, 42, 20, 14, 16, 14, 26, 18],
        D["daily_ch"],
        ["L", "L", "L", "R", "R", "R", "R", "R"],
    )

    _section(
        pdf, "6. Penggunaan Server Harian per Pengguna (OS)",
        "Dari cuplikan sumber daya sistem. CPU dalam persen (100% = 1 core penuh). "
        "Tipe 'sys' = akun sistem/layanan, 'user' = akun manusia.",
    )
    _tbl(
        pdf,
        ["Tanggal", "Pengguna", "Tipe", "CPU rata2", "CPU maks", "RAM maks", "VRAM maks", "Aktivitas"],
        [22, 32, 14, 20, 20, 22, 22, 34],
        D["daily_os"],
        ["L", "L", "C", "R", "R", "R", "R", "L"],
    )

    _section(
        pdf, "7. Layanan LLM (Ollama) Harian",
        "Pemakaian layanan AI bersama per pihak per hari. VRAM = beban layanan terukur.",
    )
    _tbl(
        pdf,
        ["Tanggal", "Pihak", "Sumber", "Menit aktif", "Koneksi pk", "VRAM layanan pk"],
        [24, 44, 24, 28, 26, 34],
        D["daily_llm"],
        ["L", "L", "L", "R", "R", "R"],
    )

    return bytes(pdf.output())


async def main() -> None:
    start, end, label = _period(sys.argv[1] if len(sys.argv) > 1 else None)
    tz = settings.REPORT_TIMEZONE

    def ld(col):
        return func.date(func.timezone(tz, col))

    gpu_seconds = func.coalesce(
        func.sum(case((Job.device == JobDevice.gpu, Job.actual_runtime_seconds), else_=0.0)), 0.0
    )
    succ = func.coalesce(func.sum(case((Job.status == JobStatus.succeeded, 1), else_=0)), 0)
    fail = func.coalesce(func.sum(case((Job.status == JobStatus.failed, 1), else_=0)), 0)

    async with AsyncSessionLocal() as session:
        # (4) Rincian job per pengguna.
        pu = (
            await session.execute(
                select(
                    User.name, User.role, func.count(Job.id), succ, fail, gpu_seconds,
                    func.max(func.coalesce(Job.peak_vram_mb, 0.0)),
                    func.max(func.coalesce(Job.peak_ram_mb, 0.0)),
                    func.max(func.coalesce(Job.peak_cpu_percent, 0.0)),
                )
                .join(User, Job.user_id == User.id)
                .where(Job.finished_at.is_not(None), Job.finished_at >= start, Job.finished_at < end)
                .group_by(User.id, User.name, User.role)
                .order_by(gpu_seconds.desc())
            )
        ).all()
        per_user = [
            (n or "-", _role(r), int(j), int(s), int(f), _fmt_jam(float(g)),
             _mib(v), _mib(rm), f"{float(c):.0f}%")
            for n, r, j, s, f, g, v, rm, c in pu
        ]
        totals = {
            "jobs": sum(int(x[2]) for x in pu),
            "failed": sum(int(x[4]) for x in pu),
            "gpu_seconds": sum(float(x[5]) for x in pu),
            "users": len(pu),
        }

        # (2) Pelanggaran (breaches) — siapa saja.
        br = (
            await session.execute(
                select(
                    Alert.created_at, Alert.scope, Alert.subject, Alert.metric,
                    Alert.value, Alert.threshold, Alert.message,
                )
                .where(Alert.created_at >= start, Alert.created_at < end)
                .order_by(Alert.created_at.asc())
            )
        ).all()
        breaches = [
            (_hm(ts), sc or "", su or "", me or "",
             f"{float(v):.1f}", f"{float(th):.1f}", (msg or "").replace("\n", " "))
            for ts, sc, su, me, v, th, msg in br
        ]
        bm: dict[str, int] = {}
        for _ts, _sc, _su, me, *_ in br:
            bm[me] = bm.get(me, 0) + 1
        totals["breaches"] = len(br)
        totals["bm"] = bm

        # (3) Ringkasan pelanggaran per subjek.
        bs = (
            await session.execute(
                select(
                    Alert.subject, func.count(),
                    func.sum(cast(Alert.metric == "cpu", Integer)),
                    func.sum(cast(Alert.metric == "ram", Integer)),
                    func.sum(cast(Alert.metric == "vram", Integer)),
                    func.sum(cast(Alert.metric == "disk", Integer)),
                )
                .where(Alert.created_at >= start, Alert.created_at < end)
                .group_by(Alert.subject)
                .order_by(func.count().desc())
            )
        ).all()
        breach_sum = [
            (su or "", int(tot), int(c or 0), int(r or 0), int(v or 0), int(d or 0))
            for su, tot, c, r, v, d in bs
        ]

        # (5) Penggunaan harian ComputeHub per pengguna.
        dcol = ld(Job.finished_at)
        dch = (
            await session.execute(
                select(dcol.label("d"), User.name, User.role, func.count(Job.id), succ, fail,
                       gpu_seconds, func.max(func.coalesce(Job.peak_vram_mb, 0.0)))
                .join(User, Job.user_id == User.id)
                .where(Job.finished_at.is_not(None), Job.finished_at >= start, Job.finished_at < end)
                .group_by(dcol, User.id, User.name, User.role)
                .order_by(dcol.asc(), gpu_seconds.desc())
            )
        ).all()
        daily_ch = [
            (str(d), n or "-", _role(r), int(j), int(s), int(f), _fmt_jam(float(g)), _mib(v))
            for d, n, r, j, s, f, g, v in dch
        ]

        # (6) Penggunaan server harian (OS) per pengguna.
        ocol = ld(OsUserSample.ts)
        dos = (
            await session.execute(
                select(ocol.label("d"), OsUserSample.username, func.bool_or(OsUserSample.is_system),
                       func.avg(OsUserSample.cpu_percent), func.max(OsUserSample.cpu_percent),
                       func.max(OsUserSample.memory_mb), func.max(OsUserSample.vram_mb),
                       func.max(cast(OsUserSample.activity, String)))
                .where(OsUserSample.ts >= start, OsUserSample.ts < end)
                .group_by(ocol, OsUserSample.username)
                .order_by(ocol.asc(), func.max(OsUserSample.vram_mb).desc())
            )
        ).all()
        daily_os = [
            (str(d), u or "-", "sys" if sys_ else "user", f"{float(ca or 0):.0f}%",
             f"{float(cm or 0):.0f}%", _mib(rm), _mib(vm), act or "")
            for d, u, sys_, ca, cm, rm, vm, act in dos
        ]

        # (7) Layanan LLM harian per pihak.
        lcol = ld(LlmConnSample.ts)
        dll = (
            await session.execute(
                select(lcol.label("d"), LlmConnSample.nama,
                       func.max(cast(LlmConnSample.sumber, String)),
                       func.sum(LlmConnSample.detik_aktif), func.max(LlmConnSample.koneksi),
                       func.max(LlmConnSample.layanan_vram_mb))
                .where(LlmConnSample.ts >= start, LlmConnSample.ts < end)
                .group_by(lcol, LlmConnSample.nama)
                .order_by(lcol.asc())
            )
        ).all()
        daily_llm = [
            (str(d), nm or "-", src or "", f"{float(sec or 0) / 60:.1f}", str(int(k or 0)), _mib(vv))
            for d, nm, src, sec, k, vv in dll
        ]

        admin_rows = (
            await session.execute(
                select(User.email).where(User.role == UserRole.admin, User.is_active.is_(True))
            )
        ).scalars().all()

    data = {
        "totals": totals, "per_user": per_user, "breaches": breaches, "breach_sum": breach_sum,
        "daily_ch": daily_ch, "daily_os": daily_os, "daily_llm": daily_llm,
    }
    pdf_bytes = _build_pdf(label, data)
    fname = f"laporan-computehub-{start.strftime('%Y-%m')}.pdf"

    # Kirim PDF sebagai DOKUMEN ke Telegram (permintaan user: file, bukan cuma teks).
    tmp = Path(tempfile.gettempdir()) / fname
    tmp.write_bytes(pdf_bytes)
    caption = (
        f"Laporan bulanan {label}: {totals['jobs']} job ({totals['failed']} gagal), "
        f"GPU {_fmt_jam(totals['gpu_seconds'])}, {totals['users']} pengguna, "
        f"{totals['breaches']} pelanggaran. PDF lengkap {len(pdf_bytes) // 1024} KB."
    )
    _telegram_doc(caption, tmp)

    # Email PDF ke admin (bila SMTP siap) — tetap seperti sebelumnya.
    recipients = sorted(
        {(settings.FIRST_ADMIN_EMAIL or "").strip(), *[a.strip() for a in admin_rows]} - {""}
    )
    if recipients and settings.smtp_configured:
        body = (
            f"Laporan penggunaan UNISMUH ComputeHub periode {label} terlampir (PDF lengkap).\n\n"
            f"Ringkas: {totals['jobs']} job selesai ({totals['failed']} gagal), "
            f"total waktu GPU {_fmt_jam(totals['gpu_seconds'])}, {totals['users']} pengguna aktif, "
            f"{totals['breaches']} pelanggaran batas.\n\n- Tim {settings.PROJECT_NAME}"
        )
        await asyncio.to_thread(
            email_svc.send_email,
            recipients,
            f"Laporan penggunaan {label} - {settings.PROJECT_NAME}",
            body,
            [(fname, pdf_bytes, "application", "pdf")],
        )
        print(f"Email terkirim ke: {', '.join(recipients)}")
    else:
        print("SMTP/penerima tidak tersedia; email dilewati (Telegram tetap terkirim).")

    try:
        tmp.unlink()
    except OSError:
        pass
    print(
        f"Laporan {label} selesai: {len(pdf_bytes) // 1024} KB, {totals['breaches']} pelanggaran, "
        f"{len(daily_ch)} baris harian CH, {len(daily_os)} baris harian OS."
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:  # noqa: BLE001 — best-effort
        print(f"Laporan bulanan gagal: {exc!r}")
        _telegram("🚨 Laporan bulanan GAGAL dibuat", repr(exc))
