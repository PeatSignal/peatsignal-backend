# BE-04 — NASA FIRMS live

Backend menyediakan sync manual untuk dua bbox DEMO: Batanghari dan Kubu Raya. Produk
yang didukung: `VIIRS_SNPP_NRT`, `VIIRS_NOAA20_NRT`. Default tiga hari kalender UTC terbaru,
maksimal lima hari. Batas DEMO adalah area filter perkiraan, bukan batas administratif resmi.
Definisi NASA tersedia di https://firms.modaps.eosdis.nasa.gov/api/area/.

## Konfigurasi dan menjalankan

Key dibaca dari `FIRMS_MAP_KEY` pada environment/`.env`. File `api_key_firms.md`
yang sudah tersedia lokal dapat dimuat tanpa menampilkan key:

```bash
cd backend
.venv/bin/python scripts/configure_firms_key.py
.venv/bin/alembic upgrade head
.venv/bin/python -m app.cli sync-hotspots --area batanghari --product VIIRS_SNPP_NRT
.venv/bin/python -m app.cli sync-hotspots --area batanghari --product VIIRS_SNPP_NRT --apply
```

Perintah tanpa `--apply` hanya menampilkan request aman; tidak menghubungi NASA/database.
Key yang sudah dikonfigurasi dipertahankan. `.env` dan file key tetap diabaikan Git.
CLI lokal memakai identitas coordinator demo yang diseed; endpoint HTTP membutuhkan bearer.
Tidak ada scheduler atau retry otomatis. Read hotspot API tidak memanggil NASA.

## Kontrak HTTP

`POST /api/v1/admin/hotspots/sync`, bearer coordinator. Contoh body:

```json
{"area_id":"batanghari","source_product":"VIIRS_SNPP_NRT","day_range":3}
```

Respons sukses menyertakan `id`, `area_id`, `source_product`, `status`, `date_from`, `date_to`,
`started_at`, `completed_at`, `rows_received`, `rows_inserted`, `rows_conflicts`, `error_code`.
Seluruh timestamp memiliki timezone UTC. Header CSV valid tanpa baris → SUCCESS dengan counts 0.

`GET /api/v1/hotspots/sync-status?area_id=batanghari&source_product=VIIRS_SNPP_NRT`
menghasilkan array target dengan `status`, `last_attempt` dan `last_successful_at`.
Filter opsional; tanpa filter ada empat target (dua wilayah × dua produk). Sebelum sync:
NOT_SYNCED dan timestamp null. Percobaan terbaru gagal tetap mempertahankan waktu keberhasilan
terakhir. RUNNING yang melewati 120 detik ditampilkan sebagai FAILED/INTERRUPTED; percobaan
baru setelah cooldown merekam penutupan run lama yang terputus.

| Status HTTP | Makna |
| --- | --- |
| 401 / 403 | Token tidak valid atau role bukan coordinator |
| 422 | Area/produk/day_range tidak didukung |
| 409 | Sync target sedang berjalan pada proses lain |
| 429 | Cooldown 600 detik dari awal percobaan; lihat header Retry-After |
| 503 | Key belum dikonfigurasi; tidak memanggil NASA |
| 502 | Koneksi/upstream/CSV/import gagal; cache lama tetap tersedia |
| 504 | Timeout request NASA |

Riwayat sync dan cooldown disimpan pada PostgreSQL, sehingga berlaku lintas worker. Lock
advisory memakai koneksi khusus dan dilepas sebelum koneksi kembali ke pool. Status RUNNING
dicommit sebelum download agar terlihat oleh UI. Import hotspot/provenance dan status SUCCESS
ada dalam satu transaksi; kegagalan mencatat FAILED dalam transaksi terpisah.

## Integrasi frontend

- Kontrak `GET /api/v1/hotspots` tetap `{items,total,limit,offset}` dengan field yang sudah
  disepakati pada handoff read API. Query `mode=CURRENT_MONITORING` membaca cache NRT.
- Untuk sync global, gunakan endpoint status di atas. Timestamp item `last_synced_at` adalah
  refresh pengamatan tersebut; `last_successful_at` adalah keberhasilan sync target, termasuk
  sync sukses yang tidak menemukan hotspot.
- Field `source_product` adalah kode produk NASA NRT; `source` adalah NASA FIRMS Area API.
  Mapping sensor/instrument, acquired_at/observed_at dan frp/frp_mw tetap melalui REST adapter.
- Key NASA tidak dikirim ke browser. Tombol sync memakai autentikasi coordinator backend;
  header X-Actor-Id saja tidak mengautentikasi pengguna.
- Cooldown/error tidak boleh menyembunyikan cache atau menampilkan data mock sebagai live.
- Hasil kosong berarti tidak ada baris dari request tersebut, bukan kondisi aman yang terverifikasi.
- GWT historis tetap tidak dipakai sebagai GWT terkini; priorities belum diimplementasikan.

## Identitas pengamatan dan batas sumber

CSV/HTTP memakai normalisasi row dan fungsi key stabil yang sama untuk produk identik,
berdasarkan produk, UTC, koordinat lima desimal dan satelit. Sumber historis dan NRT memiliki
kode produk berbeda dan mode berbeda; keduanya tidak digabung menjadi satu pengamatan.
Key berulang pada NRT memperbarui FRP/confidence/provenance dan waktu refresh, sambil
mempertahankan ID serta verification_status. Tidak ada penghapusan cache lama.

SHA-256 respons mentah tercatat pada DataSource dan riwayat sync. URL sumber yang disimpan
tidak memuat key. Respons dibatasi 20 MB, connect timeout 5 detik, request keseluruhan 30 detik.
HTML/error text dengan HTTP 200, header invalid, field kosong wajib, scope bbox/periode salah,
koordinat/FRP invalid, atau produk/satelit tidak cocok ditolak sebelum import.

NASA dapat memperbarui RT/URT menjadi NRT; BE-04 mengupsert key identik namun tidak mencoba
merekonsiliasi deteksi yang berubah waktu/koordinat. Confidence tetap nilai mentah satelit.

## Bukti verifikasi

Uji live pada 15 Oktober 2026 WIB (14 Oktober 2026 UTC) berhasil untuk Batanghari/SNPP:
periode UTC 2026-10-12–2026-10-14, 11 received/inserted, 0 conflicts. Contoh respons aktual
tersimpan di [examples/firms-live.json](examples/firms-live.json). Tiga item ditampilkan sebagai
contoh bounded; total cache untuk query itu 11.

Smoke read API juga memastikan 6.403 hotspot historis serta 3.928 GWT tetap utuh. Contoh ini
snapshot satu target yang berhasil diuji live; tiga target lainnya belum diklaim diuji live.
Untuk mengambil ulang contoh cache/status tanpa memanggil NASA:

```bash
.venv/bin/python scripts/capture_firms_examples.py
```

Tes otomatis mencakup parser/client, secret redaction, auth, cooldown, concurrency, upsert,
rollback, persistensi status dan migration PostGIS. Verifikasi final: 39 pytest PASS dan Ruff PASS,
termasuk helper key yang mempertahankan konfigurasi dan permission file privat.
Panduan Postgres digunakan untuk advisory lock pada koneksi khusus dan indeks target/waktu.
Integrasi peta/frontend masih milik teman;
Tahap 2 aplikasi baru selesai ketika hotspot nyata tampil dan filter bekerja melalui browser.

## Cakupan nasional Terkini

Sinkronisasi Terkini menggunakan `area_id: "indonesia"` dengan kotak koordinat
`94,-11.5,141.5,6.5`, mencakup Indonesia dari Aceh hingga Papua. Kotak koordinat
bukan batas negara administratif dan dapat mencakup titik di wilayah tetangga.
Status default berisi dua produk nasional: VIIRS_SNPP_NRT dan VIIRS_NOAA20_NRT.
Target Batanghari/Kubu Raya tetap diterima untuk kompatibilitas, tetapi UI Terkini
menggunakan cakupan nasional dan mengabaikan filter wilayah historis.
Terapkan `alembic upgrade head`, lalu sinkronkan kedua produk nasional.
