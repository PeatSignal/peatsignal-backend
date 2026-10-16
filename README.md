> Repository terpisah: baca [panduan setup dan hosting](SPLIT_REPOSITORY.md).

# GambutOps Backend

Backend GambutOps: FastAPI/Pydantic, autentikasi role demo, PostgreSQL/PostGIS,
ETL GWT, importer VIIRS historis, read API monitoring, decision engine, dan workflow lapangan.

## Menjalankan lokal

Gunakan Python 3.12+ dan Docker. Dari root repository ini:

```bash
[ -f .env ] || cp .env.example .env
docker compose up -d postgres
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --reload
```

API tersedia di `http://localhost:8000`, dokumentasi interaktif di `/docs`, kontrak mesin
di `/openapi.json`, dan liveness di `/health`. Konfigurasi memakai nama environment tanpa
prefix, seperti `DATABASE_URL` dan `FIRMS_MAP_KEY`; jangan commit `.env` atau kunci FIRMS.

PostgreSQL Docker diekspos pada `127.0.0.1:5433` (port container tetap 5432), sehingga dapat
berjalan bersama PostgreSQL lokal pada port 5432. Jika `.env` sudah ada, sesuaikan port
`DATABASE_URL` ke 5433; file tersebut tidak ditimpa otomatis.

### Supabase `hackaton_joints`

Project Supabase `hackaton_joints` memakai ref `jzdoblbhliezskncojoy` di region Singapore.
Schema sampai migration BE-06 (`20261015_0004`) dan PostGIS sudah dipasang melalui plugin
Supabase. Untuk menjalankan backend melalui Supavisor session mode:

```bash
cp .env.supabase.example .env
# Ganti URL_ENCODED_DATABASE_PASSWORD di .env dengan password database dari dashboard.
.venv/bin/alembic current
.venv/bin/uvicorn app.main:app --reload
```

Template ada di [.env.supabase.example](.env.supabase.example). Password harus di-URL-encode,
disimpan hanya pada `.env`/secret deployment, dan tidak boleh memakai anon/publishable key.
Session pooler port 5432 dipilih untuk backend SQLAlchemy persisten dan jaringan IPv4. Untuk
migration/backup pada host IPv6, direct connection `db.jzdoblbhliezskncojoy.supabase.co:5432`
dapat digunakan. Backend tetap menjadi satu-satunya jalur akses aplikasi ke tabel domain.

Migration `20261015_0005` menerapkan pola FastAPI-only: RLS aktif pada seluruh tabel aplikasi,
akses tabel langsung untuk role Data API `anon`/`authenticated` dicabut, dan tidak ada policy
client-side. Jangan memakai Supabase JS/Data API untuk tabel domain; frontend memanggil FastAPI.
Objek internal extension PostGIS seperti `spatial_ref_sys` tetap dikelola oleh Supabase.

Handoff frontend yang mengikuti kontrak backend tersedia di
[read-api-handoff.md](docs/read-api-handoff.md), termasuk contoh respons database aplikasi.

## FIRMS live (BE-04)

Sync manual NASA, cache Current Monitoring, dan status global sudah tersedia.
Panduan konfigurasi key, endpoint coordinator, CLI, cooldown dan contoh respons nyata:
[firms-handoff.md](docs/firms-handoff.md).

```bash
.venv/bin/alembic upgrade head
.venv/bin/python scripts/configure_firms_key.py
.venv/bin/python -m app.cli sync-hotspots --area batanghari --product VIIRS_SNPP_NRT --apply
```

`GET /api/v1/hotspots/sync-status` membaca status sync; `GET /api/v1/hotspots?mode=CURRENT_MONITORING`
membaca cache. Keduanya tidak memanggil NASA. Cooldown berlaku sepuluh menit per area/produk.

## Autentikasi demo

Endpoint write memakai `Authorization: Bearer <token>`. Pada development/test saja tersedia
token deterministik `demo-coordinator-token` dan `demo-field-officer-token`. Untuk production,
`COORDINATOR_TOKEN` dan `FIELD_OFFICER_TOKEN` wajib diisi dengan nilai kuat
minimal 32 karakter dan berbeda; aplikasi menolak startup bila keduanya tidak valid. Kedua identitas demo memiliki
UUID stabil yang diseed oleh migration awal.

Contoh:

```bash
curl http://localhost:8000/health
curl -H 'Authorization: Bearer demo-coordinator-token' \
  http://localhost:8000/api/v1/auth/me
```

Endpoint stations, groundwater, hotspots, priorities, tasks, reports, dan users sudah membaca
atau menulis database.
Priorities juga menyimpan snapshot ber-versi secara idempotent; lihat
[kontrak BE-05](docs/priorities-handoff.md). Workflow task/report mengikuti state machine,
role, ownership, dan history pada [handoff BE-06](docs/tasks-handoff.md). Endpoint ML metrics dan
forecast historis tersedia setelah model dilatih; detailnya ada di [handoff ML](docs/ml-handoff.md).

## Workflow lapangan (BE-06)

Coordinator dapat membuat/menugaskan task dan meninjau laporan. Field officer yang ditugaskan
dapat memulai pekerjaan dan mengirim laporan SIMULASI. Transisi ilegal menghasilkan `409`,
pelanggaran role/ownership menghasilkan `403`, dan setiap perubahan menyimpan aktor/timestamp.

```bash
curl 'http://localhost:8000/api/v1/users?role=field_officer'
curl 'http://localhost:8000/api/v1/tasks?status=OPEN,ASSIGNED'
```

Contoh write, seluruh transisi, payload laporan, dan catatan adapter frontend tersedia di
[tasks-handoff.md](docs/tasks-handoff.md). Endpoint write wajib Bearer token; backend mengabaikan
identitas aktor buatan dari client.

## Eksperimen GWT +1 hari (BE-07)

Pipeline eksperimen melatih `RandomForestRegressor` untuk BRG6 dan BRG3 dengan fitur lag
1/3/7 hari, rolling mean yang sudah digeser, dan perubahan historis. Missing, konflik duplikat,
serta tanggal kalender yang terputus tidak diinterpolasi dan tidak digunakan sebagai lag.
Split train/validation/test selalu kronologis; parameter dipilih pada validation lalu test hanya
dievaluasi sekali. Baseline persistence dan model memakai tanggal test yang sama.

```bash
.venv/bin/python -m app.cli train-gwt dataset/mmc1.xlsx
```

Output lengkap, termasuk prediksi test, ditulis ke `var/ml/*.metrics.json` dan diabaikan Git.
Angka tersebut adalah **HASIL EKSPERIMEN HISTORIS 2018–2019**, bukan forecast kondisi 2026.
Model yang tidak mengalahkan baseline diberi gate `EXPERIMENT_ONLY` dan tidak boleh dipakai
oleh decision engine. Training menyimpan manifest metrics dan artifact `.joblib` ber-versi.
`GET /api/v1/ml/metrics` dan `POST /api/v1/ml/forecast` menyediakan hasil eksperimen dan
forecast historis dengan tujuh lag kalender lengkap. Kontrak integrasi tersedia di
[ml-handoff.md](docs/ml-handoff.md).

## Audit dan import data

```bash
.venv/bin/python -m app.cli audit-gwt dataset/mmc1.xlsx
.venv/bin/python -m app.cli import-gwt dataset/mmc1.xlsx
.venv/bin/python -m app.cli import-gwt dataset/mmc1.xlsx --apply
.venv/bin/python -m app.cli audit-hotspots dataset/viirs-snpp_2019_Indonesia.csv \
  --output var/audits/viirs-2019.json
.venv/bin/python -m app.cli import-hotspots dataset/viirs-snpp_2019_Indonesia.csv \
  --from 2019-08-01 --to 2019-08-31 --bbox '100,-4,112,2' --apply
```

Import tanpa `--apply` hanya mengaudit. Import hotspot tanpa filter tanggal/bbox memerlukan
`--allow-full-dataset`. Ketiga CSV lokal memuat 809.523 baris; gunakan filter untuk demo kecil.
Nama file harus memuat `snpp` atau `jpss1` agar produk dapat diidentifikasi.

Audit JSON dan CSV GWT ternormalisasi ditulis ke `var/audits/`, yang diabaikan Git. Workbook
asli dipertahankan. Hash SHA-256 dan nomor baris sumber disimpan bersama data; riwayat import
menyimpan audit, jumlah insert/skip, dan waktu selesai. Seluruh file dalam satu perintah import
berada dalam satu transaksi; kegagalan menyebabkan rollback.

Kebijakan GWT: `#N/A` menjadi `null/MISSING`; konflik duplikat menjadi satu observasi
`null/DUPLICATE`, dengan nilai mentah tersimpan pada audit. BRG5 tanggal 2019-03-21 memiliki
dua nilai berbeda. Audit menghasilkan 3.928 observasi unik: 3.534 valid, 393 missing, dan satu
konflik duplikat. Tidak ada interpolasi atau koreksi tanggal otomatis. Sheet `wrc` (110 baris)
hanya dicatat sebagai arsip penelitian. Kalender yang tidak memiliki baris tetap menjadi gap.

Semua import lokal memakai `HISTORICAL_REPLAY`. Koordinat stasiun tetap null sampai sumber
terverifikasi tersedia. Timestamp GWT pada API adalah representasi tanggal harian pada
00:00 UTC, bukan jam pengukuran yang diketahui. Data penelitian dapat mengandung pengolahan
sebelumnya; flag VALID berarti numerik valid untuk pipeline, bukan bukti pengukuran langsung.

VIIRS memakai waktu akuisisi UTC, confidence mentah, instrument dan satellite dari CSV,
serta key stabil dari produk/satelit/waktu/koordinat. Reimport tidak menambah observasi yang
sama. `last_synced_at` pada CSV berarti waktu import lokal, bukan keberhasilan sync NASA live.
Hotspot menunjukkan anomali panas satelit; confidence tidak menunjukkan probabilitas kebakaran.

## Kontrak read API

- `GET /api/v1/stations`: array stasiun terurut menurut code, ID berupa UUID.
- `GET /api/v1/stations/{uuid}/groundwater?from=2019-01-01&to=2019-01-31&mode=HISTORICAL_REPLAY`:
  array observasi terurut tanggal naik, batas tanggal inklusif, nilai null dipertahankan.
- `GET /api/v1/hotspots?from=2019-01-01&to=2019-01-31&bbox=100,-4,112,2&satellite=N`:
  respons `{items,total,limit,offset}`, default limit 200, maksimum 1000; terurut waktu turun
  dengan UUID sebagai pemutus urutan. `source_product` dan `mode` juga dapat difilter.

Mode default adalah `HISTORICAL_REPLAY`. Query `CURRENT_MONITORING` kosong sampai observasi
terkini tersedia. API menolak rentang tanggal terbalik, bbox tidak valid, UUID invalid, dan
pagination di luar batas dengan `422`; stasiun tidak ditemukan menghasilkan `404`.
Produk CSV: `VIIRS_SNPP_HISTORICAL` dan `VIIRS_NOAA20_HISTORICAL`; satellite mentah `N`/`N20`.
Koneksi read API memakai SQLAlchemy async; import CLI memakai transaksi sinkron dan COPY.

## Database

Migration pertama mengaktifkan PostGIS dan `pgcrypto`, lalu membuat:

- `data_sources`, `stations`, dan `groundwater_observations` dengan provenance serta nilai null;
- `hotspots` dengan titik EPSG:4326 dan indeks GiST;
- `priority_assessments` dengan snapshot JSON dan versi rule;
- `users`, `inspection_tasks`, `field_reports`, serta `task_status_history`.
- `data_import_runs` untuk audit dan hasil import; kolom mode membedakan observasi historis/terkini.
- `firms_sync_runs` untuk status/riwayat percobaan sync, cooldown dan sumber respons.
- Migration workflow melengkapi task dengan mode/area/label simulasi, validasi hasil laporan,
  history aktor/catatan, indeks foreign key, serta RLS untuk tabel workflow.

Koordinat stasiun harus lengkap dan memiliki `coordinate_source`. Status, role, mode, prioritas,
dan kualitas data dibatasi oleh constraint database. Menjalankan migration offline tanpa database:

```bash
.venv/bin/alembic upgrade head --sql
```

## Verifikasi

```bash
.venv/bin/ruff check .
.venv/bin/pytest
```

Smoke Supabase end-to-end tanpa meninggalkan task/report pengujian:

```bash
.venv/bin/python scripts/smoke_supabase_api.py
```

Script memeriksa health/OpenAPI, users, stations, GWT, hotspot Batanghari, priorities dua area,
metrics serta forecast BRG3/BRG6 yang dibandingkan dengan artifact, penolakan forecast tanpa
riwayat GWT, dan workflow `ASSIGNED → IN_PROGRESS → SUBMITTED → VERIFIED`. Token mengikuti
settings backend. Seluruh write dijalankan pada savepoint lalu transaksi luar di-rollback;
eksekusi dibatasi 120 detik. Hasil QA terbaru: **67 tes PASS tanpa skip** dengan PostGIS
terisolasi, Ruff PASS dan smoke Supabase PASS. Prosedur serta batas verifikasi tersedia di
[backend-qa.md](docs/backend-qa.md).

Tes foundation mencakup health, autentikasi/otorisasi role, CORS, publikasi kontrak OpenAPI,
konfigurasi production, nullable GWT, mode historis, metadata tabel, kontrak task/report, dan
state machine. Tes migration serta persistensi workflow terhadap PostgreSQL nyata memerlukan
Docker/PostGIS yang aktif.

Tes data mencakup audit workbook nyata, duplikat, null/nol, UTC, key stabil, filter, dan API.
Integration test memakai database khusus dengan nama berakhiran `_test`, lalu menjalankan
migration upgrade/downgrade; jangan arahkan ke database aplikasi yang memiliki data penting.

```bash
TEST_DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/gambutops_test \
  .venv/bin/pytest
```

Tanpa variabel tersebut tes integrasi dilewati dengan alasan eksplisit.

