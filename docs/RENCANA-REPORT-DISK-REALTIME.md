# Rencana: Refresh laporan "Pemakaian Disk per User" benar-benar menghitung ulang (tanpa angka menghilang)

Status: **rencana / belum diimplementasi**
Dibuat atas permintaan admin (Muhammad Rizal Haris).

## Masalah yang dilaporkan

Di halaman **Laporan Penggunaan Resource → Pemakaian Disk per User**:

1. **Perhitungan tidak real-time.** Saat tombol **Refresh** ditekan, angka pemakaian
   disk per user tidak ikut dihitung ulang — masih memakai hasil cache lama
   (terlihat dari catatan "Dihitung 3 jam lalu").
2. **Saat menghitung ulang, angka malah hilang** dan diganti teks/spinner
   "Sedang menghitung…". Yang diinginkan: angka lama **tetap tampil**, lalu begitu
   selesai **hanya angkanya yang berubah** (pembaruan di tempat), bukan menghilang.

## Akar masalah (hasil telusur kode)

### 1. Tombol Refresh tidak menyentuh query disk
`frontend/src/pages/Report.tsx:262`

```tsx
<RefreshButton onRefresh={() => reportQ.refetch()} />
```

`reportQ` = query "Informasi Sistem" (CPU/RAM/GPU). Query disk adalah `diskQ`
(`Report.tsx:155`, `queryKey: ['admin-report-disk']`). Tombol Refresh **tidak**
memanggil `diskQ.refetch()`, jadi disk tidak pernah ikut diperbarui saat refresh.

### 2. Endpoint disk tidak punya opsi "paksa hitung ulang"
`backend/app/api/routers/admin.py:561-566` → `report_svc.disk_usage()`
(`backend/app/services/report.py:168-196`).

`disk_usage()` hanya menghitung ulang bila cache sudah **basi** (`_DISK_TTL = 1800`
detik = 30 menit, `report.py:76`). Selama masih < 30 menit, refetch mengembalikan
hasil cache yang sama. Tidak ada parameter untuk memaksa recompute.

Catatan desain yang sudah benar: recompute dilakukan **di latar** dan endpoint
mengembalikan data lama dulu (`report.py:173-187`) supaya request tidak nge-hang.
Perilaku "kembalikan data lama + hitung di latar" ini **dipertahankan** — hanya
perlu ditambah pemicu paksa.

### 3. Frontend menyembunyikan tabel saat menghitung pertama kali
`frontend/src/pages/Report.tsx:464, 492`

```tsx
const computing = data.computing && data.users.length === 0
...
{computing ? (<Spinner/> "Sedang menghitung…") : (<tabel/>) }
```

Saat cache masih kosong (pertama kali), tabel diganti spinner. Saat sudah ada data,
tabel tetap tampil (sudah benar) — tapi karena masalah #1 & #2 di atas, refresh tak
pernah memicu recompute sehingga angka tak kunjung berubah.

## Perubahan yang diusulkan

### Backend
- Tambah query param `force` pada `GET /admin/report/disk`
  (`admin.py:561`), diteruskan ke `report_svc.disk_usage(force=True)`.
- Di `disk_usage()` (`report.py:168`): bila `force=True`, jadwalkan recompute di
  latar **walau cache belum basi** (abaikan `_DISK_TTL`), tetapi **tetap kembalikan
  data lama + flag `computing: true`** (jangan blokir, jangan kosongkan). Hindari
  menjadwalkan dobel bila `computing` sudah `True`.

### Frontend (`Report.tsx`)
- Buat `RefreshButton` ikut memicu disk: `onRefresh` memanggil `reportQ.refetch()`
  **dan** `diskQ.refetch()` (dengan `force`). Tambahkan util `api.getDiskReport`
  menerima opsi `force` → `GET /admin/report/disk?force=1`.
- **Jangan pernah menyembunyikan tabel bila sudah ada data.** Ubah agar spinner
  "Sedang menghitung…" hanya muncul saat **benar-benar belum ada data sama sekali**
  (`data.users.length === 0`). Saat refresh dengan data lama ada, tetap render tabel
  lama dan cukup tampilkan indikator halus (mis. ikon berputar kecil / teks
  "· memperbarui…" di header), sehingga **hanya angkanya yang berubah** begitu
  recompute selesai.
- Saat `computing` aktif tapi data ada, aktifkan polling singkat (mis.
  `refetchInterval` dipercepat sementara) agar angka otomatis ter-update begitu
  recompute latar selesai, lalu kembali normal.

## Kriteria selesai
- Tekan **Refresh** → disk per user benar-benar dihitung ulang (bukan cache lama).
- Selama proses hitung ulang, **angka lama tetap tampil**; tidak ada tabel yang
  hilang / diganti teks "sedang dihitung".
- Setelah selesai, **hanya nilai angka** yang berubah di tempat, beserta label
  "Dihitung … lalu" yang ter-refresh.

## Catatan
- `du -bxd1 /home` memang mahal (bisa beberapa menit untuk home besar seperti
  muhyiddin 326 GB). Karena itu desain "hitung di latar + tampilkan angka lama"
  tetap dipakai; `force` hanya mem-bypass TTL, bukan memblokir request.
