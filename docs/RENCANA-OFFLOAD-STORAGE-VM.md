# Rencana Pekerjaan Tertunda — Storage & Disk hpc-ai

> Status: **SELESAI — SEMUA DATA (`/persist` + `devbox` + `images` + `shared_models`) AKTIF DI VM via NFS.**
> Copy lokal lama sudah dihapus; disk hpc-ai lega ~191 GB (95% → ~79%).
> Dokumen ini menyimpan konteks, temuan, dan langkah eksekusi.
> Dibuat: 2026-11-08. Diperbarui: 2026-11-09 — seluruh offload selesai + regresi backup NFS
> ditemukan & diperbaiki (lihat bagian "Keputusan terakhir pengguna").

## Latar belakang

**Yang dipindah HANYA data ComputeHub milik pemilik aplikasi** (muhammadrizalharis), yaitu seluruh
penyimpanan **`/persist`** (`~/.computehub/users/*`). **BUKAN** storage sistem hpc-ai, **BUKAN**
data OS-user lain (mis. `/home/muhyiddin`). Jadi ini memindah **data aplikasi sendiri** ke ruang
yang dikuasai penuh (VM pribadi). Melegakan filesystem hpc-ai hanyalah **efek samping**, bukan
tujuan utama.

Konteks: filesystem guest **hpc-ai** (disk 2 TB) sudah **~92% penuh** (sisa ~160 GB) dan **tidak
bisa diperbesar oleh pemilik aplikasi** — perubahan alokasi disk hpc-ai adalah kuasa kepala IT.
Target: pindahkan data ComputeHub milik sendiri ke VM pribadi **tanpa mengganggu aplikasi yang
sedang berjalan normal**.

### Catatan penting: file FISIK di VM tetap TAMPIL di server (transparan)

Memindah data ke VM **tidak** berarti data "hilang" dari server. Dengan **NFS (network mount)**,
byte-nya tersimpan fisik di VM tetapi folder-nya **muncul & berfungsi seperti lokal** di hpc-ai:

```
Fisik tersimpan di : VM rizal-desktop  (mis. /srv/computehub-persist)
Tampil di server   : hpc-ai           (~/.computehub/users)  ← lewat mount NFS
```

Bagi server, aplikasi, dan pengguna, folder itu terlihat sama seperti sebelumnya (buka, baca,
tulis, tampil di UI) — analogi seperti Google Drive yang di-mount. Konsekuensi: selama mount
hidup → transparan; bila mount/VM mati → folder tampak kosong/error sampai tersambung lagi (karena
satu host, kedua VM mati bersama, jadi tak ada titik gagal baru). **Pemindahan bisa selektif** —
tidak harus semua `/persist`; bisa hanya folder/user tertentu yang di-mount dari VM, sisanya tetap
lokal.

### Fakta infrastruktur (terverifikasi dari dalam guest + ESXi Host Client)

- hpc-ai **adalah VM VMware** (`systemd-detect-virt=vmware`, `VMware20,1`), bukan server fisik.
  - Disk `sda` 2 TB = **virtual disk** (vmdk). GPU: **2× NVIDIA L40S** (PCI passthrough `AD102GL`).
  - RAM 256 GB, 64 vCPU. Host name `hpc-ai`, IP LAN `10.33.33.11`, NIC `ens33` = **10 Gbps**.
  - Juga terhubung **Tailscale** (`hpc-ai.tailafe0.ts.net`, `100.122.48.123`).
- VM pribadi **`rizal-desktop`** (dikelola penuh oleh muhammadrizalharis):
  - Ubuntu 26.04, 64 vCPU, 128 GB RAM, disk **1 TB** (terpakai ~141 GB).
  - IP LAN `10.33.33.105`. Akses: `ssh muhammad-rizal-haris@10.33.33.105`.
- **Kedua VM berada di satu host ESXi yang sama** (`localhost.localdomain`, 35 VM).
  - **Hanya 1 datastore**: `datastore1` (SSD, VMFS6) — **Kapasitas 13.85 TB, Free 3.75 TB**.
  - Konsekuensi: memindah data antar kedua VM **TIDAK** mengurangi pemakaian SSD fisik ESXi;
    hanya menggeser beban ke vmdk yang dikuasai sendiri. Karena datastore masih longgar
    (3.75 TB free), ini **aman** dan **menyelesaikan masalah nyata** (filesystem hpc-ai penuh).
  - Karena satu host (mati bersama), mount storage VM ke hpc-ai **tidak menambah titik gagal baru**.

### Apa yang menghabiskan disk hpc-ai (ringkas)

- `/home/muhyiddin` ≈ **330 GB** (home OS kepala IT; 214 GB di antaranya model ComfyUI). **Bukan milik kita, jangan disentuh.**
- `/var/lib/docker` ≈ **245 GB**.
- Model Ollama `/usr/share/ollama/.ollama` ≈ **108 GB**.
- **Storage ComputeHub `~/.computehub/users/*` ≈ ~125 GB** ← ini yang akan di-offload (milik app kita).
- `DATA_ICAL` ≈ 63 GB (termasuk repo + worktree).

Catatan: panel "disk per user" di ComputeHub mengukur **home OS-user** (`du /home`), bukan `/persist`.
Semua data mahasiswa (login via SSO, bukan user OS) tersimpan di `~/.computehub/users/<id>` di
dalam home `muhammadrizalharis`, sehingga terhitung pada baris OS-user `muhammadrizalharis`.

---

## TUGAS 1 — Offload penyimpanan `/persist` ComputeHub ke VM `rizal-desktop` (via NFS)

**Tujuan:** memindahkan **data ComputeHub milik sendiri** `~/.computehub/users/*` (`/persist`,
~125 GB) dari disk hpc-ai ke VM pribadi, sehingga filesystem hpc-ai mendapat ~125 GB napas.
Compute (GPU) tetap di hpc-ai; data diakses balik lewat NFS sehingga **tetap tampil transparan**
di server. **Bisa selektif** (hanya folder/user tertentu) bila tak ingin memindah seluruh `/persist`.

**Prasyarat teknis penting:**
- `DOCKER_USER_DATA_ROOT` default = `~/.computehub/users` (lihat `backend/app/core/config.py`).
  Folder ini di-**bind-mount** ke container devbox/job/kernel saat dipakai.
- Jika jadi NFS: butuh `no_root_squash` + pemetaan uid agar container (yang menulis sebagai
  berbagai uid) tetap bisa baca-tulis. Uji permission sebelum peralihan.

**Langkah (urutan aman — copy dulu, switch belakangan):**

1. **Di `rizal-desktop`:**
   - `sudo apt install nfs-kernel-server`
   - Buat folder ekspor, mis. `/srv/computehub-persist`, owner sesuaikan uid app hpc-ai.
   - `/etc/exports`: ekspor hanya ke IP hpc-ai (`10.33.33.11`) dengan `rw,sync,no_subtree_check,no_root_squash`.
   - `sudo exportfs -ra` + pastikan firewall VM mengizinkan NFS dari `10.33.33.11`.
2. **Di hpc-ai (tahap AMAN, belum mengubah app):**
   - `sudo apt install nfs-common`
   - Mount ke path sementara: `sudo mount -t nfs 10.33.33.105:/srv/computehub-persist /mnt/ch-persist-nfs`
   - **Salin** data: `rsync -aHAX --info=progress2 ~/.computehub/users/ /mnt/ch-persist-nfs/`
   - **Verifikasi** integritas (jumlah file + checksum sampel). Data lama **tidak** dihapus.
3. **Peralihan (saat jam sepi):**
   - Hentikan sementara devbox/job aktif (quiesce) agar tak ada tulis saat switch.
   - Arahkan `DOCKER_USER_DATA_ROOT` ke mount NFS **atau** bind-mount NFS pada path lama
     `~/.computehub/users`. Tambahkan entri `/etc/fstab` (opsi `_netdev,nofail`) agar auto-mount saat boot.
   - Restart `computehub.service`, verifikasi: upload file, buka notebook, mulai devbox → semua jalan.
4. **Rollback siap:** simpan salinan lama di hpc-ai beberapa hari sebelum dihapus. Jika NFS
   bermasalah, kembalikan `DOCKER_USER_DATA_ROOT` ke path lokal + restart.

**Risiko & catatan:**
- Performa: antar-VM satu host (vSwitch internal) + SSD → cepat, tapi NFS tetap menambah latensi
  vs disk lokal. Untuk data mahasiswa yang umumnya tidak "panas ekstrem", dapat diterima.
- Datastore tunggal: **tidak** mengurangi pemakaian SSD fisik, hanya memindah ke vmdk VM pribadi
  (yang masih sangat longgar). Pastikan datastore tetap punya ruang sebelum migrasi besar.

### Folder lain yang IKUT dipindah (semua di home kita sendiri)

Prinsip wewenang: **yang kita pindahkan HANYA isi home kita** (`/home/muhammadrizalharis`),
bukan milik user/OS lain. Selain `/persist` (`~/.computehub/users`), folder berikut — semuanya di
dalam `~/.computehub` — ikut di-offload ke VM dengan pola yang sama (salin dulu, switch belakangan):

| Folder | Ukuran | Jenis |
|---|---|---|
| `~/.computehub/devbox` (homes) | ~46 GB | Home kerja devbox user |
| `~/.computehub/images` | ~16 GB | Snapshot image pemulihan (data dingin) |
| `~/.computehub/shared_models` | ~9.3 GB | Overlay model bersama (read-mostly) |

Perkiraan tambahan lega hpc-ai: **~71 GB** (di luar `/persist` ~122 GB). Masing-masing folder
di-mount balik via NFS agar tetap tampil transparan di server. Config terkait (mis. path devbox/
images di `backend/app/core/config.py`) diarahkan ke mount NFS saat peralihan, dengan rollback siap.

**TIDAK ikut dipindah — Ollama models (`/usr/share/ollama/.ollama`, ~108 GB):** meski besar, ini
**BUKAN wewenang pemilik aplikasi**. Pengelolaan model Ollama ada di tangan **muhyiddin**. Jadi
dikecualikan dari rencana ini. Wewenang kita di hpc-ai terbatas pada **home kita sendiri**.

---

## TUGAS 2 — Bersihkan snapshot hpc-ai (~1.6 TB) — KUASA KEPALA IT

**Temuan:** VM `hpc-ubuntu22` (hpc-ai) memakai **3.86 TB** di datastore padahal disk guest cuma
**2 TB** (Provisioned 2 TB, Uncommitted 148 GB). Selisih **~1.6 TB** kemungkinan besar **snapshot
lama** yang menggantung. Menghapusnya mengembalikan ~1.6 TB ke datastore — **lebih besar dari semua
pembersihan lain** yang dibahas.

**Verifikasi dulu (sebelum menyimpulkan):**
- ESXi → VM `hpc-ubuntu22` → **Actions → Snapshots → Manage snapshots** (lihat daftar snapshot), atau
- **Storage → Datastore browser → datastore1 → folder `hpc-ubuntu22`**: cari file `-000001.vmdk` /
  `-delta.vmdk` dan lihat ukurannya.

**Sampaikan ke kepala IT (nada minta tolong):** jika snapshot sudah tidak diperlukan, mohon dihapus;
itu mengembalikan ~1.6 TB (datastore sekarang free 3.75 TB).

**Peringatan (sampaikan juga):**
- Menghapus snapshot besar memicu **consolidate** (puluhan menit–jam, I/O berat) → VM bisa tersendat.
  Lakukan **saat jam sepi**; idealnya ada **backup** dulu.
- **Jangan hapus** bila snapshot sengaja dibuat sebagai titik-pulih yang masih relevan.
- Ini **kuasa & tanggung jawab kepala IT** (hpc-ai), bukan pemilik aplikasi.

---

## Keputusan terakhir pengguna (2026-11-08, diperbarui malam)

- **Snapshot hpc-ai (Tugas 2): TIDAK diurus** — di luar wewenang kita. Fokus hanya Tugas 1.
- **Offload (Tugas 1): SELESAI SEPENUHNYA.** Lingkup = **hanya home kita**. Semua data sudah
  aktif di VM via NFS dan copy lokal lama sudah dihapus:

| Data | Ukuran | Status | Copy lokal lama |
|---|---|---|---|
| `/persist` (`~/.computehub/users`) | ~122 GB | ✅ switched + fstab | **dihapus** |
| `~/.computehub/devbox` (homes) | ~46 GB | ✅ switched + fstab | **dihapus** |
| `~/.computehub/images` | ~16 GB | ✅ switched + fstab | **dihapus** |
| `~/.computehub/shared_models` | ~9.3 GB | ✅ switched + fstab | **dihapus** |

- **Hasil disk hpc-ai:** dari ~95% penuh → **~79% (sisa ~423 GB live)**, lega ~191 GB. **Ollama
  dikecualikan** (wewenang muhyiddin).
- Progres `/persist` (SELESAI):
  1. Akses VM `rizal-desktop` disiapkan (SSH key tanpa password + passwordless sudo).
  2. NFS server VM aktif (`/srv/computehub-persist`, ekspor khusus ke `10.33.33.11`), throughput ~249 MB/s.
  3. `rsync -aHAX --numeric-ids` 122 GB / 1.211.569 entri **selesai & terverifikasi** (jumlah file
     & ukuran cocok persis, 0 error; delta re-sync = 0 perubahan).
  4. **Peralihan selesai:** NFS di-mount **rw** langsung di `~/.computehub/users` (data lokal lama
     tetap tersimpan tersembunyi di bawah mount = rollback siap), `computehub.service` di-restart,
     `health=ok`, tulis-baca dari container OK (uid 1015). Entri `/etc/fstab` ditambah
     (`_netdev,nofail`) agar bertahan setelah reboot.
  5. Copy lokal lama **sudah dihapus** (lihat di bawah).
- Progres `devbox` + `images` + `shared_models` (SELESAI):
  1. Di VM: dibuat `/srv/computehub-{devbox,images,shared-models}` (chown uid 1015), ditambah 3
     ekspor NFS ke `10.33.33.11` (`no_root_squash`), `exportfs -ra`.
  2. `rsync` ketiganya **selesai & terverifikasi** (images 11 entri, shared_models 201 entri,
     devbox 483.926 entri — jumlah cocok persis kedua sisi, 0 error; kepemilikan root model
     dipertahankan).
  3. **Peralihan selesai:** NFS di-mount **rw** langsung di `~/.computehub/{devbox,images,shared_models}`,
     app di-restart sekali (semua mount terlihat rw di dalam container, baca-tulis OK, `health=ok`),
     3 entri `/etc/fstab` ditambah.
- **Penghapusan copy lokal lama (SELESAI):** setelah testing menyeluruh **T1–T12 lulus** (mount rw
  uid 1015, hardlink/symlink, root-file readable, job-sim container baca-tulis NFS, service-layer,
  e2e tulis app→VM cocok, perf baca besar 565 MB/s) + **checksum sampel acak 40/40 cocok** (persist
  & devbox) + **backup Drive terverifikasi** (restic snapshot `a090d804`, 1.36 juta file/118.8 GiB),
  copy lokal lama dihapus via bind-mount non-rekursif (`mount --bind ~/.computehub /mnt/underlying`
  → hapus isi folder lokal yang tersembunyi di bawah mount NFS, tanpa menyentuh mount hidup).
- **Rollback (bila perlu):** karena copy lokal sudah dihapus, rollback kini mengandalkan salinan di
  VM + backup Drive (`/persist`). `systemctl --user stop computehub && sudo umount
  ~/.computehub/<folder> && ...` hanya mengosongkan folder (data ada di VM), jadi mount NFS harus
  tetap hidup.
- **Database PostgreSQL (~0.6 GB) TETAP di hpc-ai** — tak boleh di NFS (risiko korupsi) + latensi.
- Mode pemeliharaan dinyalakan selama pengerjaan agar tak ada job baru menulis storage.

### Regresi backup pasca-NFS (DITEMUKAN & DIPERBAIKI)

**Masalah:** `scripts/backup.sh` men-*stage* `~/.computehub/users` ke `$TMP` (`mktemp -d` di `/tmp`
lokal) memakai `cp -al` (hardlink) dengan asumsi staging **satu filesystem** dengan data. Setelah
`/persist` pindah ke **NFS**, hardlink lintas-filesystem gagal → fallback lama `cp -a` menyalin
**~127 GB ke /tmp lokal setiap hari** (restic membaca `$TMP`). Ini membuat disk anjlok drastis tiap
backup harian jalan.

**Perbaikan (diterapkan):**
- Deteksi lintas-filesystem lebih dulu (`stat -c %d` bandingkan device `$DATA` vs `$TMP`); hanya
  pakai `cp -al` bila benar-benar satu filesystem (hardlink murah).
- Bila lintas-fs (kasus NFS), staging memakai **bind-mount read-only** (`mount --bind -o ro "$DATA"
  "$TMP/users"`) — **zero-copy**: restic & tar membaca langsung dari NFS tanpa menggandakan ke lokal.
- `cp -a` (salin penuh) hanya sebagai **upaya terakhir** bila hardlink DAN bind-mount sama-sama gagal.
- Pembersihan aman (`bak_cleanup`): umount bind-mount lebih dulu; bila masih mountpoint, `rm -rf`
  **dilewati** agar tidak pernah menembus ke data NFS hidup.
- **Diuji:** backup manual → staging menjadi bind-mount NFS ro (bukan salinan 127 GB), /tmp tidak
  membengkak, restic upload incremental ke `gdrive:ComputeHub-Restic` normal.
- Timer `computehub-backup.timer` sempat di-stop selama investigasi; diaktifkan ulang setelah fix
  tervalidasi.

**Catatan cakupan backup:** `backup.sh` hanya mem-backup `users/` (= `/persist`) + DB + config +
agent + joblogs. **Tidak** mem-backup `devbox`/`images`/`shared_models` (regenerable: devbox =
re-login/install, images = docker save/rebuild, models = skrip unduh); keamanannya mengandalkan
salinan di VM.

## Referensi terkait

- Issue #1 — Rebase backend ke Python 3.11 (CVE tertunda, accepted-risk).
- Pembersihan disk aman yang **sudah** dilakukan sesi ini: image dangling yatim (283 MB) + apt cache (5 MB).
  Journald (4.1 GB, semua < 7 hari) sengaja **tidak** dipangkas demi menjaga riwayat diagnosis.
