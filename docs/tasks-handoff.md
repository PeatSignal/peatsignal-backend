# Handoff BE-06: tugas dan laporan lapangan

BE-06 menyediakan workflow persisten untuk membuat tugas dari assessment/hotspot, menugaskan
petugas, mengirim laporan lapangan SIMULASI, dan meninjau hasil. OpenAPI pada `/openapi.json`
menjadi acuan bentuk payload HTTP.

## Autentikasi dan identitas

Endpoint GET dapat dibaca tanpa token untuk prototype demo. Semua endpoint POST/PATCH wajib
mengirim `Authorization: Bearer <token>`. Backend mengambil UUID dan role aktor dari token;
header `X-Actor-Id` tidak dipercaya dan tidak dipakai.

Token development:

- coordinator: `demo-coordinator-token`
- field officer: `demo-field-officer-token`

Nilai tersebut hanya untuk development/test. Environment production wajib memakai token kuat
yang berbeda melalui `COORDINATOR_TOKEN` dan `FIELD_OFFICER_TOKEN`.

## Endpoint

| Method | Path | Akses | Keterangan |
| --- | --- | --- | --- |
| GET | `/api/v1/users?role=field_officer` | Publik demo | Daftar pengguna aktif untuk pilihan petugas |
| GET | `/api/v1/tasks` | Publik demo | Filter opsional `mode`, `status`, `assignee_id` |
| POST | `/api/v1/tasks` | Coordinator | Buat tugas OPEN atau ASSIGNED |
| GET | `/api/v1/tasks/{uuid}` | Publik demo | Detail, seluruh history, dan reports |
| PATCH | `/api/v1/tasks/{uuid}` | Sesuai transisi | Ubah status, assignment, atau catatan |
| POST | `/api/v1/tasks/{uuid}/reports` | Field officer pemilik | Kirim laporan dan ubah status menjadi SUBMITTED |

Filter `status` menerima satu nilai atau CSV, misalnya
`status=OPEN,ASSIGNED,IN_PROGRESS`. Daftar diurutkan menurut `updated_at` terbaru.

## Membuat tugas

Tugas wajib merujuk minimal satu `assessment_id` atau `hotspot_id`. Mode referensi harus sama
dengan mode tugas. Jika keduanya dikirim, hotspot harus terdapat dalam snapshot assessment.
Backend menurunkan `area_id` dari snapshot assessment jika tersedia dan menolak area yang tidak
sesuai. Assignee harus pengguna aktif dengan role `field_officer`.

```http
POST /api/v1/tasks
Authorization: Bearer demo-coordinator-token
Content-Type: application/json

{
  "mode": "CURRENT_MONITORING",
  "title": "Periksa anomali panas DEMO",
  "priority": "HIGH",
  "hotspot_id": "<uuid-hotspot>",
  "area_id": "kubu-raya",
  "assignee_id": "00000000-0000-4000-8000-000000000002",
  "note": "Prioritas pemeriksaan simulasi"
}
```

Tanpa `assignee_id`, status awal adalah `OPEN`. Dengan assignee, backend mencatat history
`OPEN` lalu `OPEN → ASSIGNED`. Semua tugas prototype diberi `is_simulation: true`.

## State machine dan kewenangan

| Dari | Ke | Aktor | Cara |
| --- | --- | --- | --- |
| OPEN | ASSIGNED | Coordinator | PATCH dengan `status` dan `assignee_id` |
| ASSIGNED | IN_PROGRESS | Field officer yang ditugaskan | PATCH status |
| IN_PROGRESS | SUBMITTED | Field officer yang ditugaskan | POST report |
| SUBMITTED | VERIFIED | Coordinator | PATCH status |
| SUBMITTED | DISMISSED | Coordinator | PATCH status |
| SUBMITTED | NEEDS_FOLLOWUP | Coordinator | PATCH status |
| NEEDS_FOLLOWUP | ASSIGNED | Coordinator | PATCH dengan assignee |

`SUBMITTED` tidak dapat ditetapkan langsung melalui PATCH. Transisi di luar tabel menghasilkan
`409`; role/ownership yang salah menghasilkan `403`. Setiap perubahan menyimpan status asal,
status tujuan, UUID aktor, role aktor, waktu, dan catatan. Review VERIFIED/DISMISSED ikut
memperbarui `verification_status` hotspot yang terhubung.

## Laporan lapangan

```http
POST /api/v1/tasks/<uuid>/reports
Authorization: Bearer demo-field-officer-token
Content-Type: application/json

{
  "observed_at": "2026-10-15T08:30:00Z",
  "result": "NO_FIRE_FOUND",
  "note": "Tidak ada api teramati pada lokasi DEMO.",
  "evidence_url": "https://example.test/evidence/demo.jpg",
  "is_simulation": true
}
```

`result` menerima `ACTIVE_FIRE_FOUND`, `BURN_SCAR_FOUND`, `NO_FIRE_FOUND`, atau
`LOCATION_INACCESSIBLE`. `observed_at` wajib memiliki timezone, tidak boleh sebelum tugas dibuat,
dan tidak boleh di masa depan. Dalam prototype ini `is_simulation` wajib `true`; backend menolak
laporan yang mencoba mengklaim data non-simulasi. Evidence bersifat opsional dan harus URL valid.

## Respons dan integrasi frontend

Respons list/create/update task memuat `history[]`. Detail task juga memuat `reports[]`.
Nama history pada JSON adalah `from`, `to`, dan `at`, sesuai schema Zod frontend. Semua UUID
berupa string dan semua timestamp bertimezone.

REST adapter frontend perlu mengganti header sementara `X-Actor-Id` dengan Bearer token sesuai
tampilan role demo. Mock/localStorage tetap boleh dipakai saat backend tidak aktif, tetapi data
REST berasal dari PostgreSQL dan bertahan setelah reload. Tampilkan label **SIMULASI** dari
`is_simulation`; hotspot tetap anomali panas sampai hasil lapangan ditinjau.

Database memakai constraint status/role/result, indeks foreign key dan filter, row lock saat
mutasi, transaksi singkat, serta RLS pada tabel workflow. Aplikasi backend mengakses database
melalui role server; akses langsung role Data API `anon`/`authenticated` dicabut oleh migration.

## Verifikasi

```bash
cd backend
.venv/bin/ruff check app tests
.venv/bin/pytest
```

Integration test workflow memerlukan database PostGIS terisolasi dengan nama berakhiran `_test`:

```bash
TEST_DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/gambutops_test \
  .venv/bin/pytest tests/test_tasks.py
```

Tes tersebut menjalankan migration ulang dan menghapus tabel domain pada database target. Jangan
arahkan ke database aplikasi atau produksi.
