# BE-05 — kontrak priorities

`GET /api/v1/priorities?mode=HISTORICAL_REPLAY&as_of=2019-09-15T23:59:59Z`

Query wajib: `mode` (`HISTORICAL_REPLAY` / `CURRENT_MONITORING`) dan timestamp
`as_of` dengan zona waktu. Timestamp masa depan, tanggal tanpa timezone, dan area
tidak dikenal menghasilkan 422. Semua cutoff dinormalisasi UTC. Opsional
`area_id=batanghari` / `kubu-raya`; tanpa filter respons berisi dua area.

Respons berupa array assessment: `id` UUID, `area_id`, `mode`, `as_of`,
`decision` (REVIEW / MONITOR / ESCALATE / INSUFFICIENT_DATA), `priority`,
`reason_codes`, `missing_inputs`, `explanation`, `recommended_actions`,
`rule_version=inspection-rules-1.0`, `scientific_status=heuristic_not_validated`,
dan `input_snapshot` berupa objek JSON. OpenAPI `/openapi.json` adalah acuan.

Frontend harus mengubah tanggal pilihan menjadi cutoff UTC eksplisit yang tidak
di masa depan, memetakan objek snapshot ke tampilan indikator, dan memakai
`area_id` sebagai target. Ini dua area demo, bukan enam blok mock frontend.
Jangan menampilkan prioritas sebagai probabilitas kebakaran atau klaim aman.
Tombol pembuatan tugas masih menunggu BE-06; endpoint tasks tetap 501.

## Aturan versi 1.0

- Jendela hotspot: tujuh tanggal kalender UTC sampai timestamp cutoff.
- Hotspot yang belum memiliki laporan dengan status task VERIFIED pada cutoff
  menghasilkan REVIEW/MEDIUM; kejadian pada >=3 tanggal berbeda menjadi HIGH.
- Kejadian berulang dengan laporan ACTIVE_FIRE_FOUND/BURN_SCAR_FOUND terverifikasi
  menghasilkan ESCALATE/HIGH. Pengulangan adalah **per area**, bukan bukti bahwa
  hotspot tersebut berasal dari satu kebakaran.
- Tren GWT membutuhkan tujuh hari berurutan VALID, tanpa gap, dan akhir seri
  maksimal dua hari sebelum tanggal cutoff. Delta akhir-awal negatif menghasilkan
  MONITOR/MEDIUM; lainnya MONITOR/LOW jika tidak ada hotspot menunggu pemeriksaan.
- Tidak ada bukti hotspot atau tren memadai menghasilkan INSUFFICIENT_DATA.
  Tidak ada hotspot tidak sama dengan cakupan satelit lengkap atau tidak ada api.
- CHIRPS belum tersedia dan selalu tercatat missing. Laporan tidak tersedia juga
  tercatat missing; tidak menghalangi REVIEW berbasis bukti hotspot positif.

Angka jendela/freshness/pengulangan adalah konfigurasi prototype di
`app/data/priority_rules.py`, bukan ambang ilmiah tervalidasi. GWT hanya konteks
regional, **tidak menaikkan** prioritas hotspot dengan asumsi kedekatan stasiun.
Bounding box merupakan perkiraan DEMO, bukan batas administratif resmi.

## Audit dan penyimpanan

Endpoint mengevaluasi data DB lalu menyimpan snapshot dalam satu transaksi.
Identitas assessment diturunkan dari hash input, mode, cutoff, area, dan versi
aturan; INSERT ON CONFLICT menjaga request identik tidak membuat baris duplikat.
Input berbeda menghasilkan snapshot baru, bukan menimpa riwayat lama. Database
menggunakan tabel assessment yang sudah ada; tidak membutuhkan migrasi baru.

Snapshot mencatat sumber SHA-256 dan ID observasi, waktu, kualitas, tren, hotspot,
laporan pendukung, bbox, serta konfigurasi aturan. Data observasi setelah cutoff
tidak dibaca. Historis adalah replay menurut waktu observasi, bukan simulasi
"data diketahui pada 2019": dataset historis memang diimpor kemudian.
GWT hanya memiliki tanggal, bukan jam pengukuran: cutoff GWT bergranularitas
tanggal UTC, sedangkan hotspot/laporan menggunakan timestamp tepat.
Untuk NRT, `last_synced_at <= as_of` diwajibkan agar koreksi yang diambil setelah
cutoff tidak bocor ke penilaian sebelumnya. NRT bukan arsip bitemporal: record
yang sudah diperbarui dapat tidak tersedia untuk cutoff lama.

Status mutable hotspot/task saat ini tidak digunakan. Status task direkonstruksi
dari history sebelum cutoff; laporan harus sudah dibuat dan diamati sebelum
cutoff. Laporan simulasi diabaikan untuk CURRENT_MONITORING. Pada historical
replay, simulasi ditandai eksplisit dalam snapshot dan bukan verifikasi nyata.

Integrasi tugas/laporan end-to-end serta konsumsi frontend belum selesai.
