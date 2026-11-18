"""Estimasi antrian: posisi & perkiraan waktu mulai (ETA) tiap job batch queued.

Simulasi meniru aturan scheduler (services/scheduler.py):
  - Jumlah slot = policy ``max_concurrent_jobs`` (bisa diubah admin), hanya job
    BATCH yang memakai slot. Sesi interaktif (notebook/Devbox) tidak.
  - Setiap slot punya "waktu bebas" = sisa estimasi job batch yang sedang jalan.
  - Job queued (urut prioritas lalu waktu submit) menempati slot yang paling cepat
    bebas, tetapi tidak sebelum: jadwal mulainya (scheduled_at), giliran batas job
    bersamaan pemiliknya, dan reset kuota GPU harian bila kuotanya habis.

Estimasi durasi job (berurutan): riwayat nama yang sama (estimated_runtime_seconds)
-> median job sukses terakhir milik pemilik -> median job sukses terakhir semua
pengguna -> default. Hasil dibatasi time_limit_seconds. Median hanya untuk tampilan
ETA, tidak pernah dipakai sebagai batas waktu job.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import heapq
import statistics

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.job import Job, JobDevice, JobStatus
from app.models.user import User
from app.services import cpu_pool
from app.services import gpu as gpu_svc
from app.services import policy as policy_svc
from app.services import quota as quota_svc
from app.services import user_policy as user_policy_svc

# Jumlah job sukses terakhir yang dipakai untuk median.
_HISTORY_GLOBAL = 200
_HISTORY_USER = 20
_MIN_HISTORY = 3
# Job yang sudah melewati estimasinya dianggap masih butuh minimal sekian detik.
_OVERRUN_FLOOR = 60.0


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _aware(t: dt.datetime | None) -> dt.datetime | None:
    if t is not None and t.tzinfo is None:
        return t.replace(tzinfo=dt.timezone.utc)
    return t


@dataclasses.dataclass
class RunningItem:
    user_id: int
    remaining: float  # detik sampai slot bebas; inf = tak diketahui (sesi interaktif)
    batch: bool = True


@dataclasses.dataclass
class QueuedItem:
    job_id: int
    user_id: int
    estimate: float
    not_before: float = 0.0  # detik dari sekarang (jadwal / reset kuota)
    user_limit: int = 0  # 0 = tanpa batas


@dataclasses.dataclass
class Slot:
    position: int
    start_in: float
    own_limit: bool  # tertahan oleh batas job bersamaan pemiliknya


def simulate(
    slots: int, running: list[RunningItem], queued: list[QueuedItem]
) -> list[Slot]:
    """Fungsi murni: perkiraan detik mulai tiap job queued (urutan input dipertahankan).

    Meniru scheduler: setiap kali ada slot bebas, jalankan job PERTAMA (urutan
    prioritas) yang sudah boleh jalan; job yang belum boleh (jadwal belum tiba,
    kuota habis, batas job bersamaan pemilik) dilewati sehingga job lain bisa menyalip.
    """
    inf = float("inf")
    slots = max(1, slots)
    free = sorted(r.remaining for r in running if r.batch)[:slots]
    free += [0.0] * (slots - len(free))
    heapq.heapify(free)

    # Waktu selesai job/sesi milik tiap user (untuk batas job bersamaan per user).
    ends: dict[int, list[float]] = {}
    for r in running:
        ends.setdefault(r.user_id, []).append(r.remaining)

    def active(uid: int, t: float) -> int:
        return sum(1 for e in ends.get(uid, ()) if e > t)

    result: dict[int, Slot] = {}
    pending = list(enumerate(queued, start=1))
    blocked_own: set[int] = set()
    t = 0.0
    while pending:
        t = max(t, free[0])
        if t == inf:
            break
        chosen = None
        for idx, (pos, q) in enumerate(pending):
            if q.not_before > t:
                continue
            if q.user_limit > 0 and active(q.user_id, t) >= q.user_limit:
                blocked_own.add(pos)
                continue
            chosen = idx
            break
        if chosen is None:
            # Maju ke peristiwa berikutnya: jadwal tiba atau job/sesi pemilik selesai.
            nxt = [q.not_before for _, q in pending if q.not_before > t]
            for _, q in pending:
                nxt += [e for e in ends.get(q.user_id, ()) if t < e < inf]
            if not nxt:
                break
            t = min(nxt)
            continue
        pos, q = pending.pop(chosen)
        heapq.heappop(free)
        end = t + q.estimate
        heapq.heappush(free, end)
        ends.setdefault(q.user_id, []).append(end)
        result[pos] = Slot(pos, t, pos in blocked_own)

    for pos, _ in pending:  # tak bisa diperkirakan (menunggu sesi interaktif)
        result[pos] = Slot(pos, inf, pos in blocked_own)
    return [result[pos] for pos in range(1, len(queued) + 1)]


def _median(values: list[float]) -> float | None:
    return float(statistics.median(values)) if len(values) >= _MIN_HISTORY else None


async def _history_medians(
    session: AsyncSession, user_ids: set[int]
) -> tuple[float | None, dict[int, float]]:
    rows = (
        await session.execute(
            select(Job.user_id, Job.actual_runtime_seconds)
            .where(
                Job.status == JobStatus.succeeded,
                Job.is_interactive.is_(False),
                Job.actual_runtime_seconds.is_not(None),
                Job.actual_runtime_seconds > 0,
            )
            .order_by(Job.finished_at.desc())
            .limit(_HISTORY_GLOBAL)
        )
    ).all()
    global_med = _median([float(s) for _, s in rows])
    per_user: dict[int, list[float]] = {}
    for uid, secs in rows:
        if uid in user_ids and len(per_user.setdefault(uid, [])) < _HISTORY_USER:
            per_user[uid].append(float(secs))
    user_med = {uid: m for uid, v in per_user.items() if (m := _median(v)) is not None}
    return global_med, user_med


def _estimate(
    job: Job, user_med: dict[int, float], global_med: float | None
) -> tuple[float, str]:
    """(detik, sumber) — sumber: 'riwayat' | 'pengguna' | 'umum' | 'bawaan'."""
    if job.estimated_runtime_seconds:
        est, src = float(job.estimated_runtime_seconds), "riwayat"
    elif job.user_id in user_med:
        est, src = user_med[job.user_id], "pengguna"
    elif global_med is not None:
        est, src = global_med, "umum"
    else:
        est, src = float(job.time_limit_seconds or settings.DEFAULT_JOB_TIME_LIMIT_SECONDS), "bawaan"
    if job.time_limit_seconds:
        est = min(est, float(job.time_limit_seconds))
    return max(1.0, est), src


def _remaining(job: Job, est: float, now: dt.datetime) -> float:
    started = _aware(job.started_at)
    elapsed = (now - started).total_seconds() if started else 0.0
    rem = est - elapsed
    if rem < _OVERRUN_FLOOR:
        rem = _OVERRUN_FLOOR  # sudah lewat estimasi tapi belum selesai
    if job.time_limit_seconds:
        # Job dihentikan paksa saat batas waktunya habis.
        rem = min(rem, max(0.0, job.time_limit_seconds - elapsed))
    return rem


async def compute_queue_eta(session: AsyncSession) -> list[dict]:
    now = _utcnow()
    pol = policy_svc.get()

    running = (
        await session.scalars(select(Job).where(Job.status == JobStatus.running))
    ).all()
    rows = (
        await session.execute(
            select(Job, User.name, User.email)
            .join(User, Job.user_id == User.id)
            .where(Job.status == JobStatus.queued, Job.is_interactive.is_(False))
            .order_by(Job.priority.desc(), Job.submitted_at.asc())
        )
    ).all()
    if not rows:
        return []

    user_ids = {job.user_id for job, _, _ in rows}
    global_med, user_med = await _history_medians(
        session, user_ids | {j.user_id for j in running}
    )
    eff_map = await user_policy_svc.effective_map(session, user_ids)
    used_map = await quota_svc.gpu_seconds_used_map(session, user_ids)
    reset_in = max(0.0, (quota_svc.quota_reset_at() - now).total_seconds())
    super_email = (settings.FIRST_ADMIN_EMAIL or "").strip().lower()

    run_items: list[RunningItem] = []
    for job in running:
        if job.is_interactive:
            run_items.append(RunningItem(job.user_id, float("inf"), batch=False))
        else:
            est, _ = _estimate(job, user_med, global_med)
            run_items.append(RunningItem(job.user_id, _remaining(job, est, now)))

    q_items: list[QueuedItem] = []
    meta: list[tuple[Job, str, float, str, bool]] = []
    for job, owner_name, email in rows:
        est, src = _estimate(job, user_med, global_med)
        not_before = 0.0
        sched = _aware(job.scheduled_at)
        if sched is not None:
            not_before = max(0.0, (sched - now).total_seconds())
        is_super = bool(super_email) and (email or "").strip().lower() == super_email
        eff = eff_map.get(job.user_id)
        limit = 0 if is_super or eff is None else eff.max_concurrent_jobs
        quota = 0 if is_super or eff is None else eff.daily_gpu_seconds_quota
        over_quota = quota > 0 and used_map.get(job.user_id, 0.0) >= quota
        if over_quota:
            not_before = max(not_before, reset_in)
        q_items.append(QueuedItem(job.id, job.user_id, est, not_before, limit))
        meta.append((job, owner_name, est, src, over_quota))

    sim = simulate(pol.max_concurrent_jobs, run_items, q_items)

    cpu_full = cpu_pool.is_full()
    gpu_full = gpu_svc.pool_summary()["full"]
    out: list[dict] = []
    for (job, owner_name, est, src, over_quota), slot in zip(meta, sim):
        dev = job.device or JobDevice.gpu
        sched = _aware(job.scheduled_at)
        start_in = slot.start_in
        reason: str | None = None
        if over_quota:
            reason = "quota"
        elif sched is not None and sched > now:
            reason = "scheduled"
        elif slot.own_limit or slot.start_in == float("inf"):
            reason = "own_limit"
        elif dev == JobDevice.cpu and cpu_full:
            reason = "cpu_full"
        elif dev == JobDevice.gpu and gpu_full:
            reason = "gpu_full"
        out.append(
            {
                "job_id": job.id,
                "name": job.name,
                "user_id": job.user_id,
                "owner_name": owner_name,
                "position": slot.position,
                "priority": job.priority,
                "estimated_runtime_seconds": est,
                "estimate_source": src,
                # inf = menunggu sesi interaktif pemilik yang lama selesainya tak diketahui.
                "eta_seconds": start_in if start_in != float("inf") else None,
                "device": dev,
                "waiting_reason": reason,
            }
        )
    return out
