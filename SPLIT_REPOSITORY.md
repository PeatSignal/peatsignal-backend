# PeatSignal backend — repository terpisah

Semua perintah berikut dijalankan dari root repository backend.

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
cp .env.example .env
```

Isi `.env` lokal dengan koneksi database, origin frontend, token peran, dan key NASA.
Untuk database lokal gunakan `docker compose up -d postgres`; untuk database yang sudah
tersedia, sesuaikan `DATABASE_URL`. Jangan commit konfigurasi atau key pribadi.

```bash
.venv/bin/alembic upgrade head
.venv/bin/python -m app.cli import-gwt dataset/mmc1.xlsx --apply
.venv/bin/python -m app.cli train-gwt dataset/mmc1.xlsx
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

## Dataset

`dataset/mmc1.xlsx` disertakan untuk audit/import GWT dan training ML.
Ketiga CSV hotspot asli disalin tanpa perubahan isi sebagai `.csv.gz` untuk menghemat disk.
Buka hanya arsip yang diperlukan, misalnya:

```bash
gzip -dk dataset/viirs-snpp_2019_Indonesia.csv.gz
.venv/bin/python -m app.cli import-hotspots dataset/viirs-snpp_2019_Indonesia.csv --from 2019-08-17 --to 2019-09-15 --bbox '100,-4,112,2' --apply
```

Dekompresi ketiga arsip memerlukan sekitar 62 MiB tambahan. CSV hasil dekompresi di-ignore;
arsip `.gz` tetap bisa diunggah ke repository. Database yang sudah berisi data tidak perlu
mengulang import. Artefak ML tidak disalin; buat kembali melalui `train-gwt`.
Helper `scripts/configure_firms_key.py` membaca file opsional `api_key_firms.md`
di root repository ini; alternatifnya isi `FIRMS_MAP_KEY` langsung pada environment.

## Hosting Render

- Root Directory: kosong/default (kode backend sudah di root).
- Runtime: Python 3.12+; pilih versi patch penuh pada `PYTHON_VERSION`.
- Build: `pip install . && gambutops train-gwt dataset/mmc1.xlsx`
- Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1`
- Health check: `/health`.
- Environment: `APP_ENV`, `DATABASE_URL`, `CORS_ALLOWED_ORIGINS`,
  `COORDINATOR_TOKEN`, `FIELD_OFFICER_TOKEN`, `FIRMS_MAP_KEY`, `ML_ARTIFACT_DIR`.
- Migration/import dijalankan secara terpisah terhadap database tujuan.

## Pengujian

```bash
.venv/bin/ruff check .
.venv/bin/pytest
```

Tes database memerlukan `TEST_DATABASE_URL` menuju database khusus berakhiran `_test`.
Catatan QA lama mungkin masih menyebut struktur monorepo; gunakan jalur dari panduan ini.
