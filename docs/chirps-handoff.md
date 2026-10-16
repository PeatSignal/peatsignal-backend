# CHIRPS otomatis — 16 Oktober 2026

Form penilaian GWT pada `/experiments/ml` dan `/priorities` kini menawarkan
**Otomatis · CHIRPS v2 Final** sebagai sumber hujan. Tujuh tanggal hujan mengikuti
tujuh tanggal input GWT. Mode manual dan contoh DEMO tetap tersedia.

## Sumber dan cakupan

- Dataset: [CHIRPS v2 Daily / UCSB-CHG/CHIRPS/DAILY](https://developers.google.com/earth-engine/datasets/catalog/UCSB-CHG_CHIRPS_DAILY).
- Akses: [ClimateSERV API](https://climateserv.servirglobal.net/develop-api),
  dataset `0`, daily interval `0`, operasi mean `5`. Layanan ini dirujuk oleh
  [produsen UCSB/CHC](https://www.chc.ucsb.edu/node/245).
- Tidak membutuhkan kredensial Earth Engine. Cuplikan JavaScript dari katalog
  Google adalah contoh penggunaan di Earth Engine Code Editor, bukan endpoint aplikasi.
- Koordinat BRG3/BRG6 belum diketahui. Keduanya berada di Batanghari menurut dataset
  sumber. Hujan otomatis memakai **rata-rata piksel pada bbox DEMO Batanghari**
  `[102.9, -2.2, 104.0, -1.3]`, bukan estimasi tepat pada stasiun.
- Endpoint lookup juga mendukung bbox DEMO Kubu Raya `[108.9, -1.2, 110.0, 0.3]`.
  Bbox bukan batas administrasi resmi. Tanggal label sumber dipertahankan.

Unduhan raster global UCSB dan pembacaan subset lokal berhasil diuji tetapi lambat
di jaringan pengembangan. Jalur produksi memakai permintaan statistik regional
ClimateSERV, sehingga tidak mengunduh raster global dan tidak menambah dependency GIS.

## API dan provenance

`GET /api/v1/rainfall/chirps?area_id=batanghari&date_to=2019-09-15`

Mengembalikan tujuh tanggal sampai `date_to`, nilai mm/hari (nullable), dataset,
provider, bbox, cakupan regional, waktu pengambilan, job ID, URL hasil dan status:

- `PENDING`: job masih berjalan. Pengecekan berikut memakai job yang sama; UI mengecek
  kembali otomatis, tanpa mengirim ulang job untuk setiap polling.
- `AVAILABLE`: tujuh tanggal memiliki nilai valid.
- `PARTIAL`: hanya beberapa tanggal memiliki nilai valid.
- `NOT_AVAILABLE`: tidak ada tanggal dengan nilai valid pada hasil sumber.
- `ERROR`: sumber gagal/timeout/respons tidak sesuai kontrak.

Nilai `0` dipertahankan sebagai nol yang benar-benar berasal dari sumber.
Nilai NoData `-9999`, non-finite, atau tanggal hilang tetap `null`. Tidak ada pergeseran
tanggal, interpolasi, penggantian dengan periode terdahulu atau penyamaan data kosong
dengan tidak hujan. Agregasi tujuh hari/dry spell membutuhkan tujuh nilai valid.

`POST /api/v1/prevention/assess` menerima `rainfall_mode: "CHIRPS"` (default lama tetap
`MANUAL`). Pada mode CHIRPS server mengambil sumber sendiri dan **mengabaikan nilai
hujan yang dikirim browser**. Respons menyertakan `rainfall` beserta `readings` efektif
yang benar-benar dipakai mesin rekomendasi. JSON unduhan memakai input efektif tersebut.
Kolom hujan otomatis hanya-baca; beralih ke manual mengosongkan nilai CHIRPS.

Job dibatasi dua menit; setiap request dibatasi 25 detik. Hasil lengkap di-cache enam
jam, data sebagian/belum tersedia 15 menit, kegagalan satu menit. Cache memori maksimal
64 periode per proses. Tidak ada perubahan tabel database atau penyimpanan observasi.

## Batas penggunaan terkini

Default frontend sekarang `AUTO`: `GET /api/v1/rainfall/automatic` memilih Open-Meteo
untuk tanggal akhir dalam 14 hari terakhir, dan CHIRPS untuk periode lebih lama.
Pilihan CHIRPS Final eksplisit tetap tersedia. Tidak ada penggabungan dua sumber
secara diam-diam. Mode `AUTO` pada assessment mengambil ulang data di server.

Open-Meteo memakai `precipitation_sum` harian dalam mm, kalender UTC dan titik tengah
kotak DEMO Batanghari (103,45; −1,75), **bukan koordinat BRG3/BRG6**. Label sumber
menyatakan estimasi model cuaca pada titik acuan; bukan rata-rata wilayah maupun
pengukuran stasiun. Data hari ini berjenis `FORECAST` dan tidak dipakai pada agregasi
rekomendasi. Pilih tanggal akhir kemarin untuk tujuh hari yang telah selesai.
Kesalahan upstream menghasilkan nilai kosong, tidak pernah nol pengganti.

Uji langsung 16 Oktober 2026 berhasil menampilkan 7/7 nilai untuk 10–16 Oktober:
`5.9, 1, 2.2, 4.4, 0, 0, 0 mm`; nilai terakhir masih prakiraan. Browser desktop dan
320 px terverifikasi tanpa kesalahan JavaScript. Sembilan tes Open-Meteo mencakup
validasi tanggal/unit/lokasi, data hilang, cache, pemilihan sumber, serta pengecualian
prakiraan dari rekomendasi. Lihat [dokumentasi Open-Meteo](https://open-meteo.com/en/docs).

CHIRPS Final mempunyai jeda publikasi dan bukan prakiraan cuaca. Uji endpoint nyata
pada 16 Oktober 2026 untuk **10–16 Oktober 2026** menghasilkan `NOT_AVAILABLE`, 0/7 hari
tersedia. Ini bukan curah hujan nol. Pada keadaan ini rekomendasi tetap memakai GWT
dan menerangkan bahwa konteks hujan belum lengkap.

Penambahan hujan ini mendukung aturan pencegahan; **belum** menjadi fitur training
model Random Forest. Metrik akurasi ML yang terdahulu tidak berubah. Training dengan
hujan memerlukan dataset yang dipasangkan dan evaluasi kronologis baru.

## Verifikasi

- Pengambilan nyata Batanghari 9–15 September 2019: `AVAILABLE`, lima hari pertama
  `0 mm`, 14 September `0.9618392587 mm`, 15 September `3.4247212410 mm`.
- Nilai 15 September dibandingkan dengan ekstraksi raster resmi UCSB (396 piksel
  valid), menghasilkan sekitar `3.4247 mm`.
- Tes backend mencakup NoData, nilai nol, tanggal duplikat/di luar periode, dataset atau
  interval salah, respons gagal, cache, polling job yang sama dan pengabaian hujan browser.
- 70 tes data frontend, lint/typecheck, serta browser CHIRPS, penilaian manual/demo dan
  regresi ML lulus. Uji browser CHIRPS memakai fixture REST untuk kondisi parsial/readonly;
  pengambilan nyata diuji terpisah. Browser penilaian memakai backend/model lokal asli.
