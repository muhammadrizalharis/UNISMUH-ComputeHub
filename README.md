<div align="center">

<img src="frontend/public/logos/teknik-merah.png" alt="Fakultas Teknik UNISMUH" width="92" />

# 🖥️ UNISMUH ComputeHub

### Platform Komputasi GPU ala Google Colab untuk Server Kampus

Submit **kode Python, notebook, project ZIP, atau GitHub repo** —
semuanya berjalan **langsung di GPU** dengan isolasi penuh per pengguna.

<br/>

![React](https://img.shields.io/badge/React-20232A?style=for-the-badge&logo=react&logoColor=61DAFB)
![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?style=for-the-badge&logo=typescript&logoColor=white)
![Vite](https://img.shields.io/badge/Vite-646CFF?style=for-the-badge&logo=vite&logoColor=white)
![Tailwind CSS](https://img.shields.io/badge/Tailwind_CSS-06B6D4?style=for-the-badge&logo=tailwindcss&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?style=for-the-badge&logo=postgresql&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white)
![NVIDIA CUDA](https://img.shields.io/badge/NVIDIA_CUDA-76B900?style=for-the-badge&logo=nvidia&logoColor=white)

</div>

---

## ✨ Tentang

**UNISMUH ComputeHub** adalah platform orkestrasi *job* GPU untuk server kampus
bersama — dirancang senyaman **Google Colab**, namun aman untuk banyak pengguna.
Mahasiswa & dosen dapat menjalankan kode, melatih model, dan bereksperimen di GPU
**tanpa akses admin**, lengkap dengan pemantauan *real-time*, kuota per pengguna,
laporan penggunaan, dan isolasi penuh berbasis kontainer.

> 🎓 Digunakan internal di **Fakultas Teknik — Informatika, UNISMUH Makassar**.

---

## 🚀 Fitur Utama

### 📓 Notebook Interaktif — ala Colab / VS Code
Jalankan Python dari **4 sumber**: tempel kode, unggah `.ipynb`, upload project
`.zip`, atau clone **GitHub repo** — semuanya di **kernel hidup di GPU** (variabel
tetap antar-sel, output langsung). Dilengkapi **file explorer**, **unduh project
(.zip)**, **ekspor `.ipynb`**, dan **commit & push balik ke GitHub**.

### 🤖 Asisten AI Koding
Asisten cerdas berbasis LLM lokal kampus — membantu **menulis, menjelaskan, dan
memperbaiki kode** langsung di dalam notebook, bahkan memahami gambar.

### ⚙️ Eksekusi & Penjadwalan GPU-aware
Job batch dengan **antrian + ETA**, timeout adaptif (belajar dari riwayat),
auto `pip install`, dan **enforcement GPU** (pekerjaan wajib berjalan di GPU).

### 🔐 Isolasi & Keamanan
Setiap eksekusi berjalan di **kontainer efemeral** (satu pengguna, satu ruang),
non-root, jaringan terisolasi, dengan **workspace persisten** per pengguna.
Login via **SSO Unismuh** (OpenID Connect) maupun akun lokal.

### 📊 Monitoring & Laporan
Pemantauan **CPU · RAM · GPU** secara *real-time*, laporan penggunaan ala HPC
(siapa memakai apa + analisis workload otomatis), serta **peringatan batas**
yang dikirim via **email + PDF**.

### 🎛️ Kebijakan Fleksibel
Kuota GPU harian, batas job paralel, plafon VRAM/RAM, dan kuota penyimpanan —
diatur admin **per-peran & per-pengguna**, tanpa perlu restart.

---

## 🧩 Teknologi

| Lapisan | Teknologi |
|---|---|
| **Frontend** | React · TypeScript · Vite · Tailwind CSS |
| **Backend** | FastAPI · Python · SQLAlchemy (async) |
| **Basis Data** | PostgreSQL |
| **Komputasi** | Docker · NVIDIA CUDA · PyTorch |
| **Autentikasi** | SSO Unismuh (OIDC / Keycloak) + lokal (JWT) |

---

## 🏛️ Akses

Platform **internal kampus**. Akun dibuat oleh administrator; registrasi publik
dinonaktifkan. Login mendukung **SSO Unismuh** (akun kampus) dan akun lokal.

> 📁 Dokumentasi teknis (arsitektur, konfigurasi, *environment*, dan *deployment*)
> bersifat internal dan tidak disertakan di repositori publik ini.

---

<div align="center">

### 👨‍💻 Pembuat

**Muhammad Rizal Haris**
<br/>
*Perancang & Pengembang Aplikasi*

<br/>

🏛️ Fakultas Teknik · 💻 Informatika · **UNISMUH Makassar**

<sub>© 2026 UNISMUH ComputeHub — dibuat dengan ❤️ untuk komputasi kampus.</sub>

</div>

