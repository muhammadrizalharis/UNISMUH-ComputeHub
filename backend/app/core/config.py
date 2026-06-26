"""Application configuration.

Semua setting dibaca dari environment / file `.env` (lihat `.env.example`).
Tidak perlu mengubah kode untuk pindah stack (SQLite <-> PostgreSQL, dll).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# .../backend  (file ini: backend/app/core/config.py -> parents[2] = backend)
BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Konfigurasi aplikasi (di-load sekali saat startup)."""

    model_config = SettingsConfigDict(
        env_file=str(BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # --- Umum ---
    PROJECT_NAME: str = "UNISMUH ComputeHub"
    ENV: str = "production"
    API_V1_PREFIX: str = "/api/v1"
    HOST: str = "127.0.0.1"
    PORT: int = 8000

    # --- Keamanan ---
    SECRET_KEY: str = "CHANGE_ME_PLEASE"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 720  # 12 jam (lebih pendek = lebih aman)

    # --- Rate limit login (anti brute-force) ---
    LOGIN_RATE_LIMIT_MAX_ATTEMPTS: int = 10    # maks. percobaan GAGAL per window
    LOGIN_RATE_LIMIT_WINDOW_SECONDS: int = 300  # jendela hitung percobaan (5 menit)
    LOGIN_RATE_LIMIT_BLOCK_SECONDS: int = 600   # lama diblokir setelah lewat batas

    # --- Database ---
    DATABASE_URL: str = "sqlite+aiosqlite:///./unismuh_ai_cloud.db"
    DB_REQUIRE_SSL: bool = True   # wajibkan SSL utk Postgres remote (mis. Supabase)

    # --- Logging (stdout + file dengan rotasi) ---
    LOG_DIR: str = "./logs"
    LOG_FILE: str = "app.log"
    LOG_LEVEL: str = "INFO"
    LOG_MAX_BYTES: int = 5_000_000   # ~5MB per file sebelum dirotasi
    LOG_BACKUP_COUNT: int = 5        # jumlah berkas rotasi yang disimpan
    LOG_TO_FILE: bool = True

    # --- CORS (comma-separated; lihat properti cors_origins) ---
    BACKEND_CORS_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000"

    # --- Scheduler & monitoring ---
    SCHEDULER_MODE: str = "local"
    SCHEDULER_INTERVAL_SECONDS: float = 8.0
    MONITOR_SAMPLE_INTERVAL_SECONDS: float = 30.0
    # Plafon job paralel GLOBAL. Pembatas nyata kini = kolam GPU (VRAM) + kolam
    # CPU (core); angka ini hanya pagar atas supaya loop tidak kebablasan.
    MAX_CONCURRENT_JOBS: int = 32

    # --- Batas CPU proses platform (jadi "warga server" yang baik) ---
    # Proses orkestrasi (web + scheduler + monitor + laporan) WAJIB ringan.
    PLATFORM_NICE: int = 15            # 0..19; makin tinggi makin mengalah ke user lain
    PLATFORM_CPU_THREADS: int = 2      # plafon thread BLAS/OpenMP/torch utk proses ini
    PLATFORM_CPU_AFFINITY: str = ""    # "" = semua core; mis. "0-3" atau "0,1,2,3"
    REPORT_CACHE_TTL_SECONDS: float = 20.0  # cache scan proses OS (hemat CPU saat polling)

    # --- Peringatan (alert) batas resource + email PDF ---
    ALERT_CHECK_INTERVAL_SECONDS: int = 300   # interval cek pelanggaran batas
    ALERTS_DIR: str = "./_alerts"             # tempat simpan PDF peringatan
    # Penerima default laporan peringatan (dipisah koma). Kosong = fallback email admin.
    ALERT_EMAIL_TO: str = ""
    # SMTP (kosongkan SMTP_HOST untuk menonaktifkan pengiriman email)
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""
    SMTP_USE_TLS: bool = True
    SMTP_USE_SSL: bool = False
    SMTP_TIMEOUT: int = 20

    # --- Kuota resource (0 = auto-detect) ---
    TOTAL_CPU_CORES: int = 0
    TOTAL_MEMORY_MB: int = 0
    RESERVED_MEMORY_MB: int = 2048
    RESERVED_CPU_CORES: int = 2

    # --- Eksekusi job ---
    JOBS_DIR: str = "./_jobs"
    ENABLE_JOB_EXECUTION: bool = True

    # --- Batas resource keras subprocess job/kernel (mitigasi DoS; 0 = lewati) ---
    # CATATAN: RLIMIT_AS/memori virtual TIDAK dipakai (CUDA/PyTorch reserve address
    # space besar -> akan crash). Plafon memori ditegakkan via sampler (advisory).
    JOB_RLIMIT_NPROC: int = 16384        # maks proses/thread real-UID (cegah fork bomb); 0 = off
    JOB_RLIMIT_FSIZE_MB: int = 0         # maks ukuran 1 file (MB); 0 = off
    JOB_RLIMIT_NOFILE: int = 0           # maks file descriptor terbuka; 0 = off
    JOB_RLIMIT_NO_CORE: bool = True      # True = nonaktifkan core dump (cegah disk fill)

    # --- Sandbox isolasi (user-namespace via unshare; non-root) ---
    # True = bungkus eksekusi job/kernel dalam user+mount namespace yang MENYEMBUNYIKAN
    # file rahasia (backend/.env) dari kode user, sekaligus memblok ptrace ke proses
    # backend. GPU & jaringan TETAP jalan. Otomatis nonaktif bila unshare tak tersedia.
    JOB_SANDBOX_ENABLED: bool = True

    # --- Retensi & pembersihan otomatis (hemat disk server) ---
    JOB_RETENTION_DAYS: int = 14         # hapus folder job terminal > N hari (0 = off)
    ALERT_RETENTION_DAYS: int = 30       # hapus PDF peringatan > N hari (0 = off)
    CLEANUP_INTERVAL_HOURS: float = 6.0  # interval scan pembersihan

    # --- Enforcement GPU (job GPU di-pin & wajib lihat CUDA) ---
    ENFORCE_GPU: bool = True
    ALLOW_CPU_FALLBACK: bool = False
    REQUIRE_CUDA_PREFLIGHT: bool = True
    GPU_VISIBLE_DEVICES: str = ""  # "" = semua GPU; atau "0,1"
    GPU_MIN_FREE_MEMORY_MB: float = 1024.0

    # --- Komputasi CPU (mis. Random Forest/ML klasik) dgn kolam core + antrian ---
    ALLOW_CPU_JOBS: bool = True          # True = job/sesi boleh pilih device CPU
    CPU_POOL_CORES: int = 48             # core utk job platform (0 = nproc - reserved)
    CPU_RESERVED_CORES: int = 16         # core disisakan utk OS + user server lain

    # --- GPU SHARING (banyak beban kerja berbagi 1 GPU sesuai VRAM) ---
    GPU_SHARE_ENABLED: bool = True            # True = boleh >1 job/sesi per GPU
    GPU_MAX_WORKLOADS_PER_GPU: int = 4        # batas beban kerja serempak/GPU (0 = tak terbatas)
    GPU_SHARE_HEADROOM_MB: float = 2048.0     # sisakan VRAM bebas tiap GPU (cadangan aman)

    # --- Sampling resource per-job (RAM/VRAM/GPU) ---
    JOB_SAMPLE_INTERVAL_SECONDS: float = 5.0

    # --- Sesi interaktif (notebook/console ala Colab; kernel hidup di GPU) ---
    INTERACTIVE_ENABLED: bool = True
    INTERACTIVE_MAX_SESSIONS: int = 8              # total kernel hidup serempak (sharing -> > jumlah GPU)
    INTERACTIVE_DEFAULT_VRAM_MB: float = 8192.0    # anggaran VRAM default 1 sesi (bila peran tanpa batas)
    INTERACTIVE_IDLE_TIMEOUT_SECONDS: int = 1800   # 30 mnt idle -> kernel dimatikan (bebaskan GPU)
    INTERACTIVE_MAX_EXEC_SECONDS: int = 600        # batas waktu eksekusi 1 sel (anti runaway)
    INTERACTIVE_MAX_SESSION_SECONDS: int = 7200    # umur maks 1 sesi (2 jam) -> bebaskan GPU
    INTERACTIVE_STARTUP_TIMEOUT_SECONDS: int = 90  # tunggu kernel siap
    # Auto-antrian sesi interaktif (auto-mulai saat slot kosong):
    INTERACTIVE_GRANT_TTL_SECONDS: int = 120       # jatah giliran (klaim slot) sebelum kedaluwarsa
    INTERACTIVE_QUEUE_TTL_SECONDS: int = 180        # tiket antri dibuang bila berhenti dipantau (tab ditutup)

    # --- Asisten AI notebook (chat ala Copilot; provider OpenAI-compatible) ---
    # Default base URL menunjuk GitHub Models. Aktif begitu ASSISTANT_API_KEY diisi
    # (GitHub Personal Access Token, scope: models:read) di .env. Bisa diganti ke
    # OpenAI/OpenRouter/Groq atau server vLLM/Ollama lokal tanpa ubah kode.
    ASSISTANT_ENABLED: bool = True
    ASSISTANT_API_BASE: str = "https://models.github.ai/inference"
    ASSISTANT_API_KEY: str = ""                     # RAHASIA -> isi di .env (JANGAN di .env.example)
    ASSISTANT_MODEL: str = "openai/gpt-4o-mini"
    ASSISTANT_PROVIDER_LABEL: str = "GitHub Models"
    ASSISTANT_MAX_TOKENS: int = 1024
    ASSISTANT_TEMPERATURE: float = 0.2
    ASSISTANT_TIMEOUT_SECONDS: float = 60.0

    # --- Batas waktu eksekusi job (timeout, detik) ---
    DEFAULT_JOB_TIME_LIMIT_SECONDS: int = 3600       # default 1 jam
    STUDENT_MAX_TIME_LIMIT_SECONDS: int = 7200       # plafon (mahasiswa) 2 jam
    MAX_JOB_TIME_LIMIT_SECONDS: int = 86400          # batas absolut (admin) 24 jam
    MIN_JOB_TIME_LIMIT_SECONDS: int = 120            # lantai batas waktu otomatis
    RUNTIME_SAFETY_FACTOR: float = 1.5               # faktor pengaman estimasi

    # --- Upload project (ZIP) ---
    MAX_UPLOAD_SIZE_MB: int = 200                    # ukuran arsip
    MAX_UPLOAD_UNCOMPRESSED_MB: int = 1024           # anti zip-bomb
    MAX_UPLOAD_FILES: int = 5000                     # batas jumlah file

    # --- Auto install dependency (requirements.txt) ---
    AUTO_PIP_INSTALL: bool = True                    # default install otomatis
    PIP_INSTALL_TIMEOUT_SECONDS: int = 600           # batas waktu pip install

    # --- Kuota GPU harian per mahasiswa (detik, rolling 24 jam) ---
    STUDENT_DAILY_GPU_SECONDS_QUOTA: int = 14400     # 4 jam/hari; 0 = tanpa batas

    # --- Kebijakan peran (mahasiswa dibatasi, dosen bebas) ---
    # Mahasiswa: prioritas TIDAK bisa diatur (mengikuti urutan submit / FIFO),
    # dan jumlah job berjalan dibatasi.
    STUDENT_MAX_CONCURRENT_JOBS: int = 1
    STUDENT_MAX_GPU_MEMORY_MB: float = 8192.0  # plafon VRAM per job (MB); 0 = tanpa batas
    STUDENT_MAX_RAM_MB: float = 8192.0      # plafon RAM proses (MB); 0 = tanpa batas
    STUDENT_MAX_CPU_THREADS: int = 2        # maks core komputasi; 0 = pakai default
    # Dosen: batas pemakaian resource (angka diisi super admin via UI; 0 = tanpa batas).
    DOSEN_MAX_CONCURRENT_JOBS: int = 1               # maks job/sesi GPU berjalan / dosen
    DOSEN_DAILY_GPU_SECONDS_QUOTA: int = 0           # detik/24jam; 0 = tanpa batas
    DOSEN_MAX_GPU_MEMORY_MB: float = 8192.0          # plafon VRAM per job (MB); 0 = penuh
    DOSEN_MAX_RAM_MB: float = 8192.0                 # plafon RAM proses (MB); 0 = tanpa batas
    DOSEN_MAX_CPU_THREADS: int = 2                   # maks core komputasi; 0 = pakai default
    # Admin BIASA juga bisa dibatasi (super admin tetap bebas & jadi pengatur). 0 = tanpa batas.
    ADMIN_MAX_CONCURRENT_JOBS: int = 0
    ADMIN_DAILY_GPU_SECONDS_QUOTA: int = 0
    ADMIN_MAX_GPU_MEMORY_MB: float = 8192.0
    ADMIN_MAX_RAM_MB: float = 8192.0
    ADMIN_MAX_CPU_THREADS: int = 2
    # Core komputasi default per job bila plafon peran = 0 (jaga server bersama).
    JOB_DEFAULT_CPU_THREADS: int = 2
    # Dosen & admin boleh atur prioritas (selalu di atas mahasiswa).
    DOSEN_DEFAULT_PRIORITY: int = 20
    DOSEN_MAX_PRIORITY: int = 50
    ADMIN_MAX_PRIORITY: int = 100

    # --- Sumber job dari Git (GitHub) ---
    ALLOWED_GIT_HOSTS: str = "github.com"
    GIT_CLONE_TIMEOUT_SECONDS: int = 180

    # --- Admin pertama ---
    # WAJIB di-set via .env saat instalasi BARU (tidak ada default demi keamanan).
    FIRST_ADMIN_NAME: str = "Administrator"
    FIRST_ADMIN_EMAIL: str = "admin@unismuh.ac.id"
    FIRST_ADMIN_PASSWORD: str = ""

    # ----------------------------------------------------------------- helpers
    @property
    def cors_origins(self) -> list[str]:
        """Daftar origin CORS (dipisah koma)."""
        return [o.strip() for o in self.BACKEND_CORS_ORIGINS.split(",") if o.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")

    @property
    def is_postgres(self) -> bool:
        return self.DATABASE_URL.startswith("postgresql")

    @property
    def jobs_path(self) -> Path:
        """Direktori kerja job (absolut, relatif ke folder backend)."""
        p = Path(self.JOBS_DIR).expanduser()
        if not p.is_absolute():
            p = BACKEND_DIR / p
        return p

    @property
    def alerts_path(self) -> Path:
        """Direktori penyimpanan PDF peringatan."""
        p = Path(self.ALERTS_DIR).expanduser()
        if not p.is_absolute():
            p = BACKEND_DIR / p
        return p

    @property
    def log_dir_path(self) -> Path:
        """Direktori berkas log (absolut, relatif ke folder backend)."""
        p = Path(self.LOG_DIR).expanduser()
        if not p.is_absolute():
            p = BACKEND_DIR / p
        return p

    @property
    def is_first_admin_password_safe(self) -> bool:
        """True bila FIRST_ADMIN_PASSWORD layak dipakai (bukan default lemah)."""
        weak = {"", "admin", "admin123", "password", "password123", "changeme"}
        pwd = self.FIRST_ADMIN_PASSWORD.strip()
        return pwd.lower() not in weak and len(pwd) >= 8

    @property
    def smtp_configured(self) -> bool:
        """True bila SMTP siap mengirim email."""
        return bool(self.SMTP_HOST.strip())

    @property
    def assistant_configured(self) -> bool:
        """True bila asisten AI siap memanggil provider (kunci API terisi)."""
        return self.ASSISTANT_ENABLED and bool(self.ASSISTANT_API_KEY.strip())

    @property
    def assistant_chat_url(self) -> str:
        """Endpoint chat completions (OpenAI-compatible) dari base URL provider."""
        base = self.ASSISTANT_API_BASE.strip().rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions"

    @property
    def gpu_visible_indices(self) -> list[int] | None:
        """Indeks GPU yang boleh dipakai platform; None = semua."""
        raw = self.GPU_VISIBLE_DEVICES.strip()
        if not raw:
            return None
        out: list[int] = []
        for part in raw.split(","):
            part = part.strip()
            if part != "":
                out.append(int(part))
        return out

    @property
    def is_secret_key_safe(self) -> bool:
        weak = {"", "CHANGE_ME", "CHANGE_ME_PLEASE", "GANTI-DENGAN-STRING-ACAK-PANJANG"}
        return self.SECRET_KEY not in weak and len(self.SECRET_KEY) >= 32

    @property
    def allowed_git_hosts(self) -> set[str]:
        return {
            h.strip().lower()
            for h in self.ALLOWED_GIT_HOSTS.split(",")
            if h.strip()
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
