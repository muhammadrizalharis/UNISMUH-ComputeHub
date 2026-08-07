"""Laporan DETAIL per AKUN ComputeHub (padanan `report.user_report` untuk akun OS).

`user_report` menjawab "apa yang dilakukan akun Linux di server". Modul ini menjawab
pertanyaan yang berbeda: "apa yang dilakukan sebuah AKUN PLATFORM" -- job yang
dijalankan, kuota yang berlaku, sesi interaktif, dan pemakaian Asisten AI. Keduanya
tidak bisa saling menggantikan karena satu orang bisa punya akun di kedua sisi.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import Integer, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.job import Job, JobDevice, JobStatus
from app.models.user import User
from app.services import assistant_usage as assistant_usage_svc
from app.services import storage_guard
from app.services import usage_history as usage_history_svc
from app.services import user_policy as user_policy_svc

logger = get_logger(__name__)


def _iso(v) -> str:
    return v.isoformat() if v else ""


def _temuan_rekomendasi(
    j: dict, k: dict, simpan: dict, asisten: dict, akun: dict, harian: list[dict]
) -> tuple[list[dict], dict, str]:
    """Temuan + rekomendasi + kesimpulan untuk satu akun platform.

    Ditulis sebagai aturan sederhana yang bisa ditelusuri, bukan skor buram:
    tiap temuan menyebut angka yang mendasarinya agar bisa diperiksa ulang.
    """
    temuan: list[dict] = []
    rek: dict[str, list[str]] = {"high": [], "medium": [], "low": []}

    total = j["total"]
    selesai = j["sukses"] + j["gagal"]
    rasio_gagal = (j["gagal"] / selesai) if selesai else 0.0

    if not akun["aktif"]:
        temuan.append({"level": "warn", "text": "Akun berstatus NONAKTIF."})
        rek["high"].append("Aktifkan kembali bila pemiliknya masih berhak memakai platform.")

    if total == 0:
        temuan.append({"level": "info", "text": "Belum pernah menjalankan job sama sekali."})
        rek["medium"].append(
            "Pastikan pemiliknya sudah mendapat panduan; akun tanpa aktivitas "
            "biasanya menandakan kendala saat memulai."
        )
    else:
        temuan.append(
            {
                "level": "info",
                "text": (
                    f"{total} job total, {j['sukses']} sukses / {j['gagal']} gagal "
                    f"({rasio_gagal * 100:.0f}% gagal), waktu GPU {j['gpu_detik'] / 3600:.2f} jam."
                ),
            }
        )

    if selesai >= 5 and rasio_gagal >= 0.3:
        temuan.append(
            {"level": "warn", "text": f"Tingkat kegagalan tinggi ({rasio_gagal * 100:.0f}%)."}
        )
        rek["high"].append(
            "Periksa log job yang gagal; pola berulang biasanya soal dependensi "
            "atau permintaan VRAM melebihi kuota."
        )

    kuota_mb = float(simpan.get("kuota_mb") or 0.0)
    pakai_mb = float(simpan.get("dipakai_mb") or 0.0)
    if kuota_mb > 0:
        rasio = pakai_mb / kuota_mb
        if rasio >= 0.9:
            temuan.append(
                {
                    "level": "warn",
                    "text": f"Penyimpanan hampir penuh: {rasio * 100:.0f}% dari kuota.",
                }
            )
            rek["high"].append("Minta pemilik merapikan berkas, atau naikkan kuota penyimpanan.")
        elif rasio >= 0.7:
            temuan.append(
                {"level": "info", "text": f"Penyimpanan terpakai {rasio * 100:.0f}% dari kuota."}
            )
            rek["low"].append("Pantau penyimpanan; sudah lewat dua pertiga kuota.")

    if j["vram_max_mb"] and k["vram_mb"] and j["vram_max_mb"] >= k["vram_mb"] * 0.9:
        temuan.append(
            {
                "level": "warn",
                "text": (
                    f"VRAM puncak {j['vram_max_mb']:.0f} MB mendekati plafon "
                    f"{k['vram_mb']:.0f} MB."
                ),
            }
        )
        rek["medium"].append(
            "Pertimbangkan menaikkan plafon VRAM, atau sarankan mengecilkan batch size."
        )

    if asisten.get("permintaan"):
        temuan.append(
            {
                "level": "info",
                "text": (
                    f"Memakai Asisten AI {asisten['permintaan']} kali "
                    f"({float(asisten.get('detik', 0)) / 60:.1f} menit proses)."
                ),
            }
        )

    if akun["pintu_admin"]:
        temuan.append({"level": "info", "text": "Memiliki hak masuk pintu admin."})
        rek["low"].append("Tinjau berkala apakah hak admin masih diperlukan.")

    if k["boleh_multi_gpu"]:
        temuan.append({"level": "info", "text": "Diizinkan memakai 2 GPU sekaligus."})

    hari_aktif = len(harian)
    if hari_aktif:
        temuan.append(
            {"level": "info", "text": f"Tercatat aktif pada {hari_aktif} hari dalam rentang ini."}
        )

    if not rek["high"] and not rek["medium"]:
        rek["low"].append("Tidak ada tindakan yang mendesak; pemakaian dalam batas wajar.")

    if total == 0:
        kesimpulan = (
            f"Akun {akun['nama'] or akun['email']} ({akun['role']}) belum menghasilkan "
            "aktivitas komputasi apa pun pada platform."
        )
    else:
        kesimpulan = (
            f"Akun {akun['nama'] or akun['email']} ({akun['role']}) menjalankan {total} job "
            f"dengan total waktu GPU {j['gpu_detik'] / 3600:.2f} jam dan tingkat keberhasilan "
            f"{(1 - rasio_gagal) * 100:.0f}%. Penyimpanan terpakai "
            f"{pakai_mb / 1024:.2f} GB"
            + (f" dari kuota {kuota_mb / 1024:.0f} GB." if kuota_mb else " (tanpa kuota).")
        )
    return temuan, rek, kesimpulan


async def account_report(
    session: AsyncSession, user_id: int, *, days: int = 30
) -> dict | None:
    """Laporan lengkap satu akun ComputeHub. None bila akun tak ada."""
    user = await session.get(User, user_id)
    if user is None:
        return None

    eff = await user_policy_svc.effective(session, user_id)

    # --- Ringkasan job sepanjang masa ---
    agg = (
        await session.execute(
            select(
                func.count().label("total"),
                func.sum(func.cast(Job.status == JobStatus.succeeded, Integer)).label("sukses"),
                func.sum(func.cast(Job.status == JobStatus.failed, Integer)).label("gagal"),
                func.sum(func.cast(Job.status == JobStatus.cancelled, Integer)).label("batal"),
                func.sum(func.cast(Job.status == JobStatus.running, Integer)).label("jalan"),
                func.sum(func.cast(Job.status == JobStatus.queued, Integer)).label("antre"),
                func.sum(
                    func.cast(Job.device == JobDevice.gpu, Integer)
                    * func.coalesce(Job.actual_runtime_seconds, 0.0)
                ).label("gpu_detik"),
                func.sum(func.coalesce(Job.actual_runtime_seconds, 0.0)).label("total_detik"),
                func.max(Job.peak_vram_mb).label("vram_max"),
                func.max(Job.peak_ram_mb).label("ram_max"),
                func.max(Job.peak_cpu_percent).label("cpu_max"),
                func.min(Job.submitted_at).label("pertama"),
                func.max(Job.submitted_at).label("terakhir"),
            ).where(Job.user_id == user_id)
        )
    ).one()

    # --- Job terakhir (bukti konkret, bukan sekadar angka) ---
    rows = (
        await session.execute(
            select(Job)
            .where(Job.user_id == user_id)
            .order_by(Job.id.desc())
            .limit(15)
        )
    ).scalars().all()
    job_terakhir = [
        {
            "id": j.id,
            "nama": j.name or f"Job #{j.id}",
            "status": j.status.value if hasattr(j.status, "value") else str(j.status),
            "device": j.device.value if hasattr(j.device, "value") else str(j.device),
            "gpu_index": j.gpu_index,
            "interaktif": bool(j.is_interactive),
            "detik": float(j.actual_runtime_seconds or 0.0),
            "vram_mb": float(j.peak_vram_mb or 0.0),
            "ram_mb": float(j.peak_ram_mb or 0.0),
            "selesai": _iso(j.finished_at),
        }
        for j in rows
    ]

    harian = await usage_history_svc.daily_summary_computehub(
        session, days=days, user_id=user_id
    )
    asisten = [
        a
        for a in await assistant_usage_svc.ringkasan(session, days=days, limit=200)
        if a["user_id"] == user_id
    ]

    # CATATAN PENTING: akun Linux di kolom `username` (mis. CH105841103223) hanya
    # nama logis -- TIDAK ada di /etc/passwd. Container job berjalan sebagai uid
    # platform, sehingga pemakaian resource akun ini TIDAK muncul pada cuplikan
    # per-user OS. Sumber resource yang sahih adalah metrik per-job di bawah.
    os_user = (user.username or "").strip()

    # Pemakaian penyimpanan pribadi (/persist) -- best-effort.
    dipakai_mb = 0.0
    try:
        dipakai_mb = float(await storage_guard.user_disk_used_bytes(user_id)) / 1024 / 1024
    except Exception as exc:  # noqa: BLE001
        logger.debug("Pemakaian disk akun %s tak terbaca: %s", user_id, exc)

    # --- Yang SEDANG berjalan milik akun ini (potret saat laporan dibuat) ---
    aktif_rows = (
        await session.execute(
            select(Job)
            .where(
                Job.user_id == user_id,
                Job.status.in_([JobStatus.running, JobStatus.queued]),
            )
            .order_by(Job.id.desc())
        )
    ).scalars().all()
    sekarang = [
        {
            "id": x.id,
            "nama": x.name or f"Job #{x.id}",
            "status": x.status.value if hasattr(x.status, "value") else str(x.status),
            "interaktif": bool(x.is_interactive),
            "device": x.device.value if hasattr(x.device, "value") else str(x.device),
            "gpu_index": x.gpu_index,
            "pid": x.pid,
            "mulai": _iso(x.started_at),
            "vram_mb": float(x.peak_vram_mb or 0.0),
            "ram_mb": float(x.peak_ram_mb or 0.0),
            "cpu_percent": float(x.peak_cpu_percent or 0.0),
        }
        for x in aktif_rows
    ]

    # --- Perbandingan dengan akun lain (posisi relatif, bukan sekadar angka) ---
    banding_rows = (
        await session.execute(
            select(
                User.id,
                func.max(User.name).label("nama"),
                func.count(Job.id).label("jobs"),
                func.sum(
                    func.cast(Job.device == JobDevice.gpu, Integer)
                    * func.coalesce(Job.actual_runtime_seconds, 0.0)
                ).label("gpu_detik"),
            )
            .select_from(User)
            .join(Job, Job.user_id == User.id, isouter=True)
            .group_by(User.id)
            .order_by(func.coalesce(func.sum(
                func.cast(Job.device == JobDevice.gpu, Integer)
                * func.coalesce(Job.actual_runtime_seconds, 0.0)
            ), 0.0).desc())
            .limit(10)
        )
    ).all()
    perbandingan = [
        {
            "user_id": b.id,
            "nama": b.nama or "-",
            "jobs": int(b.jobs or 0),
            "gpu_detik": round(float(b.gpu_detik or 0.0), 1),
            "ini": b.id == user_id,
        }
        for b in banding_rows
    ]

    job_ringkas = {
        "total": int(agg.total or 0),
        "sukses": int(agg.sukses or 0),
        "gagal": int(agg.gagal or 0),
        "batal": int(agg.batal or 0),
        "jalan": int(agg.jalan or 0),
        "antre": int(agg.antre or 0),
        "gpu_detik": round(float(agg.gpu_detik or 0.0), 1),
        "total_detik": round(float(agg.total_detik or 0.0), 1),
        "vram_max_mb": round(float(agg.vram_max or 0.0), 1),
        "ram_max_mb": round(float(agg.ram_max or 0.0), 1),
        "cpu_max_percent": round(float(agg.cpu_max or 0.0), 1),
        "pertama": _iso(agg.pertama),
        "terakhir": _iso(agg.terakhir),
    }
    kuota_ringkas = {
        "gpu_detik_harian": eff.daily_gpu_seconds_quota,
        "job_serempak": eff.max_concurrent_jobs,
        "batas_waktu_detik": eff.max_time_limit_seconds,
        "vram_mb": eff.max_gpu_memory_mb,
        "ram_mb": eff.max_ram_mb,
        "cpu_threads": eff.max_cpu_threads,
        "storage_mb": eff.max_storage_mb,
        "model_asisten": eff.assistant_model,
        "boleh_multi_gpu": eff.allow_multi_gpu,
    }
    akun_ringkas = {
        "id": user.id,
        "nama": user.name,
        "email": user.email,
        "username_os": os_user,
        "role": user.role.value if hasattr(user.role, "value") else str(user.role),
        "aktif": bool(user.is_active),
        "pintu_admin": bool(user.can_admin),
        "sso": bool(user.sso_sub),
        "dibuat": _iso(user.created_at),
    }
    simpan = {
        "dipakai_mb": round(dipakai_mb, 1),
        "kuota_mb": float(eff.max_storage_mb or 0.0),
    }
    asis = asisten[0] if asisten else {}
    temuan, rekomendasi, kesimpulan = _temuan_rekomendasi(
        job_ringkas, kuota_ringkas, simpan, asis, akun_ringkas, harian
    )

    return {
        "generated_at": dt.datetime.now().astimezone().strftime("%d %b %Y %H:%M:%S %Z"),
        "days": days,
        "akun": akun_ringkas,
        "kuota": kuota_ringkas,
        "job": job_ringkas,
        "penyimpanan": simpan,
        "sekarang": sekarang,
        "harian": harian,
        "asisten": asis,
        "job_terakhir": job_terakhir,
        "perbandingan": perbandingan,
        "temuan": temuan,
        "rekomendasi": rekomendasi,
        "kesimpulan": kesimpulan,
    }
