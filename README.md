# PeatSignal — Backend

Backend API untuk aplikasi PeatSignal, menggunakan Python, FastAPI, dan PostgreSQL/PostGIS.

Panduan ini menjelaskan cara memasang dan menjalankan backend di komputer sendiri. Semua perintah dijalankan dari folder backend. Contoh perintah menggunakan terminal Linux/macOS atau WSL di Windows.

## 1. Persiapan

Pastikan sudah memasang:

- Python versi **3.12 atau lebih baru**, beserta modul `venv`.
- Docker dengan Docker Compose. Pastikan Docker sudah berjalan.

Cek melalui terminal:

```bash
python3 --version
docker --version
docker compose version
```

## 2. Buka folder backend

Unduh atau clone repository backend, lalu buka terminal di folder yang berisi `pyproject.toml` dan `docker-compose.yml`.

Jika terminal masih berada di folder induk proyek, masuk ke folder backend:

```bash
cd peat-signal-backend
```

## 3. Buat database lokal dengan Docker

Database dibuat **di komputer sendiri melalui Docker**. Tidak perlu membuat database lewat aplikasi lain. Ada dua tahap: Docker membuat database pada langkah ini, lalu migration membuat tabel pada langkah 5.

Jika belum ada file `.env`, salin `.env.example` menjadi `.env`:

```bash
cp .env.example .env
```

Jika `.env` sudah ada, gunakan file tersebut tanpa menimpanya. Untuk database Docker lokal, salin nilai `DATABASE_URL` dari `.env.example` ke `.env`. Biarkan alamat `127.0.0.1` dan port `5433` sesuai contoh. Pastikan juga konfigurasi berikut tersedia:

```dotenv
APP_ENV=development
CORS_ALLOWED_ORIGINS=http://localhost:3000
```

Buat dan jalankan database dengan perintah berikut:

```bash
docker compose up -d postgres
```

Saat pertama kali dijalankan, Docker otomatis menyiapkan PostgreSQL/PostGIS, membuat database dan pengguna sesuai `docker-compose.yml`, serta menyimpan datanya pada volume Docker. **Tidak perlu membuat database secara manual atau menjalankan `CREATE DATABASE`.** Pada penggunaan berikutnya, perintah yang sama menjalankan database yang sudah ada.

Pengaturan database berada di file [docker-compose.yml](docker-compose.yml):

| Pengaturan | Kegunaan |
| --- | --- |
| `POSTGRES_DB` | Nama database yang dibuat otomatis |
| `POSTGRES_USER` | Pengguna untuk mengakses database |
| `POSTGRES_PASSWORD` | Kata sandi database lokal |

Untuk setup paling mudah, gunakan nilai bawaan dan `DATABASE_URL` dari `.env.example` agar keduanya cocok. Pengaturan tersebut berlaku saat volume database pertama kali dibuat.

Cek status database:

```bash
docker compose ps
```

Tunggu sampai database berstatus **healthy** sebelum melanjutkan. Setelah itu, database sudah dibuat dan siap diisi tabel. Database memakai alamat `127.0.0.1` dengan port **5433** di komputer, sehingga bisa berjalan bersama PostgreSQL lain pada port 5432.

Lanjutkan instalasi dependency pada langkah 4, kemudian jalankan migration pada langkah 5. Backend baru dijalankan setelah kedua langkah tersebut selesai.

API key NASA FIRMS belum diperlukan untuk menjalankan API lokal. Jangan commit file `.env` atau kunci rahasia ke repository.

## 4. Instalasi dependency

Buat lingkungan Python terpisah untuk proyek, lalu pasang dependency:

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

Tunggu sampai proses selesai. Instalasi membutuhkan koneksi internet. Perintah berikutnya memakai Python dari `.venv`, sehingga tidak perlu mengaktifkannya secara manual.

## 5. Siapkan tabel database

Setelah database dibuat pada langkah 3, jalankan migration untuk membuat atau memperbarui tabel di dalamnya:

```bash
.venv/bin/alembic upgrade head
```

Migration juga menyiapkan akun demo. Data pemantauan perlu diimpor secara terpisah jika ingin menampilkan data historis.

## 6. Jalankan backend

```bash
.venv/bin/uvicorn app.main:app --reload
```

Biarkan terminal tetap terbuka selama backend digunakan. Buka alamat berikut untuk memeriksa hasilnya:

| Alamat | Kegunaan |
| --- | --- |
| http://localhost:8000/health | Memeriksa apakah API berjalan |
| http://localhost:8000/docs | Dokumentasi interaktif untuk mencoba endpoint |
| http://localhost:8000/openapi.json | Kontrak API dalam format JSON |

Untuk menghentikan server, tekan **Ctrl+C** di terminal.

Saat ingin menjalankan kembali, cukup jalankan dari folder backend:

```bash
docker compose up -d postgres
.venv/bin/uvicorn app.main:app --reload
```

Tidak perlu mengulang instalasi. Jalankan `alembic upgrade head` kembali jika ada migration baru. Untuk menghentikan database setelah selesai, gunakan `docker compose stop postgres`.

## 7. Isi data historis (opsional)

Jika memakai database baru dan ingin mencoba data tinggi muka air tanah, impor dataset yang disertakan:

```bash
.venv/bin/python -m app.cli import-gwt dataset/mmc1.xlsx --apply
```

Untuk menyiapkan hasil eksperimen prediksi historis:

```bash
.venv/bin/python -m app.cli train-gwt dataset/mmc1.xlsx
```

Hasilnya adalah eksperimen data historis, bukan prediksi kondisi saat ini. Data titik panas historis dan sinkronisasi NASA memerlukan langkah tambahan; lihat dokumentasi lanjutan di bawah.

## 8. Hubungkan frontend (opsional)

Pada folder frontend, buat atau sesuaikan `.env.local`:

```dotenv
NEXT_PUBLIC_DATA_SOURCE=rest
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api/v1
NEXT_PUBLIC_DEMO_COORDINATOR_TOKEN=demo-coordinator-token
NEXT_PUBLIC_DEMO_FIELD_OFFICER_TOKEN=demo-field-officer-token
```

Token di atas tersedia untuk development/test. Jika token di `.env` backend sudah diubah, gunakan nilai yang sama di frontend.

Jalankan ulang frontend setelah mengubah konfigurasi. Pastikan backend tetap berjalan. Jika frontend memakai alamat atau port lain, sesuaikan `CORS_ALLOWED_ORIGINS` di `.env` backend, lalu jalankan ulang backend.

## Kendala yang sering muncul

- **Perintah `python3` tidak ditemukan atau versinya terlalu lama:** pasang Python 3.12+, lalu buka ulang terminal.
- **Gagal membuat `.venv`:** pastikan modul `venv` untuk versi Python yang digunakan sudah terpasang.
- **Docker tidak dapat dihubungi:** jalankan Docker Desktop atau layanan Docker terlebih dahulu.
- **Koneksi database ditolak:** cek `docker compose ps`, tunggu status healthy, dan pastikan `DATABASE_URL` memakai port 5433.
- **Tabel belum ditemukan:** jalankan `.venv/bin/alembic upgrade head` sebelum memulai API.
- **Port 8000 sedang digunakan:** jalankan `.venv/bin/uvicorn app.main:app --reload --port 8001`. Sesuaikan juga alamat API di frontend.
- **Data pemantauan kosong:** database baru belum memiliki observasi; lakukan import data historis atau konfigurasi sinkronisasi sesuai kebutuhan.

## Pemeriksaan kode (opsional)

```bash
.venv/bin/ruff check .
.venv/bin/pytest
```

Tes integrasi database memerlukan `TEST_DATABASE_URL` menuju database khusus dengan nama berakhiran `_test`. Tanpa konfigurasi tersebut, tes integrasi terkait dilewati. Lihat [panduan pengujian](docs/backend-qa.md) untuk detailnya.

## Dokumentasi lanjutan

- [Setup database eksternal, import titik panas, dan hosting](SPLIT_REPOSITORY.md)
- [Kontrak API pemantauan](docs/read-api-handoff.md)
- [Sinkronisasi NASA FIRMS](docs/firms-handoff.md)
- [Prioritas pemeriksaan](docs/priorities-handoff.md)
- [Alur tugas dan laporan lapangan](docs/tasks-handoff.md)
- [Eksperimen prediksi historis](docs/ml-handoff.md)
