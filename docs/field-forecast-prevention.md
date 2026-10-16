# Prediksi dari pengukuran lapangan dan rekomendasi pencegahan

Pembaruan hujan otomatis: lihat [integrasi CHIRPS](chirps-handoff.md). Default form
manual memakai sumber otomatis: Open-Meteo untuk periode terkini dan CHIRPS untuk
periode historis. Sumber hujan manual tetap tersedia.

Fitur tersedia pada `/experiments/ml` dan `/priorities`, di panel **Penilaian dari
pengukuran lapangan**. Evaluasi historis tetap tersedia untuk menjelaskan asal model.

## Yang sudah bisa dilakukan

- Masukkan tujuh pengukuran harian GWT untuk BRG3/BRG6, dengan lokasi yang sama
  dengan stasiun model. Form memakai **cm**; API/model memakai **meter**.
- Tanggal input bisa terkini. Model terlatih 2018–2019 menerima tujuh nilai baru,
  tanpa menyalin nilai historis ke tanggal sekarang. Target prediksi satu hari setelah
  pengukuran terakhir. Tanggal menggunakan kalender UTC.
- Curah hujan per hari opsional. Angka `0` berarti pengukuran nol; kosong berarti
  tidak diketahui. Total hujan/dry spell hanya dihitung jika ketujuh nilai tersedia.
- Pilih contoh kering, pulih, atau hujan tidak tersedia. Semua contoh berlabel
  **DEMO/SIMULASI**. Beralih ke manual menghapus nilai contoh dan catatan sumber.
- Lihat kandidat Random Forest, baseline persistence, grafik dan alasan rekomendasi.
  Ringkasan JSON dapat diunduh bersama seluruh input, sumber, versi model dan aturan.

Input dinilai saat itu saja: tidak disimpan sebagai observasi atau assessment wilayah,
tidak mengubah dashboard, dan tidak membuat tugas secara otomatis. Pengukuran manual
berlabel **belum diverifikasi**; demo tetap simulasi bahkan bila inferensi memakai
artifact model asli. GWT belum tersambung sensor; hujan dapat diambil otomatis.
Open-Meteo menggunakan titik acuan DEMO di tengah kotak Batanghari karena koordinat
stasiun belum tersedia. Ini estimasi model cuaca, bukan pengukuran stasiun. Nilai
hari ini berlabel prakiraan dan tidak masuk agregasi rekomendasi; gunakan periode
yang berakhir kemarin untuk tujuh hari yang telah selesai.

## Pemilihan prediksi dan batasan

Artifact model yang sudah ada digunakan kembali. Tidak ada klaim training ulang
atau perbaikan akurasi pada fitur ini. Baseline memakai nilai pengukuran terakhir.
Model dipilih sebagai pembanding utama hanya jika MAE **dan** RMSE historis lebih baik
daripada baseline. Kandidat model tetap diperlihatkan untuk transparansi.

Hasil dengan input terkini tetap **eksperimental**: belum ada validasi terukur pada
2026. MAE yang ditampilkan adalah galat pada test historis, bukan selang kepercayaan
atau jaminan galat pada data baru. Prediksi model tidak dipakai untuk menaikkan prioritas.
Model yang tidak tersedia menghasilkan baseline saja; mode mock tidak mengarang ML.

Tanggal duplikat, tanggal masa depan, urutan dengan gap, nilai non-finite, dan hujan
negatif ditolak. Input terakhir lebih dari dua hari lalu diberi `STALE`, tidak menghasilkan
prediksi terkini, dan prioritas menjadi `INSUFFICIENT_DATA`.

## Aturan pencegahan v1.0

Aturan berlaku pada **stasiun input**, tidak mengasumsikan kedekatan dengan hotspot.
Semua ambang berikut konfigurasi prototipe, bukan model probabilitas kebakaran.

| Kondisi dari pengukuran | Dampak |
| --- | --- |
| GWT terakhir ≤ −0,40 m | Indikator muka air rendah |
| GWT turun ≥ 5 cm dari awal ke akhir 7 tanggal | Indikator penurunan |
| Hujan total < 10 mm pada 7 hari lengkap | Indikator hujan minim |
| Muka air rendah + (penurunan atau hujan minim) | Prioritas tinggi untuk pemeriksaan |
| Salah satu indikator saja | Perlu dipantau |
| Tidak ada indikator pada data yang lengkap | Pemantauan rutin, bukan jaminan aman |

Rekomendasi meliputi pengukuran ulang, pemantauan harian, inspeksi kondisi tata air
bersama petugas, patroli saat kering dan melengkapi hujan. Setiap rekomendasi disertai
angka input serta alasan. Hujan yang banyak tidak menghapus indikator GWT rendah.

## API

`POST /api/v1/prevention/assess` tidak memerlukan koneksi database. Badan request:

```json
{
  "station_code": "BRG6",
  "source_kind": "MANUAL",
  "source_note": "Pengukuran dipwell BRG6 oleh tim lapangan",
  "readings": [
    {"date": "2026-10-10", "gwt_m": -0.32, "rainfall_mm": 0},
    {"date": "2026-10-11", "gwt_m": -0.35, "rainfall_mm": 0},
    {"date": "2026-10-12", "gwt_m": -0.39, "rainfall_mm": null},
    {"date": "2026-10-13", "gwt_m": -0.42, "rainfall_mm": 0},
    {"date": "2026-10-14", "gwt_m": -0.45, "rainfall_mm": 0},
    {"date": "2026-10-15", "gwt_m": -0.48, "rainfall_mm": 0},
    {"date": "2026-10-16", "gwt_m": -0.52, "rainfall_mm": 0}
  ]
}
```

Tanggal contoh harus diperbarui saat dipakai lagi. Respons menyertakan provenance,
freshness, kandidat/pembanding, rekomendasi, alasan, data belum lengkap dan batasan.
Kontrak endpoint historis `/ml/forecast` tidak berubah.

## Alur demonstrasi untuk juri

1. Buka Uji prediksi → **Contoh kering** → **Hitung prediksi & rekomendasi**.
2. Tunjukkan grafik input sintetis, kandidat ML, pilihan baseline, dan alasan prioritas tinggi.
3. Pilih **Contoh pulih**; bandingkan rekomendasi pemantauan rutin.
4. Pilih **Tanpa data hujan**; tunjukkan sistem tetap menilai GWT dan menyatakan kekurangan data.
5. Beralih ke manual: angka demo hilang. Masukkan pengukuran lapangan yang sebenarnya
   sebelum mengklaim hasil berdasarkan data lapangan. Unduh ringkasan sebagai bukti penilaian.

Pesan demo: *data historis melatih pola; input lapangan baru memberi konteks tanggal
sekarang; rekomendasi menjelaskan apa yang perlu diperiksa beserta buktinya*.

## Dasar dan langkah selanjutnya

Studi [Hooijer & Vernimmen (2026)](https://www.nature.com/articles/s41598-026-64641-2)
memodelkan muka air gambut menggunakan hujan satelit dan kalibrasi muka air lapangan.
Model tersebut ditujukan pada hutan gambut tertentu; hasilnya bukan pembenaran bahwa
model lokal ini otomatis berlaku lintas lokasi/kondisi drainase.

Peningkatan berikutnya: pengukuran GWT terkini yang terverifikasi, koordinat stasiun
yang benar, hujan historis yang dipasangkan dengan GWT, validasi kronologis dan validasi
periode baru. [Open-Meteo](https://open-meteo.com/en/docs) menyediakan data cuaca untuk
integrasi lanjutan; prakiraan, reanalisis dan pengukuran lapangan harus dibedakan.

## Verifikasi 16 Oktober 2026

- Suite backend lengkap lulus (4 tes integrasi bersifat opt-in dan dilewati).
- 13 tes khusus penilaian/forecast lapangan lulus, termasuk model asli dari artifact
  fixture, provenance, validasi input, freshness dan pemilihan baseline.
- 69 tes data frontend, typecheck, lint dan build produksi REST lulus.
- Tes browser penilaian memakai API/backend dan artifact model lokal asli: skenario
  kering/pulih, hujan hilang, ringkasan JSON, input manual dan lebar 320/375/768 px lulus.
- Regresi browser ML dengan respons REST terkontrol lulus.
- Screenshot panel desktop dan 320 px diperiksa. Tidak ada observasi database atau
  sinkronisasi NASA yang dibuat oleh penilaian ini.
