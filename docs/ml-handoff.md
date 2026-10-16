# BE-07/08 — eksperimen ML GWT +1 hari

Peningkatan 16 Oktober 2026: tersedia inferensi dari tujuh pengukuran manual terkini,
skenario DEMO, dan rekomendasi pencegahan dari GWT + hujan opsional pada endpoint baru
`POST /api/v1/prevention/assess`. Lihat [kontrak dan panduan demo](field-forecast-prevention.md).
Pembatasan historis di bawah berlaku pada endpoint lama `/ml/forecast`.

Pipeline melatih model terpisah untuk BRG6 dan BRG3 dari `mmc1.xlsx`. Targetnya perubahan
GWT satu hari dari nilai terakhir; hasil model ditambahkan kembali ke lag 1. Fitur hanya memakai
tujuh tanggal kalender sebelum target: lag 1/3/7, rolling mean 3/7 yang sudah digeser, dan
perubahan 1/3/7. Missing, konflik duplikat, atau tanggal tanpa observasi memutus sequence.

Training menggunakan split kronologis 70/15/15. `min_samples_leaf` dipilih pada validation;
model final di-fit pada train+validation dan dievaluasi satu kali pada test. Persistence
`GWT(t+1)=GWT(t)` dibandingkan pada tanggal test yang sama.

```bash
cd backend
.venv/bin/python -m app.cli train-gwt dataset/mmc1.xlsx
```

Perintah menghasilkan manifest `var/ml/{station}.metrics.json` dan artifact `.joblib` ber-versi.
Folder dapat diganti melalui `ML_ARTIFACT_DIR`. Jalankan training sebagai release step
sebelum memulai API; jika artifact belum ada, metrics mengembalikan `NOT_AVAILABLE`.

## Kontrak API

- `GET /api/v1/ml/metrics` mengembalikan `{status:"AVAILABLE", experiments:[...]}` atau
  `{status:"NOT_AVAILABLE", reason}`. Prediction points memakai meter; MAE/RMSE memakai cm.
- `POST /api/v1/ml/forecast` menerima `{"station_id":"<uuid>","date":"YYYY-MM-DD"}`.
  `date` adalah tanggal input terakhir dan output berlaku untuk hari berikutnya.
- Forecast hanya memakai observasi `HISTORICAL_REPLAY` dengan tujuh hari valid berurutan.
  Input kurang, stasiun/model tidak tersedia, dan ID invalid menghasilkan envelope `REJECTED`.
- `release_gate` selalu disertakan. Model `EXPERIMENT_ONLY` tetap dapat divisualisasikan sebagai
  eksperimen historis, tetapi tidak boleh menjadi input decision engine.

Hasil dataset saat ini:

| Stasiun | Test | Model MAE/RMSE | Baseline MAE/RMSE | Gate |
| --- | ---: | ---: | ---: | --- |
| BRG6 | 81 hari | 2,843 / 4,191 cm | 1,705 / 3,094 cm | `EXPERIMENT_ONLY` |
| BRG3 | 75 hari | 2,444 / 3,832 cm | 1,339 / 3,329 cm | `EXPERIMENT_ONLY` |

Data dan hasil berlabel eksperimen historis 2018–2019. Endpoint tidak menghasilkan klaim kondisi
2026 dan tidak mengubah data Current Monitoring.

## Verifikasi runtime

Pada 15 Oktober 2026 smoke API lokal dengan database Supabase lulus untuk kedua model:
BRG3 target 2019-06-14 dan BRG6 target 2019-07-19. Prediksi, baseline, versi, gate dan tanggal
cocok dengan artifact evaluasi. Forecast BRG6 dengan input 2026-10-15 ditolak karena tidak
memiliki tujuh hari GWT terkini. Workflow smoke di-rollback. Artifact masih berada pada host
lokal; sertakan pada host deployment dan ulangi verifikasi di sana.
Lihat [prosedur QA](backend-qa.md).
