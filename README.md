# Olah Data Hidrologi BBWS Serayu Opak

**Versi saat ini: `1.6.0.1` — Pre-QC**  
Aplikasi web terpadu untuk mengambil, menormalisasi, mengolah, memantau, memvisualisasikan, dan mengekspor data hidrologi dari beberapa sistem telemetry/logger dalam satu antarmuka.

Vendor/sumber yang sudah terintegrasi:

- **Beacon / Monitoring4System**
- **Tatonas**
- **Higertech**
- **Dashindo / Scadash**
- **Upload Excel/CSV manual**

> Status `1.x.x` berarti aplikasi masih berada pada tahap pengembangan dan validasi **sebelum QC formal**. Hasil pengolahan tetap perlu diverifikasi sebelum digunakan sebagai data resmi.

---

## Skema Versi

Repository sekarang memakai penomoran yang lebih konsisten:

```text
0.x.x      prototipe / fondasi awal
1.x.x      pengembangan terpadu sebelum QC
2.x.x      disiapkan untuk fase setelah QC / rilis operasional

x.y.z      versi fitur normal
x.y.z.n    hotfix kecil tanpa perubahan fitur utama
```

Contoh versi saat ini:

```text
1.6.0      optimasi Pengolahan Beacon, Higertech, Dashindo
1.6.0.1    hotfix timestamp Beacon BBWS
```

Nomor lama seperti `V13`, `V24`, atau `V26.1` dipertahankan hanya pada tabel riwayat sebagai referensi terhadap arsip pengembangan lama.

---

## Daftar Isi

- [Fitur Utama](#fitur-utama)
- [Arsitektur Aplikasi](#arsitektur-aplikasi)
- [Pengolahan Data](#pengolahan-data)
- [Monitoring Telemetri](#monitoring-telemetri)
- [Integrasi Vendor](#integrasi-vendor)
- [Aturan Pengolahan Data](#aturan-pengolahan-data)
- [UI Bersama](#ui-bersama)
- [Menjalankan Secara Lokal](#menjalankan-secara-lokal)
- [Environment Variables](#environment-variables)
- [Deploy GitHub dan Vercel](#deploy-github-dan-vercel)
- [Struktur Repository](#struktur-repository)
- [Keamanan dan Operasional](#keamanan-dan-operasional)
- [Riwayat Versi](#riwayat-versi)
- [Rencana Pengembangan](#rencana-pengembangan)

---

# Fitur Utama

## Pengolahan

- Pengolahan **Curah Hujan** dan **Tinggi Muka Air**.
- Sumber **Server Telemetri** atau **Upload File Manual**.
- Pilihan periode:
  - Harian
  - Bulanan
  - Tahunan
  - Rentang tanggal
- Normalisasi format timestamp dan nama parameter antar-vendor.
- Data sumber tetap dipertahankan pada resolusi yang diperlukan sebelum diagregasi oleh aplikasi.
- Pengolahan menjadi format jam-jaman.
- Hari hidrologis Curah Hujan **07:00–06:59**.
- Faktor koreksi opsional.
- Grafik time series.
- Ringkasan nilai terakhir, tertinggi, terendah, akumulasi/rerata sesuai parameter.
- Tabel hasil pengolahan.
- Ekspor Excel `.xlsx`.
- Cache sesi untuk pilihan dan hasil Pengolahan.

## Monitoring

- Monitoring terpadu lintas vendor.
- Filter multi-select **Logger** agar vendor yang tidak diperlukan sama sekali tidak di-request.
- Kategori utama:
  - Curah Hujan
  - Tinggi Muka Air
- Tampilan jam-jaman atau harian.
- Orientasi horizontal atau vertikal.
- Rentang 3, 7, 14, 30 hari dan rentang tanggal sesuai UI yang tersedia.
- Status ketersediaan data per pos.
- Ringkasan tertinggi khusus Curah Hujan.
- Klasifikasi Curah Hujan.
- Ekspor Excel Monitoring.
- Diagnostik performa di DevTools untuk debugging local.
- Fetch antar-vendor berjalan paralel sehingga waktu total mendekati vendor paling lambat, bukan penjumlahan seluruh vendor.

---

# Arsitektur Aplikasi

Backend menggunakan **Flask** dan dipisahkan menjadi route, adapter vendor, serta service Monitoring.

```text
Browser
   │
   ├── Pengolahan
   │      ↓
   │   /api/... telemetry
   │      ↓
   │   adapter vendor
   │      ↓
   │   raw normalized rows
   │      ↓
   │   agregasi frontend
   │
   └── Monitoring
          ↓
       /api/monitoring/...
          ↓
       vendor fetch paralel
          ↓
       normalisasi + agregasi Monitoring
          ↓
       tabel/status/grafik
```

Prinsip utama proyek:

1. UI pengguna tidak bergantung pada UI website vendor.
2. Credential vendor hanya berada di backend.
3. Setiap vendor memiliki adapter sendiri.
4. Setelah raw data dinormalisasi, pipeline aplikasi dibuat seragam.
5. Fast path selalu memiliki fallback bila upstream vendor berubah atau gagal.
6. Optimasi Monitoring tidak boleh mengorbankan ketepatan Pengolahan.

---

# Pengolahan Data

Alur umum:

```text
Pilih Logger
    ↓
Pilih Kategori Data
    ↓
Pilih Sumber Data
    ↓
Pilih Pos
    ↓
Pilih Parameter
    ↓
Pilih Periode
    ↓
Ambil / parse raw data
    ↓
Normalisasi timestamp + nilai
    ↓
Agregasi jam-jaman
    ↓
Faktor koreksi opsional
    ↓
Grafik + tabel + ringkasan
    ↓
Ekspor Excel
```

Untuk Server Telemetri, cara pengambilan raw berbeda pada tiap vendor, tetapi hasilnya dikembalikan ke format yang konsisten sebelum diproses lebih lanjut.

---

# Monitoring Telemetri

Monitoring dirancang untuk membaca banyak pos sekaligus. Karena bebannya jauh lebih berat daripada Pengolahan satu pos, jalur Monitoring memakai endpoint dan strategi yang lebih sesuai untuk dashboard.

## Status Data

Status dihitung dari view jam-jaman:

| Status | Kondisi |
|---|---|
| **Berhasil** | gap kosong kontinyu terpanjang per hari `≤ 6 jam` |
| **Peringatan** | gap kosong kontinyu `> 6` sampai `12 jam` |
| **Terputus** | gap kosong kontinyu `> 12 jam` |
| **Gagal** | request/parameter vendor gagal diambil |

Catatan:

- Nilai `0.0` dianggap data valid.
- Curah Hujan memakai hari hidrologis 07:00–06:59.
- Tinggi Muka Air memakai hari kalender.
- Untuk periode berjalan, hanya slot sampai waktu efektif request yang diperiksa.

## Diagnostik Performa

Response Monitoring membawa informasi performa dan browser mencetak detail ke DevTools, antara lain:

```text
TOTAL request
Metadata seluruh vendor
Fase fetch vendor paralel
Beacon total
Beacon bulk /monitoring
Beacon supplement exact
Higertech
Tatonas
Dashindo
Agregasi + bentuk tabel
```

Detail Beacon juga dapat menunjukkan ukuran chunk, jumlah worker, token cache, dan timing supplement. Diagnostik ini ditujukan untuk debugging dan tidak ditampilkan sebagai waktu proses pada UI utama.

---

# Integrasi Vendor

## Ringkasan Jalur Saat Ini

| Vendor | Pengolahan | Monitoring | Fallback utama |
|---|---|---|---|
| **Beacon BBWS** | `set_sensordash → token → data_chunk` | bulk `/monitoring` + exact supplement | mekanisme token lama |
| **Beacon PSDA** | halaman historis `/analisa/data/<token>` | bulk bila tersedia + supplement HTML | HTML historis |
| **Tatonas** | API historis vendor | API historis dengan fast-fail/deadline | mekanisme request existing |
| **Higertech** | `GetChartDataAwlrArr`, `minute`, raw 5-menit | endpoint chart `minute`, lalu agregasi sendiri | XLSX bulanan |
| **Dashindo** | `get_n_data`, raw menit/sub-menit | `get_n_data_hourly` | `downloadcsv` |

## 1. Beacon / Monitoring4System

### Credential

```env
BEACON_USERNAME=
BEACON_PASSWORD=
```

### Pengolahan Beacon BBWS

Fast path saat ini:

```text
set_sensordash
    ↓
ambil token dari Location redirect
    ↓
data_chunk
    ↓
parse payload.data [epoch_ms, value]
    ↓
raw normalized rows
```

Ketentuan penting:

- Maksimal request historis Beacon tetap **25 hari per chunk**.
- Chunk satu pos dapat dijalankan paralel secara konservatif.
- Token sensor dapat di-cache singkat pada warm instance.
- Bila fast selector gagal, backend kembali ke mekanisme token lama.
- Parser canonical `payload.data` mencegah timestamp numerik berubah menjadi tanggal 1899/1900.

### Pengolahan Beacon PSDA

Aset PSDA/non-BBWS tidak menggunakan `data_chunk` karena upstream tidak mendukung jalur tersebut. Backend tetap mengambil halaman historis token dan mem-parsing tabel data.

Untuk rentang panjang, aplikasi dapat membagi pekerjaan menjadi bagian yang lebih kecil sehingga tidak bergantung pada satu render halaman vendor yang sangat berat.

### Monitoring Beacon

Monitoring memakai strategi:

```text
bulk /monitoring
    ↓
identifikasi pos yang sudah ter-cover
    ↓
exact supplement hanya untuk sensor yang belum ter-cover
```

Kategori native yang dipakai antara lain:

- AWLR untuk Tinggi Muka Air.
- ARR untuk Curah Hujan.

Rentang panjang menggunakan bulk chunk dan session Beacon terisolasi karena `set_kategori` dan `set_tanggal` bersifat stateful per session.

Supplement BBWS memakai satu global `data_chunk` pool agar pekerjaan beberapa pos/rentang panjang lebih seimbang.

---

## 2. Tatonas

### Credential

```env
TATONAS_USERNAME=
TATONAS_PASSWORD=
```

Sumber utama historis menggunakan endpoint Tatonas pada plant BBWS Serayu Opak.

Pengolahan mempertahankan mekanisme historis yang sudah ada, termasuk pemecahan rentang dan retry sesuai adapter.

Monitoring memakai profil berbeda karena dashboard tidak boleh tertahan terlalu lama oleh satu vendor:

- timeout lebih pendek;
- retry default minimum;
- deadline total vendor;
- pos yang tidak selesai dapat ditandai gagal sementara vendor lain tetap ditampilkan.

Hal ini penting ketika server Tatonas sedang lambat atau tidak stabil.

---

## 3. Higertech

### Credential

```env
HIGERTECH_USERNAME=
HIGERTECH_PASSWORD=
```

### Pengolahan

Untuk rentang sampai default **62 hari**, jalur utama menggunakan:

```text
POST /Station/GetChartDataAwlrArr
selectedTime=minute
filterDate=YYYY-MM-DD
```

Satu request mengambil raw native **5-menit** untuk satu hari. Beberapa hari dapat dipanggil paralel, kemudian raw data digabung kronologis dan baru diagregasi oleh pipeline aplikasi.

Field utama yang dipakai sesuai parameter antara lain:

- `waterLevel`
- `rainfall`
- timestamp `readingAt`

Jika chart JSON gagal atau rentang melewati batas fast path, backend fallback ke export XLSX bulanan 5-menit.

### Monitoring

Monitoring memakai endpoint chart yang sama dengan resolusi `minute`, kemudian:

- TMA jam-jaman = agregasi titik 5-menit dalam jam.
- Curah Hujan jam-jaman = agregasi titik 5-menit dalam jam.
- Curah Hujan harian tetap mengikuti 07:00–06:59.

Raw per hari memiliki cache warm-instance untuk mengurangi request berulang.

---

## 4. Dashindo / Scadash

### Credential

```env
DASHINDO_USERNAME=
DASHINDO_PASSWORD=
```

Backend berkomunikasi dengan Engine.IO v4 / Socket.IO vendor.

### Pengolahan

Pengolahan memakai event raw:

```text
get_n_data(device, field, [tss, tse])
    ↓
n_data {times, values}
```

Data tetap **raw menit/sub-menit**, bukan hourly. Agregasi dilakukan sendiri oleh aplikasi.

Jalur ini lebih ringan daripada:

```text
downloadcsv
→ Base64
→ decode
→ parse CSV
```

Jika direct raw gagal, `downloadcsv` tetap tersedia sebagai fallback.

### Monitoring

Monitoring memakai:

```text
persistent Engine.IO
→ get_n_data_hourly
→ n_data
```

Koneksi persisten dipakai per worker untuk mengurangi handshake/autentikasi berulang. CSV dipakai sebagai fallback bila hourly direct gagal.

---

# Aturan Pengolahan Data

## Curah Hujan

Hari hidrologis:

```text
07:00 hari H
sampai
06:59 hari H+1
```

Contoh 1 Januari 2026:

```text
2026-01-01 07:00
sampai
2026-01-02 06:59
```

Nilai Curah Hujan pada UI dan export mengikuti format angka yang ditetapkan aplikasi. Monitoring juga menyediakan klasifikasi intensitas/harian.

## Tinggi Muka Air

Tinggi Muka Air ditampilkan dan diekspor dengan **dua angka desimal** (`0.00`). Grafik dan tooltip mengikuti format dua desimal.

## Faktor Koreksi

Faktor koreksi bersifat opsional dan diterapkan pada pipeline Pengolahan setelah raw data berhasil dinormalisasi sesuai aturan parameter yang tersedia pada UI.

## Periode

Mode yang tersedia:

```text
Harian
Bulanan
Tahunan
Rentang Tanggal
```

Tanggal output menggunakan format `yyyy-mm-dd`. Untuk periode bulanan/tahunan, tabel dan Excel mempertahankan tanggal yang termasuk dalam periode sampai batas tanggal yang valid/tersedia sesuai aturan aplikasi.

---

# UI Bersama

Pengolahan dan Monitoring memakai komponen Jinja reusable pada:

```text
templates/components/ui.html
```

dan styling komponen pada:

```text
static/css/ui-components.css
```

Komponen utama:

- `three_column_layout(...)`
- `card(...)`
- `card_header(...)`
- `field(...)`
- `stat_card(...)`
- `status_card(...)`
- `summary_table(...)`
- `info_item(...)`

`static/css/app.css` menyediakan semantic theme tokens light/dark, sedangkan `processing.css` dan `monitoring.css` menangani kebutuhan spesifik halaman.

Layout desktop menggunakan tiga kolom fluid dengan breakpoint bersama dan menjadi satu kolom pada mobile.

---

# Menjalankan Secara Lokal

## Persyaratan

- Python **3.11+** disarankan.
- Windows dapat memakai `run.bat`.
- Koneksi internet diperlukan untuk akses vendor.

## Cara Cepat Windows

1. Extract repository.
2. Salin `.env.example` menjadi `.env`.
3. Isi credential yang dibutuhkan.
4. Jalankan:

```text
run.bat
```

5. Buka:

```text
http://127.0.0.1:5050
```

`run.bat` akan mencari Python, memuat `.env`, memastikan dependency terpasang, lalu menjalankan Flask.

## Cara Manual

```bash
python -m venv .venv
```

Windows:

```bash
.venv\Scripts\activate
pip install -r requirements.txt
python api/app.py
```

Aplikasi berjalan pada:

```text
http://127.0.0.1:5050
```

---

# Environment Variables

Gunakan `.env.example` sebagai template local. Jangan commit `.env` asli.

## Akses Aplikasi

```env
APP_PASSWORDS=password_admin,password_operator,password_lapangan
SESSION_SECRET=ganti_dengan_string_panjang_acak
```

`APP_PASSWORD` lama masih dapat dibaca sebagai fallback kompatibilitas, tetapi konfigurasi baru sebaiknya memakai `APP_PASSWORDS`.

## Beacon

```env
BEACON_USERNAME=
BEACON_PASSWORD=
BEACON_USERNAME_FIELD=username
BEACON_PASSWORD_FIELD=password
BBWS_BASE_URL=https://bbwsso.monitoring4system.com
BBWS_TIMEOUT=45
PARAMETER_CACHE_TTL=21600
BEACON_CHUNK_DAYS=25
BEACON_PARALLEL_WORKERS=3
BEACON_PROCESS_TOKEN_TTL=300
```

Monitoring Beacon opsional:

```env
MONITORING_BEACON_BULK_DAYS=7
MONITORING_BEACON_BULK_WORKERS=3
MONITORING_BEACON_BULK_LONG_THRESHOLD=15
MONITORING_BEACON_BULK_LONG_DAYS=8
MONITORING_BEACON_BULK_LONG_WORKERS=4
MONITORING_BEACON_WORKERS=4
MONITORING_BEACON_CHUNK_WORKERS=6
MONITORING_BEACON_METADATA_TTL=21600
MONITORING_BEACON_SESSION_TTL=900
MONITORING_BEACON_TOKEN_TTL=300
```

## Tatonas

```env
TATONAS_USERNAME=
TATONAS_PASSWORD=
TATONAS_CHUNK_MONTHS=3
TATONAS_PARALLEL_WORKERS=2
```

Monitoring Tatonas opsional:

```env
MONITORING_TATONAS_WORKERS=4
MONITORING_TATONAS_CONNECT_TIMEOUT=4
MONITORING_TATONAS_TIMEOUT=12
MONITORING_TATONAS_RETRIES=0
MONITORING_TATONAS_VENDOR_DEADLINE=15
```

## Higertech

```env
HIGERTECH_USERNAME=
HIGERTECH_PASSWORD=
HIGERTECH_BASE_URL=https://bbwsserayuopak.higertech.com
HIGERTECH_CHART_DAY_WORKERS=8
HIGERTECH_CHART_TIMEOUT=8
HIGERTECH_CHART_MAX_DAYS=62
HIGERTECH_CHART_CACHE_TTL=21600
HIGERTECH_CHART_TODAY_CACHE_TTL=60
HIGERTECH_CHART_CACHE_MAX=256
HIGERTECH_PARALLEL_WORKERS=3
HIGERTECH_EXPORT_CACHE_TTL=900
HIGERTECH_EXPORT_CACHE_MAX=12
HIGERTECH_CHUNK_MONTHS=1
HIGERTECH_EXPORT_TIMEOUT=120
```

Monitoring Higertech opsional:

```env
MONITORING_HIGERTECH_DAY_WORKERS=4
MONITORING_HIGERTECH_TIMEOUT=8
MONITORING_HIGERTECH_DAY_CACHE_TTL=600
MONITORING_HIGERTECH_TODAY_CACHE_TTL=60
```

## Dashindo

```env
DASHINDO_USERNAME=
DASHINDO_PASSWORD=
DASHINDO_BASE_URL=http://202.180.30.82
DASHINDO_SOCKET_URL=http://202.180.30.82:8000
DASHINDO_WAIT_TIMEOUT=45
DASHINDO_PARALLEL_WORKERS=3
DASHINDO_CHUNK_MONTHS=3
DASHINDO_DIRECT_RAW_ENABLED=1
```

Monitoring Dashindo opsional:

```env
MONITORING_DASHINDO_WORKERS=6
MONITORING_DASHINDO_CONNECT_TIMEOUT=4
MONITORING_DASHINDO_READ_TIMEOUT=8
MONITORING_DASHINDO_EVENT_TIMEOUT=8
MONITORING_DASHINDO_VENDOR_DEADLINE=15
```

## Cache Monitoring

```env
MONITORING_CACHE_TTL=300
```

> Worker dapat dinaikkan saat debugging local, tetapi deployment production sebaiknya tetap mempertimbangkan kemampuan upstream vendor dan resource serverless.

---

# Deploy GitHub dan Vercel

## GitHub

Commit hanya source code dan file contoh konfigurasi. Jangan commit:

```text
.env
credential
cookie
session
HAR yang mengandung credential/token
file debug sensitif
```

## Vercel

Repository sudah memiliki `vercel.json`. Alur umum:

1. Push repository ke GitHub.
2. Import project ke Vercel.
3. Tambahkan Environment Variables.
4. Deploy.
5. Uji vendor satu per satu dengan periode pendek terlebih dahulu.
6. Setelah stabil, uji periode bulanan/rentang panjang.

### Catatan Serverless

- Cache memory dan `/tmp` pada Vercel bersifat **best effort** dan dapat hilang saat instance baru dibuat.
- Cold start dapat lebih lambat daripada warm instance.
- Request upstream yang lama tetap harus memiliki timeout/deadline internal sebelum platform memutus function.
- Dashindo menggunakan komunikasi Engine.IO/Socket.IO melalui backend; jalur Monitoring sudah dibuat persistent per worker untuk mengurangi overhead.

---

# Struktur Repository

```text
.
├── api/
│   ├── app.py
│   ├── core.py
│   ├── routes/
│   │   ├── auth.py
│   │   ├── telemetry.py
│   │   ├── monitoring.py
│   │   └── download.py
│   └── services/
│       └── monitoring.py
├── templates/
│   ├── components/
│   │   └── ui.html
│   ├── base.html
│   ├── index.html
│   └── monitoring.html
├── static/
│   ├── css/
│   │   ├── app.css
│   │   ├── ui-components.css
│   │   ├── processing.css
│   │   └── monitoring.css
│   └── js/
│       ├── common.js
│       ├── index.js
│       └── monitoring.js
├── data/
│   ├── station_aliases.json
│   ├── beacon/
│   ├── higertech/
│   ├── tatonas/
│   └── dashindo/
├── config.py
├── requirements.txt
├── run.bat
├── vercel.json
├── .env.example
└── README.md
```

Seluruh dokumentasi utama, UI, integrasi vendor, deployment, dan riwayat versi sekarang dipusatkan di **satu `README.md`**.

---

# Keamanan dan Operasional

## Credential

Credential seluruh vendor wajib berada di backend. Jangan menaruh credential asli pada:

- HTML
- JavaScript frontend
- README
- repository GitHub
- screenshot publik
- file contoh yang di-commit

## Cache

Cache digunakan untuk mengurangi request vendor berulang, antara lain:

- metadata pos/parameter;
- token Beacon tertentu;
- raw Higertech per hari;
- hasil Monitoring;
- cache sesi browser untuk pilihan/hasil tertentu.

Pada Vercel, cache runtime tidak boleh dianggap permanen.

## Validasi Data

Data telemetry dapat mengandung:

- gap;
- duplicate;
- perubahan interval;
- timestamp tidak kontinu;
- nilai kosong;
- gangguan komunikasi alat;
- perbedaan unit atau penamaan parameter antar-vendor.

Jumlah record yang berbeda dari perkiraan tidak selalu berarti parser gagal. Untuk penggunaan resmi, hasil tetap perlu dibandingkan dengan sumber dan prosedur QC.

## Periode Panjang

Aplikasi sengaja memecah beberapa request historis menjadi chunk agar lebih stabil daripada meminta seluruh periode dalam satu response vendor yang besar.

Contoh strategi:

```text
Beacon     maksimal 25 hari/chunk untuk data_chunk
Tatonas    chunk kalender sesuai konfigurasi
Higertech  raw 5-menit harian pada fast path
Dashindo   range raw melalui Engine.IO dengan fallback CSV
```

---

# Riwayat Versi

Penomoran di bawah adalah penomoran repository baru. Kolom **Legacy** menghubungkan versi baru dengan arsip/migration label lama agar riwayat debugging tetap dapat ditelusuri.

| Versi | Legacy | Ringkasan perubahan |
|---|---|---|
| **0.0.1** | awal | Versi pertama. Hanya dapat mengolah data dari file manual; belum ada Server Telemetri, Monitoring terpadu, atau integrasi vendor. |
| **0.1.0** | fase awal | Mulai menambahkan sumber Server Telemetri dan adapter vendor pertama, sementara upload manual tetap dipertahankan. |
| **0.2.0** | fase awal | Fondasi integrasi multi-vendor Beacon, Higertech, Tatonas, dan Dashindo serta normalisasi data ke pipeline Pengolahan yang sama. |
| **0.3.0** | fase awal | Perapihan UI Pengolahan, mode periode, grafik, tabel, Excel, metadata/cache, serta kesiapan local → GitHub/Vercel. |
| **1.0.0** | V6–V11 | Masuk lini **Pre-QC 1.x**. Backend dimodularisasi, multi-password, metadata/cache vendor, alias nama pos terpusat, cache sesi, Monitoring dasar, klasifikasi/status, dan konsistensi UI/format TMA dua desimal. |
| **1.1.0** | V13–V16 | Monitoring Beacon memakai **bulk + exact supplement**, diagnostik performa ditambahkan, Tatonas Monitoring mendapat fast-fail, dan filter multi-select Logger memungkinkan vendor yang tidak dipilih tidak di-request. |
| **1.2.0** | V17–V18 | Optimasi Monitoring periode pendek Beacon, UI Monitoring diringkas, cache session/login Beacon diperkuat, dan Tatonas mendapat **vendor deadline** agar tidak menahan vendor lain. |
| **1.2.1** | V20 | Eksperimen bulk+supplement paralel dari V19 dibatalkan karena lebih lambat. Kembali ke bulk lalu supplement dan menambahkan cache token Beacon supplement yang fail-safe. |
| **1.3.0** | V21 | Monitoring Dashindo memakai **persistent Engine.IO per worker**, sehingga handshake dan autentikasi tidak lagi diulang untuk setiap pos. |
| **1.3.1** | V22 | Monitoring Dashindo berpindah ke `get_n_data_hourly → n_data`; Base64/CSV hanya fallback. |
| **1.4.0** | V23 | Monitoring Higertech berpindah dari XLSX ke `GetChartDataAwlrArr` `selectedTime=minute`, tetap raw 5-menit lalu diagregasi sendiri. |
| **1.5.0** | V24 | Optimasi Beacon rentang panjang: bulk chunk adaptif, fast token `set_sensordash` tanpa render HTML, serta perbaikan scope timer metadata. |
| **1.5.1** | V25 | Supplement Beacon BBWS di-flatten ke satu global `data_chunk` pool; warning Lucide `calendar-month` diperbaiki menjadi ikon valid `calendar-days`. |
| **1.6.0** | V26 | Pengolahan ikut memakai fast raw path: Beacon BBWS `set_sensordash + data_chunk`, Higertech chart JSON raw 5-menit, dan Dashindo `get_n_data` raw menit/sub-menit. Semua tetap memiliki fallback. |
| **1.6.0.1** | V26.1 | **Hotfix kecil** parser timestamp Beacon BBWS: canonical `payload.data [epoch_ms, value]` dipakai agar tanggal tidak berubah menjadi 1899/1900. **Versi saat ini.** |

### Catatan Arsip Legacy

- Label lama tidak selalu membentuk release formal; sebagian merupakan iterasi eksperimen/debug.
- `V19` merupakan eksperimen parallel bulk + supplement dan **tidak dipertahankan** karena benchmark lebih lambat.
- Beberapa nomor legacy tidak memiliki file migration tersendiri. Riwayat baru di atas mengelompokkan perubahan berdasarkan milestone fitur, bukan sekadar nomor eksperimen.
- Mulai versi ini, riwayat perubahan baru sebaiknya langsung ditambahkan ke tabel ini dan tidak lagi membuat banyak file `MIGRATION_V*.md` terpisah.

---

# Rencana Pengembangan

Fokus berikutnya sebelum QC formal dapat mencakup:

- quality control missing/duplicate/outlier;
- validasi konsistensi timestamp dan unit antar-vendor;
- cache historis yang lebih permanen;
- optimasi periode panjang tanpa membebani server vendor;
- health check integrasi vendor;
- logging diagnostik terstruktur;
- penyimpanan dataset historis;
- auto-input Google Spreadsheet;
- integrasi sumber telemetry tambahan;
- pengujian QC terstruktur sebelum menaikkan major version dari `1.x.x`.

---

## Status Proyek

```text
Versi      : 1.6.0.1
Tahap       : Pre-QC
Backend     : Flask
Deployment  : Local / GitHub / Vercel
Vendor      : Beacon, Tatonas, Higertech, Dashindo
Input lain  : Excel/CSV manual
```

Arah pengembangan tetap menjaga satu prinsip: **vendor boleh berbeda, tetapi pengalaman pengguna dan pipeline data aplikasi harus tetap satu dan sederhana.**
