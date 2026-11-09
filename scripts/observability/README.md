# Observability ComputeHub (Prometheus + Grafana)

Stack monitoring mandiri untuk backend ComputeHub. Backend mengekspos metrik
format Prometheus di `/metrics`; Prometheus men-scrape-nya; Grafana menampilkan
dashboard.

```
backend :8088/metrics  ──scrape──▶  Prometheus :9090  ──query──▶  Grafana :3300
     (token Bearer)                   (localhost)                  (localhost)
```

## Komponen

| Bagian       | Jalan sebagai                         | Port (localhost) |
|--------------|---------------------------------------|------------------|
| `/metrics`   | di dalam `ComputeHub-app` (FastAPI)   | 8088             |
| Prometheus   | `computehub-prometheus.service`       | 9090             |
| Grafana      | `computehub-grafana.service`          | 3300             |

Prometheus & Grafana sengaja **bind ke 127.0.0.1** (bukan publik). Akses dari
laptop via SSH tunnel:

```bash
ssh -N -L 3300:localhost:3300 user@server-kampus   # buka http://localhost:3300
```

## Berkas konfig (di git)

- `prometheus/prometheus.yml` — target scrape + `credentials_file` token.
- `grafana/provisioning/datasources/prometheus.yml` — datasource (uid `computehub-prom`).
- `grafana/provisioning/dashboards/dashboards.yml` — provider dashboard.
- `grafana/dashboards/computehub-backend.json` — dashboard "Backend Overview".
- `../systemd/computehub-prometheus.service`, `../systemd/computehub-grafana.service`.

## Rahasia (DI LUAR git, di host `~/.computehub/observability/`)

| Berkas             | Isi                                                   |
|--------------------|-------------------------------------------------------|
| `metrics_token`    | token Bearer scrape (sama dgn `METRICS_TOKEN` di .env)|
| `grafana.env`      | `GF_SECURITY_ADMIN_USER` + `GF_SECURITY_ADMIN_PASSWORD`|
| `prometheus-data/` | TSDB Prometheus (retensi 30 hari)                     |
| `grafana-data/`    | DB & state Grafana                                    |

### Setup di host baru

```bash
mkdir -p ~/.computehub/observability/{prometheus-data,grafana-data}

# 1) Token scrape: HARUS sama dengan METRICS_TOKEN di backend/.env
printf '%s' "<METRICS_TOKEN>" > ~/.computehub/observability/metrics_token
chmod 600 ~/.computehub/observability/metrics_token

# 2) Kredensial admin Grafana
cat > ~/.computehub/observability/grafana.env <<EOF
GF_SECURITY_ADMIN_USER=admin
GF_SECURITY_ADMIN_PASSWORD=<password-kuat>
EOF
chmod 600 ~/.computehub/observability/grafana.env

# 3) Pasang unit
cp scripts/systemd/computehub-prometheus.service scripts/systemd/computehub-grafana.service \
   ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now computehub-prometheus.service computehub-grafana.service
```

## Verifikasi

```bash
# /metrics (butuh token)
curl -s -H "Authorization: Bearer <METRICS_TOKEN>" http://localhost:8088/metrics | head

# target Prometheus harus "up"
curl -s http://localhost:9090/api/v1/targets | jq '.data.activeTargets[].health'

# kesehatan Grafana
curl -s http://localhost:3300/api/health
```

## Metrik aplikasi

| Metrik                                        | Arti                                   |
|-----------------------------------------------|----------------------------------------|
| `computehub_http_requests_total`              | counter request per method/path/status |
| `computehub_http_request_duration_seconds`    | histogram latensi per method/path      |
| `computehub_http_requests_in_progress`        | gauge request yang sedang diproses     |
| `computehub_app_info{version=...}`            | info versi app                         |
| `process_*`, `python_*`                        | CPU/RAM/FD/GC proses (standar)         |

Label `path` dinormalisasi ke template route (mis. `/api/v1/jobs/{id}`) agar
kardinalitas rendah. Endpoint `/metrics`, `/health`, `/assets/*` tidak dihitung.

## Konfigurasi backend

Di `backend/.env`:

```
METRICS_ENABLED=true          # set false untuk menonaktifkan /metrics
METRICS_TOKEN=<token-rahasia> # kosongkan untuk tanpa gerbang token (tidak disarankan)
PROMETHEUS_URL=http://localhost:9090   # dipakai panel Monitoring (query server-side)
GRAFANA_PUBLIC_URL=                     # isi bila Grafana diekspos via proxy ber-auth
```

## Panel Monitoring in-app (khusus super-admin)

Selain Grafana, dashboard ComputeHub menampilkan metrik ini langsung di halaman
**Monitor** (`/monitor`): di bawah grafik CPU/RAM/GPU muncul bagian **Observability
backend** yang **hanya tampil untuk administrator utama** (`is_superadmin`).
Panel ini memanggil endpoint super-admin:

- `GET /api/v1/admin/ops/monitoring/summary` — nilai terkini (req/s, error %,
  latensi p50/p95/p99, CPU, RAM, uptime) + status target scrape.
- `GET /api/v1/admin/ops/monitoring/series` — deret waktu untuk grafik mini.

Backend yang menjalankan query ke Prometheus (`PROMETHEUS_URL`), sehingga
Prometheus/Grafana **tidak perlu diekspos ke browser**. Bila `GRAFANA_PUBLIC_URL`
diisi, panel menampilkan tombol "Buka Grafana".

