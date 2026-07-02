"""Mesin peringatan (alert) batas resource.

Alur:
  loop tiap ALERT_CHECK_INTERVAL_SECONDS -> ambil pemakaian OS (report_svc) ->
  bandingkan dgn ambang (AlertConfig) -> untuk pelanggaran baru (lewat cooldown):
  buat Alert, render PDF laporan user, kirim email + lampiran PDF (kalau SMTP siap).

Tanpa SMTP pun alert tetap tercatat & PDF tersimpan ke disk (graceful).
"""

from __future__ import annotations

import asyncio
import datetime as dt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.models.alert import Alert, AlertConfig
from app.models.user import User, UserRole
from app.services import email as email_svc
from app.services import pdf as pdf_svc
from app.services import report as report_svc

logger = get_logger(__name__)

# Akun sistem yang tidak perlu dipantau (bukan user "manusia").
_SYSTEM_USERS = {
    "root", "daemon", "bin", "sys", "sync", "games", "man", "lp", "mail",
    "news", "uucp", "proxy", "www-data", "backup", "list", "irc", "gnats",
    "nobody", "systemd-network", "systemd-resolve", "systemd-timesync",
    "messagebus", "syslog", "_apt", "tss", "uuidd", "tcpdump", "landscape",
    "pollinate", "sshd", "lxd", "polkitd", "chrony", "_chrony", "dnsmasq",
}


def _is_real_user(username: str) -> bool:
    if username in _SYSTEM_USERS or username.startswith("systemd"):
        return False
    try:
        import pwd

        return pwd.getpwnam(username).pw_uid >= 1000
    except Exception:  # noqa: BLE001
        return username not in _SYSTEM_USERS


async def get_config(session: AsyncSession) -> AlertConfig:
    cfg = await session.get(AlertConfig, 1)
    if cfg is None:
        cfg = AlertConfig(id=1, email_to=settings.ALERT_EMAIL_TO)
        session.add(cfg)
        await session.commit()
        await session.refresh(cfg)
    return cfg


def _breaches(usage: dict, cfg: AlertConfig) -> list[dict]:
    out: list[dict] = []
    for u in usage["os_users"]:
        if not _is_real_user(u["username"]):
            continue
        if cfg.cpu_cores > 0 and u["cpu_cores_eq"] > cfg.cpu_cores:
            out.append({
                "scope": "os_user", "subject": u["username"], "metric": "cpu",
                "value": round(u["cpu_cores_eq"], 1), "threshold": cfg.cpu_cores,
                "message": f"User {u['username']} memakai CPU ~{u['cpu_cores_eq']:.0f} core "
                           f"({u['cpu_percent']:.0f}%), melewati batas {cfg.cpu_cores:.0f} core.",
            })
        ram_gb = u["memory_mb"] / 1024
        if cfg.ram_gb > 0 and ram_gb > cfg.ram_gb:
            out.append({
                "scope": "os_user", "subject": u["username"], "metric": "ram",
                "value": round(ram_gb, 1), "threshold": cfg.ram_gb,
                "message": f"User {u['username']} memakai RAM {ram_gb:.1f} GB, "
                           f"melewati batas {cfg.ram_gb:.0f} GB.",
            })
        vram_gb = u["vram_mb"] / 1024
        if cfg.vram_gb > 0 and vram_gb > cfg.vram_gb:
            out.append({
                "scope": "os_user", "subject": u["username"], "metric": "vram",
                "value": round(vram_gb, 1), "threshold": cfg.vram_gb,
                "message": f"User {u['username']} memakai VRAM {vram_gb:.1f} GB, "
                           f"melewati batas {cfg.vram_gb:.0f} GB.",
            })
    sys = usage["system"]
    if cfg.disk_percent > 0 and sys["disk_percent"] > cfg.disk_percent:
        out.append({
            "scope": "system", "subject": "system", "metric": "disk",
            "value": round(sys["disk_percent"], 1), "threshold": cfg.disk_percent,
            "message": f"Disk / terpakai {sys['disk_percent']:.0f}%, "
                       f"melewati batas {cfg.disk_percent:.0f}%.",
        })
    return out


async def _recipients(session: AsyncSession, cfg: AlertConfig) -> list[str]:
    emails = [e.strip() for e in (cfg.email_to or "").split(",") if e.strip()]
    if emails:
        return emails
    rows = (await session.scalars(select(User.email).where(User.role == UserRole.admin))).all()
    return [e for e in rows if e]


async def _in_cooldown(session: AsyncSession, subject: str, metric: str, minutes: int) -> bool:
    if minutes <= 0:
        return False
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=minutes)
    last = await session.scalar(
        select(Alert.created_at)
        .where(Alert.subject == subject, Alert.metric == metric, Alert.created_at >= since)
        .order_by(Alert.created_at.desc())
        .limit(1)
    )
    return last is not None


async def _emit(session: AsyncSession, cfg: AlertConfig, breach: dict) -> Alert:
    """Catat Alert + render PDF (untuk user) + kirim email (kalau SMTP siap)."""
    alert = Alert(
        scope=breach["scope"],
        subject=breach["subject"],
        metric=breach["metric"],
        value=breach["value"],
        threshold=breach["threshold"],
        message=breach["message"],
    )

    pdf_bytes: bytes | None = None
    if breach["scope"] == "os_user":
        try:
            rep = await report_svc.user_report(breach["subject"])
            pdf_bytes = await asyncio.to_thread(pdf_svc.build_user_pdf, rep, breach)
            settings.alerts_path.mkdir(parents=True, exist_ok=True)
            fname = pdf_svc.pdf_filename(breach["subject"])
            path = settings.alerts_path / fname
            path.write_bytes(pdf_bytes)
            alert.pdf_path = str(path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Gagal render PDF alert %s: %s", breach["subject"], exc)

    if cfg.email_on_breach:
        try:
            recipients = await _recipients(session, cfg)
            if not recipients:
                raise RuntimeError("Tidak ada penerima email (atur email_to / akun admin).")
            attachments = []
            if pdf_bytes is not None:
                attachments.append((pdf_svc.pdf_filename(breach["subject"]), pdf_bytes, "application", "pdf"))
            body = (
                f"Peringatan batas resource server.\n\n{breach['message']}\n\n"
                f"Metrik: {breach['metric'].upper()}  |  nilai: {breach['value']}  |  batas: {breach['threshold']}\n"
                f"Waktu: {dt.datetime.now().astimezone():%d %b %Y %H:%M:%S}\n\n"
                "Detail lengkap ada di lampiran PDF.\n\n— UNISMUH ComputeHub"
            )
            await asyncio.to_thread(
                email_svc.send_email,
                recipients,
                f"[ComputeHub] Peringatan {breach['metric'].upper()} — {breach['subject']}",
                body,
                attachments,
            )
            alert.emailed = True
        except Exception as exc:  # noqa: BLE001
            alert.emailed = False
            alert.email_error = str(exc)[:500]
            logger.warning("Email alert gagal/terlewati: %s", exc)

    session.add(alert)
    await session.commit()
    await session.refresh(alert)
    return alert


async def process(session: AsyncSession, *, ignore_cooldown: bool = False) -> list[Alert]:
    """Evaluasi sekali; kembalikan alert baru yang dibuat."""
    cfg = await get_config(session)
    if not cfg.enabled and not ignore_cooldown:
        return []
    usage = await report_svc.os_usage()
    created: list[Alert] = []
    for breach in _breaches(usage, cfg):
        if not ignore_cooldown and await _in_cooldown(
            session, breach["subject"], breach["metric"], cfg.cooldown_minutes
        ):
            continue
        created.append(await _emit(session, cfg, breach))
    return created


async def send_user_alert(session: AsyncSession, username: str) -> Alert:
    """Manual: paksa buat & kirim laporan PDF user (uji / on-demand)."""
    cfg = await get_config(session)
    breach = {
        "scope": "os_user", "subject": username, "metric": "manual",
        "value": 0.0, "threshold": 0.0,
        "message": f"Laporan manual penggunaan resource user {username}.",
    }
    return await _emit(session, cfg, breach)


async def notify(
    session: AsyncSession,
    *,
    scope: str,
    subject: str,
    metric: str,
    value: float,
    threshold: float,
    message: str,
) -> Alert | None:
    """Catat + email SATU pelanggaran custom (mis. kuota disk /persist per-user).

    Memakai pipeline Alerts yang sama: hormati AlertConfig.enabled, email_on_breach,
    dan cooldown per (subject, metric). Return None bila alert nonaktif / masih cooldown.
    """
    cfg = await get_config(session)
    if not cfg.enabled:
        return None
    if await _in_cooldown(session, subject, metric, cfg.cooldown_minutes):
        return None
    return await _emit(session, cfg, {
        "scope": scope, "subject": subject, "metric": metric,
        "value": value, "threshold": threshold, "message": message,
    })


class AlertMonitor:
    """Loop latar belakang yang mengevaluasi pelanggaran batas secara berkala."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="alert-monitor")
        logger.info("AlertMonitor jalan (interval %ss).", settings.ALERT_CHECK_INTERVAL_SECONDS)

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None

    async def _loop(self) -> None:
        interval = max(30, int(settings.ALERT_CHECK_INTERVAL_SECONDS))
        while not self._stop.is_set():
            try:
                async with AsyncSessionLocal() as session:
                    new = await process(session)
                    if new:
                        logger.info("AlertMonitor: %d peringatan baru.", len(new))
            except Exception as exc:  # noqa: BLE001
                logger.warning("AlertMonitor tick gagal: %s", exc)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass


alert_monitor = AlertMonitor()
