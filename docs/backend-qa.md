# Verifikasi backend — 15 Oktober 2026

Branch yang diperiksa: `feat/backend-ml`, kode ML pada commit `ff35c83`.
Penguatan smoke dan pembaruan dokumentasi dilakukan setelah commit tersebut.

## Hasil

| Pemeriksaan | Hasil |
| --- | --- |
| `.venv/bin/ruff check .` | PASS |
| `.venv/bin/pytest` tanpa database tes | 63 PASS, 4 SKIP |
| Suite lengkap dengan PostGIS lokal terisolasi | 67 PASS, 0 SKIP |
| Smoke API lokal melalui ASGI dengan database Supabase | PASS; seluruh write di-rollback |
| Metrics ML BRG3/BRG6 | AVAILABLE; kedua model EXPERIMENT_ONLY |
| Forecast BRG3 pada input 2019-06-13 | Target 2019-06-14; prediksi/baseline sesuai artifact |
| Forecast BRG6 pada input 2019-07-18 | Target 2019-07-19; prediksi/baseline sesuai artifact |
| Forecast BRG6 pada input 2026-10-15 tanpa GWT terkini | REJECTED |
| Workflow Supabase | ASSIGNED → IN_PROGRESS → SUBMITTED → VERIFIED; 5 history entries |

Suite lengkap mencakup upgrade/downgrade migration, import/reimport dan rollback COPY,
API monitoring, client/sync FIRMS dengan fixture, priorities, role/state machine, persistensi
task/report serta pipeline dan kontrak ML. Suite ini tidak melakukan sync NASA live baru.

Smoke membaca delapan stasiun, 15 observasi GWT BRG6 pada 1–15 September 2019,
3.439 hotspot historis Batanghari pada rentang seed, serta dua area prioritas demo.
API dijalankan di proses pengujian lokal; ini belum memverifikasi host API publik,
reverse proxy, TLS, CORS domain deployment, atau browser frontend.

## Mengulang suite lengkap

Dari `backend/`, jalankan PostGIS lokal:

```bash
docker compose up -d postgres
```

Buat database **baru** khusus QA. Nama harus berakhiran `_test`; fixture integration test
menjalankan downgrade/upgrade dan menghapus tabel domain pada database tersebut.
Perintah berikut memakai nama sesi ini. Jika nama sudah ada, gunakan nama database tes baru
atau pastikan database yang ada memang khusus QA sebelum melanjutkan.

```bash
docker compose exec -T postgres createdb -U gambutops gambutops_qa_20261015_test
TEST_DATABASE_URL=postgresql+psycopg://gambutops:gambutops@127.0.0.1:5433/gambutops_qa_20261015_test \
  .venv/bin/pytest
.venv/bin/ruff check .
```

Hanya database khusus QA yang digunakan oleh migration test; `.env` aplikasi tidak diubah.

## Mengulang smoke Supabase

Gunakan `.env` backend yang sudah dikonfigurasi ke database Supabase dan artifact lokal
pada `ML_ARTIFACT_DIR` (default `var/ml`). Jika artifact belum tersedia,
ikuti [handoff ML](ml-handoff.md) untuk training dari dataset sumber.

```bash
.venv/bin/python scripts/smoke_supabase_api.py
```

Script menggunakan token coordinator/petugas dari settings, sehingga tetap bekerja saat token
demo diganti. Metrics harus memuat BRG3 dan BRG6; forecast pertama pada test setiap model
dibandingkan dengan prediksi, baseline, versi, gate dan tanggal manifest. Forecast tanpa
riwayat terkini harus ditolak. Semua request database berbagi transaksi luar dengan savepoint;
commit endpoint tidak mempertahankan perubahan setelah rollback transaksi luar.
Eksekusi dibatasi 120 detik agar koneksi bermasalah tidak menggantung tanpa batas.

Pada sesi ini akses database dari sandbox tidak selesai; menjalankan smoke dengan akses
jaringan di luar sandbox berhasil. Tidak ada perubahan schema atau seed Supabase pada sesi ini.

## Gate berikutnya

- Review kontrak dan integrasi browser frontend, termasuk mode/filter dan workflow lengkap.
- Pilih host backend, sertakan artifact ML, konfigurasi secret dan CORS domain frontend.
- Ulangi smoke dengan runtime deployment dan periksa URL publik melalui browser.
- Tutup review/merge dan acceptance sebelum freeze/submission.
