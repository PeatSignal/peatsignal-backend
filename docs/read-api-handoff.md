# Handoff read API: frontend mengikuti backend

Keputusan: Pydantic/OpenAPI backend menjadi acuan bentuk JSON HTTP. Teman frontend memiliki
schema Zod respons API, pemetaan REST adapter, dan model UI. Priorities memiliki handoff
terpisah di [priorities-handoff.md](priorities-handoff.md). Tasks/reports, users dan ML
belum termasuk integrasi ini.

Pembaruan BE-04: Current Monitoring kini memiliki cache dari sync NASA nyata. Status/waktu
global tersedia melalui endpoint terpisah; lihat [firms-handoff.md](firms-handoff.md).
Angka dan contoh kosong di bawah adalah snapshot sebelum BE-04, bukan kondisi database terbaru.

## Database aplikasi yang diverifikasi

- Docker PostgreSQL 16/PostGIS 3.5: `127.0.0.1:5433`, database `gambutops`.
- Migration: `20261014_0002`.
- Delapan stasiun; 3.928 GWT unik: 3.534 VALID, 393 MISSING, satu DUPLICATE.
- 6.403 hotspot SNPP historis: 3.439 pada bbox Batanghari dan 2.964 pada bbox Kubu Raya.
- Periode sampel hotspot: 2019-08-17 sampai 2019-09-15, inklusif (UTC).
- Bbox Batanghari `102.9,-2.2,104,-1.3`; Kubu Raya `108.9,-1.2,110,0.3`.
  Keduanya batas perkiraan DEMO dari frontend, bukan batas administratif terverifikasi.
- Reimport GWT dan kedua sampel hotspot menambah nol observasi.

Hasil tersebut adalah database aplikasi lokal, berbeda dari database tes integrasi. Hotspot di
luar bbox/periode sampel dapat kosong karena belum diimport. Kosong bukan bukti tidak ada
anomali panas pada lokasi/periode lain. Current Monitoring kosong karena belum ada sync live.

## Acuan kontrak dan contoh nyata

Jalankan backend lalu baca `http://localhost:8000/openapi.json` atau `/docs`. Contoh bounded
payload nyata ada di [examples/read-api.json](examples/read-api.json). Setiap contoh mencatat
method, path/query, status HTTP, dan body yang benar-benar dihasilkan API/database.

UUID dan waktu import pada file adalah snapshot, bukan ID yang wajib sama pada setiap instalasi.
Untuk merekam ulang contoh dengan data demo sudah tersedia:

```bash
cd backend
.venv/bin/python scripts/capture_read_api_examples.py
```

Script membaca database yang dikonfigurasi, memeriksa kontrak/filter, dan menulis contoh JSON;
tidak menjalankan migration atau import. Dataset demo harus mengikuti periode/bbox di atas.
Gunakan `listStations()` untuk mengambil UUID lalu tampilkan `code` (misalnya BRG6) sebagai label.

## Pemetaan respons HTTP ke model UI

Validasi payload mentah terlebih dahulu dengan schema respons backend. Pemetaan kemudian
memenuhi interface `GambutOpsRepository`; komponen tetap memakai hook repository yang ada.

| Endpoint / field backend | Penyesuaian frontend |
| --- | --- |
| Stations `id`, `code` | ID tetap UUID; tambahkan code untuk label, jangan mengganti ID dengan BRG6 |
| Stations `latitude`, `longitude` | Petakan ke `lat`/`lon` bila model UI mempertahankan nama tersebut |
| Stations `region`, `source` | Nullable; tampilkan metadata belum tersedia bila null |
| Stations `period_start`, `period_end` | Nullable ISO date dari min/max observasi di DB, termasuk baris missing/duplikat |
| GWT array | Bungkus menjadi `{station_id,mode,from,to,availability,notice,observations}` dari query dan hasil |
| GWT `observed_date` | Tanggal harian UI `observed_at` dalam YYYY-MM-DD |
| GWT `observed_at` | Representasi tanggal pada 00:00 UTC; jangan mengklaim jam pengukuran diketahui |
| GWT `source_id`, `source_sha256` | Pertahankan sebagai provenance tambahan; sumber tampilan dari `source` |
| Quality `DUPLICATE` | Boleh dipetakan ke `DUPLICATE_FLAGGED` pada model UI; makna konflik tetap dibedakan dari MISSING |
| Hotspot `acquired_at`, `sensor`, `frp` | Petakan ke `observed_at`, `instrument`, `frp_mw` |
| Hotspot `last_synced_at` | Timestamp import CSV lokal per item; belum merupakan waktu sync NASA live |
| Hotspot `daynight` | Belum tersedia dalam API: null, jangan menebak dari waktu pengamatan |
| Hotspot `area_id` | Nullable/hasil lookup bbox DEMO frontend; bukan relasi resmi dengan stasiun |
| Hotspot `is_simulation` | false untuk item nyata dari REST; fixture mock tetap SIMULASI |

Respons stations tetap array. Metadata periode/sumber bersifat aditif dan tidak mengubah UUID
atau nama koordinat. Jika terdapat beberapa sumber GWT, `source` berisi nama unik terurut,
dipisahkan `, `. Stasiun tanpa observasi memiliki periode/sumber null. Koordinat tanpa sumber
terverifikasi tetap null.

Untuk GWT, schema frontend harus menerima null pada MISSING dan DUPLICATE_FLAGGED/DUPLICATE.
Konflik duplikat tidak boleh diubah menjadi angka ataupun dihilangkan. AVAILABLE berarti ada
baris pada hasil query, bukan semua baris valid numerik. Hasil array kosong → NOT_AVAILABLE;
gunakan notice data kosong historis atau GWT terkini belum tersedia sesuai mode yang diminta.
Validasi mode setiap observasi terhadap query, urutkan menurut tanggal, dan pertahankan gap.

Default periode frontend berakhir 2019-09-15, sementara BRG3 berhenti pada 2019-08-27.
Tampilkan batas periode stasiun dan gap tersebut; jangan memperpanjang seri dengan nilai buatan.

## Filter, pagination dan batas metrik

`GET /api/v1/hotspots` menghasilkan `{items,total,limit,offset}`. Default limit 200, maksimum
1000. Query `from/to` berupa YYYY-MM-DD inklusif, `bbox=west,south,east,north`, `satellite`,
`source_product`, `mode`, `limit`, `offset`. Data terurut waktu akuisisi turun lalu UUID.
Produk sampel: `VIIRS_SNPP_HISTORICAL`; satellite `N`; instrument `VIIRS`.

Teman perlu memperluas query/collection repository agar metadata pagination tersimpan,
menambahkan limit/offset dan reset offset ketika filter/mode berubah. Mock mengikuti
interface repository yang sama. Jangan otomatis mengunduh seluruh halaman dataset besar.

Collection UI boleh menambah `mode` dari query setelah seluruh item lolos validasi mode.
Field waktu collection dapat memakai maksimum timestamp import item yang sedang tampil,
tetapi harus dilabeli “waktu import pada hasil halaman ini”; pada halaman kosong nilainya null.
Status sync global kini tersedia; lihat endpoint BE-04 di [firms-handoff.md](firms-handoff.md).

Dashboard total hotspot harus memakai `total`, bukan `items.length`. Jumlah UNVERIFIED yang
dihitung dari item satu halaman hanya berlaku untuk halaman itu; jangan dipresentasikan sebagai
statistik seluruh hasil. Priorities tersedia melalui BE-05; tasks masih menunggu BE-06.

## Kasus yang wajib diperiksa teman frontend

- Payload `stations` lolos schema, UUID BRG6/BRG3 dipakai pada query, koordinat tetap null.
- `groundwater_brg6`/`groundwater_brg3` mempertahankan tanggal, nilai, source ID dan hash.
- `groundwater_missing` dan `groundwater_duplicate` lolos validasi dengan null dan flag berbeda.
- Dua kasus GWT kosong dibungkus sebagai NOT_AVAILABLE dengan notice yang sesuai.
- `hotspots_page_1` dan `hotspots_page_2` memiliki total sama, offset berbeda, dan ID tak tumpang tindih.
- `hotspots_current_empty` serta `hotspots_bbox_empty` tidak diganti fixture/mock diam-diam.
- Input bbox/tanggal/UUID invalid menghasilkan 422 dan pesan validasi; stasiun UUID tak dikenal → 404.
- Payload dengan mode salah, tipe salah atau field wajib hilang tetap ditolak sebagai INVALID_PAYLOAD.
- Jalankan tes schema/REST adapter memakai fixture nyata ini setelah mapping dibuat, lalu
  lint/typecheck/build dan browser pada halaman monitoring yang diimplementasikan teman.

Integrasi frontend dinyatakan selesai setelah teman menjalankan pemeriksaan tersebut. Handoff
ini tidak menyatakan schema Zod atau halaman frontend telah disesuaikan.

## Seed ulang demo lokal

Jalankan migration terlebih dahulu pada database aplikasi yang disepakati, kemudian:

```bash
cd backend
.venv/bin/python -m app.cli import-gwt dataset/mmc1.xlsx --apply
.venv/bin/python -m app.cli import-hotspots dataset/viirs-snpp_2019_Indonesia.csv \
  --from 2019-08-17 --to 2019-09-15 --bbox '102.9,-2.2,104,-1.3' --apply
.venv/bin/python -m app.cli import-hotspots dataset/viirs-snpp_2019_Indonesia.csv \
  --from 2019-08-17 --to 2019-09-15 --bbox '108.9,-1.2,110,0.3' --apply
```

Jika sample database sudah memiliki data tambahan, total bisa lebih besar. Dataset raw dan
database yang berisi data penting tidak dihapus untuk mereproduksi handoff.

## Marker peta tanpa pagination daftar

`GET /api/v1/hotspots/map` menerima filter `from`, `to`, `mode`, `bbox`,
`satellite`, dan `source_product` yang sama dengan daftar. Respons `{mode, items}`
berisi seluruh marker sesuai filter tanpa limit/offset. Field marker: `id`,
`latitude`, `longitude`, `observed_at`, `frp_mw`, `verification_status`, `list_offset`.
Urutan dan `list_offset` mengikuti daftar (`acquired_at DESC, id`) agar klik peta
bisa membuka halaman daftar yang tepat. Respons besar dikompresi gzip.
