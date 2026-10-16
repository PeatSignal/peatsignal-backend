# Kontrak API PeatSignal untuk penilaian

Panduan ini melengkapi [README submission](../../README.md). Schema lengkap, field wajib, enum dan format response berasal dari FastAPI pada [`/docs`](http://localhost:8000/docs) dan [`/openapi.json`](http://localhost:8000/openapi.json). Semua path di bawah relatif terhadap `http://localhost:8000/api/v1`, kecuali `/health`.

## Konvensi

- JSON `snake_case`; UUID string; tanggal `YYYY-MM-DD`; timestamp dengan timezone, misalnya `2019-09-15T23:59:59Z`.
- `mode`: `HISTORICAL_REPLAY` atau `CURRENT_MONITORING`. Data historis tidak dipindahkan ke mode terkini.
- `area_id` pada hujan/prioritas: `batanghari` atau `kubu-raya`. FIRMS juga mendukung `indonesia`.
- `bbox`: `west,south,east,north`, contoh `102.9,-2.2,104,-1.3`.
- GWT API dalam **meter**, galat MAE/RMSE dalam **cm**, hujan dalam **mm/hari**. `null` adalah tidak tersedia, bukan nol.
- Field JSON internal pada snapshot dapat berkembang; gunakan schema OpenAPI dan `rule_version` untuk interpretasi.

## Auth dan peran

```bash
curl -sS http://localhost:8000/api/v1/auth/me \
  -H 'Authorization: Bearer demo-coordinator-token'
```

Respons development:

```json
{
  "id": "00000000-0000-4000-8000-000000000001",
  "role": "coordinator",
  "display_name": "Koordinator Demo"
}
```

Petugas memakai `demo-field-officer-token`, ID `00000000-0000-4000-8000-000000000002`. Token dapat diubah dalam konfigurasi backend. Identitas aktor diturunkan dari token, bukan dari body atau header aktor buatan klien.

Read endpoint publik untuk prototipe, kecuali `/auth/me`. POST assessment/forecast bersifat publik; POST sinkron dan task/PATCH/report memeriksa token serta role. Pada production, backend mensyaratkan dua token berbeda, minimal 32 karakter; skema ini tetap identitas demo, bukan autentikasi pengguna produksi.

## Sistem dan monitoring

| Method / path | Parameter | Bentuk response |
| --- | --- | --- |
| `GET /health` (root origin) | — | `{status:"ok", service, version, environment}` |
| `GET /users` | `role?` | Array `{id, role, display_name}` |
| `GET /stations` | — | Array `{id, code, region, latitude, longitude, coordinate_source, period_start, period_end, source}` |
| `GET /stations/{uuid}/groundwater` | `from?`, `to?`, `mode?` (default historis) | Array observasi GWT |
| `GET /hotspots` | `from?`, `to?`, `mode?`, `bbox?`, `satellite?`, `source_product?`, `limit=200` (1–1000), `offset=0` | `{items, total, limit, offset}` |
| `GET /hotspots/map` | Filter hotspot tanpa `limit`/`offset` | `{mode, items:[marker...]}` |

Observasi GWT memuat `id`, `station_id`, `observed_date`, `observed_at`, `gwt_m`, `quality_flag`, `source`, `source_id`, `source_sha256`, `mode`. Kualitas: `VALID`, `MISSING`, `DUPLICATE`, `SUSPECT`. Tanggal tanpa pengukuran tidak boleh dianggap bernilai nol.

Item daftar hotspot memakai field backend `acquired_at`, `frp`, `sensor`, beserta koordinat, satelit, produk, sumber, kualitas, mode dan waktu sinkron. Marker peta berupa payload ringkas: `id`, `latitude`, `longitude`, `observed_at`, `frp_mw`, `verification_status`, `list_offset`. `list_offset` menghubungkan marker ke posisi dalam daftar yang memakai filter sama; map tidak terpotong pagination.

```bash
curl -sS 'http://localhost:8000/api/v1/hotspots/map?mode=HISTORICAL_REPLAY&from=2019-08-17&to=2019-09-15&bbox=102.9,-2.2,104,-1.3'
```

Frontend mode terkini meminta bbox nasional `[94,-11.5,141.5,6.5]`. Perbedaan tanggal/satelit/bbox dapat menghasilkan titik yang berbeda walaupun endpoint sama.

## Prioritas wilayah

`GET /priorities` wajib menerima `mode` dan `as_of` timestamp bertimezone yang tidak di masa depan. `area_id` opsional; tanpa area menghasilkan penilaian dua wilayah demo.

```bash
curl -sS 'http://localhost:8000/api/v1/priorities?mode=HISTORICAL_REPLAY&as_of=2019-09-15T23:59:59Z&area_id=batanghari'
```

Response array assessment memuat `id`, `area_id`, `mode`, `as_of`, `decision`, `priority`, `explanation`, `reason_codes`, `missing_inputs`, `input_snapshot`, `recommended_actions`, `rule_version`, `scientific_status`.

- Decision: `REVIEW`, `MONITOR`, `ESCALATE`, `INSUFFICIENT_DATA`.
- Priority: `HIGH`, `MEDIUM`, `LOW`, `INSUFFICIENT_DATA`.
- Snapshot disimpan dalam DB; `id` dapat menjadi `assessment_id` pada pembuatan tugas.
- Ini endpoint GET yang **melakukan penyimpanan snapshot**. Request identik tidak menduplikasi assessment yang sama.
- Assessment wilayah terpisah dari input lapangan stateless `/prevention/assess`. Hujan otomatis pada form lapangan tidak otomatis menjadi input mesin prioritas wilayah.

## Forecast historis

`GET /ml/metrics`: `{status:"AVAILABLE", experiments:[...]}` atau `{status:"NOT_AVAILABLE", reason}`. Setiap eksperimen memuat stasiun, fitur, periode train/test, ukuran test, `model_metrics`, `baseline_metrics`, `beats_baseline`, prediction points, versi dan `release_gate`.

`POST /ml/forecast`:

```json
{"station_id":"<UUID dari GET /stations>","date":"2019-07-18"}
```

`date` adalah input terakhir, target satu hari setelahnya. Contoh tanggal di atas untuk BRG6; pilih tanggal dengan tujuh hari valid pada database setelah import.

- Berhasil: `{status:"OK", station_id, input_date, forecast_date, predicted_gwt_m, baseline_gwt_m, model_version, release_gate}`.
- Tidak dapat dibuat: `{status:"REJECTED", reason}` dengan HTTP 200 (penolakan bisnis, bukan HTTP error).
- Endpoint ini mengambil GWT historis dari DB; untuk nilai baru dari pengguna gunakan endpoint berikut.

## Input GWT baru + rekomendasi

`POST /prevention/assess` tidak membutuhkan koneksi database, tidak menyimpan pengukuran, tidak membuat tugas, dan tidak mengubah prioritas wilayah. Artifact lokal opsional: jika belum ada, metode menjadi baseline saja.

| Field request | Aturan |
| --- | --- |
| `station_code` | `BRG3` / `BRG6` |
| `source_kind` | `MANUAL` / `DEMO` |
| `source_note` | Setelah trim, 3–300 karakter |
| `rainfall_mode` | `MANUAL` (default API), `AUTO`, `CHIRPS`; default UI adalah AUTO |
| `readings` | Tepat 7 tanggal berurutan, tanpa duplikat/gap, tidak melewati hari ini UTC |
| `readings[].date` | Tanggal kalender UTC |
| `readings[].gwt_m` | Angka finite −10 sampai 2 meter |
| `readings[].rainfall_mm` | Opsional/null atau angka finite 0–1500 mm |

Pada AUTO/CHIRPS, server mengambil ulang hujan dan **mengabaikan nilai hujan yang dikirim klien**. Source otomatis mengikuti mapping stasiun ke DEMO Batanghari. Prakiraan hari ini dikecualikan dari input efektif. Untuk sumber manual, `0` tetap nol dan `null` tetap tidak diketahui.

### Request yang dapat langsung dijalankan

Dari `backend/`, buat tujuh tanggal terbaru secara dinamis agar contoh tidak kedaluwarsa. Contoh ini **sintetis**, bukan pengukuran lapangan:

```bash
.venv/bin/python - <<'PY'
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
end = datetime.now(UTC).date() - timedelta(days=1)
values = [-0.32, -0.35, -0.39, -0.42, -0.45, -0.48, -0.52]
body = {
    "station_code": "BRG6",
    "source_kind": "DEMO",
    "source_note": "Skenario sintetis penilaian juri",
    "rainfall_mode": "MANUAL",
    "readings": [
        {"date": (end-timedelta(days=6-i)).isoformat(), "gwt_m": value, "rainfall_mm": 0}
        for i, value in enumerate(values)
    ],
}
Path('/tmp/peatsignal-assess.json').write_text(json.dumps(body))
PY

curl -sS http://localhost:8000/api/v1/prevention/assess \
  -H 'Content-Type: application/json' \
  --data-binary @/tmp/peatsignal-assess.json
```

Response utama:

| Field | Makna |
| --- | --- |
| `source_kind`, `source_note`, `is_simulation`, `observation_status` | Asal dan status validasi input |
| `input_date`, `freshness` | Tanggal terakhir dan `RECENT`/`STALE` |
| `forecast` | Status, tanggal target, metode terpilih, GWT model/baseline, metrics dan alasan |
| `prevention` | Priority, alasan, tindakan, input kurang, GWT/delta, total hujan/dry spell, versi aturan |
| `rainfall` | Seri hujan/provenance otomatis, atau null untuk manual |
| `readings` | Input efektif yang benar-benar dipakai assessment |
| `limitations` | Batasan hasil |

`forecast.status`: `EXPERIMENTAL`, `BASELINE_ONLY`, `NOT_AVAILABLE`. `selected_method`: `RANDOM_FOREST`, `PERSISTENCE`, atau null. Input stale (>2 hari) tidak menghasilkan prediksi terkini. `prevention.forecast_used` selalu false; kandidat ML tidak menaikkan prioritas rekomendasi.

## Curah hujan

```text
GET /rainfall/automatic?area_id=batanghari&date_to=YYYY-MM-DD
GET /rainfall/chirps?area_id=batanghari&date_to=YYYY-MM-DD
```

Keduanya mengambil tujuh tanggal sampai `date_to`; tanggal akhir tidak boleh di masa depan dan tanggal awal minimal 1981-01-01. Automatic memilih Open-Meteo bila tanggal akhir dalam 14 hari terakhir, selain itu CHIRPS. Endpoint CHIRPS selalu memakai CHIRPS.

Response memuat `status`, `dataset_id`, `provider`, `scope`, area/bbox/titik referensi, resolusi/statistik, `date_from`, `date_to`, `retrieved_at`, `note`, `job_id`, `days`.

- Status: `AVAILABLE`, `PARTIAL`, `NOT_AVAILABLE`, `PENDING`, `ERROR`.
- Provider: `OPEN_METEO` / `CLIMATESERV`.
- `days[]`: `date`, `rainfall_mm`, `source_url`, `valid_cells`, `kind`, `eligible_for_assessment`.
- Kind: `MODEL_ESTIMATE`, `HISTORICAL_ESTIMATE`, `FORECAST`.
- `PENDING`: periksa ulang periode sama; job CHIRPS dipakai ulang. Kesalahan upstream dilaporkan melalui status/seri kosong, bukan hujan nol.
- `AVAILABLE` dapat berarti tujuh nilai ditampilkan, tetapi rekomendasi masih 6/7 bila hari ini `FORECAST` dan tidak eligible.

## Sinkron FIRMS

`GET /hotspots/sync-status` menerima filter opsional `area_id`, `source_product`; response status per target: `NOT_SYNCED`, `RUNNING`, `SUCCESS`, `FAILED` dan informasi attempt terakhir.

`POST /admin/hotspots/sync` memerlukan Bearer koordinator dan key NASA backend:

```json
{"area_id":"indonesia","source_product":"VIIRS_SNPP_NRT","day_range":3}
```

Area: `indonesia`, `batanghari`, `kubu-raya`. Produk: `VIIRS_SNPP_NRT`, `VIIRS_NOAA20_NRT`. Hari: 1–5. Hasil memuat ID attempt, target, status, periode, waktu mulai/selesai, jumlah diterima/insert/konflik, dan kode error. Cooldown dapat menghasilkan HTTP 429 serta header `Retry-After`.

## Tugas, laporan, dan transisi

`GET /tasks` menerima `mode?`, `status?` (CSV seperti `OPEN,ASSIGNED`), `assignee_id?`. `GET /tasks/{uuid}` menyertakan `reports`; list/create/update menyertakan `history`.

### Buat tugas — koordinator

```json
{
  "mode": "HISTORICAL_REPLAY",
  "title": "Periksa lokasi DEMO Batanghari",
  "priority": "HIGH",
  "assessment_id": "<UUID assessment dari GET /priorities>",
  "assignee_id": "00000000-0000-4000-8000-000000000002",
  "note": "Skenario penilaian, bukan penugasan lapangan nyata"
}
```

Kirim ke `POST /tasks` dengan Bearer koordinator. Alternatif referensi adalah `hotspot_id`. Minimal satu referensi wajib, mode harus cocok; jika keduanya diberikan, hotspot harus terdapat pada snapshot assessment. Tanpa assignee status awal OPEN; dengan assignee ASSIGNED. Contoh UUID placeholder perlu diganti, bukan dikirim secara literal.

### Perbarui dan kirim laporan

`PATCH /tasks/{uuid}` menerima minimal satu field `status`, `assignee_id`, `note`. Contoh petugas memulai tugas: `{"status":"IN_PROGRESS"}`.

Petugas yang ditugaskan mengirim `POST /tasks/{uuid}/reports`:

```json
{
  "observed_at": "<timestamp UTC sesudah tugas dibuat dan tidak di masa depan>",
  "result": "NO_FIRE_FOUND",
  "note": "Contoh pemeriksaan untuk penilaian, tidak ada api teramati dalam skenario.",
  "is_simulation": true
}
```

`evidence_url` opsional berupa URL HTTP/HTTPS; bukan upload berkas. Hasil: `ACTIVE_FIRE_FOUND`, `BURN_SCAR_FOUND`, `NO_FIRE_FOUND`, `LOCATION_INACCESSIBLE`. Laporan prototipe wajib `is_simulation: true`.

| Dari | Ke | Aktor / endpoint |
| --- | --- | --- |
| OPEN | ASSIGNED | Koordinator PATCH dengan assignee |
| ASSIGNED | IN_PROGRESS | Petugas pemilik PATCH |
| IN_PROGRESS | SUBMITTED | Petugas pemilik POST report |
| SUBMITTED | VERIFIED / DISMISSED / NEEDS_FOLLOWUP | Koordinator PATCH |
| NEEDS_FOLLOWUP | ASSIGNED | Koordinator PATCH dengan assignee |

SUBMITTED tidak boleh ditetapkan lewat PATCH. History memuat `from`, `to`, `actor_id`, `actor_role`, `at`, `note`. Koordinator meninjau, petugas hanya memproses tugas yang ditugaskan kepadanya. Laporan simulasi tidak diperlakukan sebagai bukti nyata dalam penilaian wilayah terkini.

## Status HTTP dan error

| HTTP | Makna |
| --- | --- |
| 200 | Read/update/assessment, termasuk business envelope NOT_AVAILABLE/REJECTED |
| 201 | Task atau laporan berhasil dibuat |
| 401 | Bearer tidak ada/tidak valid |
| 403 | Role atau ownership tidak sesuai |
| 404 | Resource tidak ditemukan |
| 409 | Konflik state/transisi/refensi bisnis |
| 422 | Payload/query/date/enum tidak valid |
| 429 | Cooldown/rate limit FIRMS |
| 5xx | Kegagalan server atau layanan upstream tertentu |

Error HTTP umumnya `{"detail":"pesan"}`; validasi FastAPI menghasilkan `detail` array dengan lokasi field, pesan dan tipe error. Jangan menyamakan status data kosong dengan HTTP error. Baca `status`, `reason`, `missing_inputs` dan `limitations` pada response bisnis.
