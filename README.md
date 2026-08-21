# Olah Data Hidrologi BBWS Serayu Opak

Aplikasi web untuk membantu pengambilan, normalisasi, pengolahan, visualisasi, dan ekspor data hidrologi dari beberapa sistem telemetry/logger BBWS Serayu Opak dalam satu antarmuka.

Repository ini menggabungkan integrasi:

- **Beacon / Monitoring4System**
- **Tatonas**
- **Higertech**
- **Dashindo / Scadash**
- **Upload Excel/CSV manual**

Pipeline UI/UX dan pemrosesan dibuat tetap seragam meskipun masing-masing vendor memiliki mekanisme login, format data, resolusi, dan endpoint yang berbeda.

> Aplikasi ini merupakan alat bantu pengolahan. Data hasil proses tetap perlu diverifikasi oleh operator/analis sebelum digunakan sebagai data resmi.

---

## Daftar Isi

- [Fitur Utama](#fitur-utama)
- [Jenis Data](#jenis-data)
- [Periode Pengolahan](#periode-pengolahan)
- [Alur Pemrosesan](#alur-pemrosesan)
- [Integrasi Vendor](#integrasi-vendor)
  - [Beacon](#1-beacon--monitoring4system)
  - [Tatonas](#2-tatonas)
  - [Higertech](#3-higertech)
  - [Dashindo](#4-dashindo--scadash)
- [Faktor Koreksi](#faktor-koreksi)
- [Menjalankan Secara Lokal](#menjalankan-secara-lokal)
- [Environment Variables](#environment-variables)
- [Deploy GitHub + Vercel](#deploy-github--vercel)
- [Struktur Repository](#struktur-repository)
- [Keamanan](#keamanan)
- [Catatan Operasional](#catatan-operasional)

---

## Fitur Utama

- Pengolahan **Curah Hujan** dan **Tinggi Muka Air**.
- Sumber data server dari Beacon, Tatonas, Higertech, dan Dashindo.
- Upload Excel/CSV manual sebagai alternatif sumber data.
- Periode:
  - Harian
  - Bulanan
  - Tahunan
  - Rentang tanggal
- Normalisasi variasi nama parameter.
- Pemrosesan data menjadi format jam-jaman.
- Hari hidrologis curah hujan **07:00–06:59**.
- Faktor koreksi opsional.
- Ringkasan data minimum, maksimum, dan data terakhir.
- Grafik time series.
- Preview hasil.
- Ekspor Excel `.xlsx`.
- Password akses fitur Server Telemetri.
- Backend Flask yang dapat dijalankan lokal maupun di Vercel.

---

## Jenis Data

### Curah Hujan

Parameter hujan dapat berasal dari beberapa istilah berbeda, misalnya:

- Curah Hujan
- Rainfall
- Precipitation
- Precipitation Intensity
- variasi nama lain dari masing-masing logger

Untuk parameter hujan utama, hari hidrologis menggunakan:

```text
07:00 hari berjalan
sampai
06:59 hari berikutnya
```

Contoh periode hidrologis 1 Januari 2026:

```text
01 Januari 2026 07:00
sampai
02 Januari 2026 06:59
```

### Tinggi Muka Air

Parameter dapat berasal dari istilah seperti:

- Tinggi Muka Air
- Water Level
- Water Stage
- Elevasi Muka Air
- nama parameter vendor lainnya

Data kemudian diteruskan ke pipeline pemrosesan utama untuk diringkas sesuai resolusi keluaran aplikasi.

### Parameter Observasi Lain

Pada logger tertentu, katalog server juga dapat mengekspos parameter tambahan seperti:

- Battery Logger
- Temperature Logger
- Humidity
- Tekanan Udara
- Radiasi
- UV
- Arah Angin
- Kecepatan Angin
- Pan Level
- parameter observasi lain yang tersedia dari sumber

---

## Periode Pengolahan

Aplikasi mendukung empat mode periode:

### Harian

Memilih satu tanggal.

### Bulanan

Memilih bulan dan tahun.

### Tahunan

Memilih satu tahun.

### Rentang Tanggal

Memilih tanggal awal dan tanggal akhir.

Komponen pemilih tanggal menggunakan tampilan yang disesuaikan dengan masing-masing mode agar pengalaman pengguna tetap konsisten.

---

## Alur Pemrosesan

Secara umum seluruh vendor masuk ke pipeline yang sama:

```text
Pilih Jenis Data
        ↓
Pilih Logger
        ↓
Pilih Sumber Data
(Server / Upload File)
        ↓
Pilih Pos
        ↓
Pilih Parameter
        ↓
Pilih Periode
        ↓
Ambil / Parse Raw Data
        ↓
Normalisasi Timestamp & Nilai
        ↓
Agregasi / Pemrosesan Jam-Jaman
        ↓
Faktor Koreksi (opsional)
        ↓
Ringkasan + Grafik + Preview
        ↓
Ekspor Excel
```

Perbedaan antar-vendor hanya berada pada **adapter sumber data**. Setelah data berhasil dinormalisasi, UI/UX dan proses pengolahan menggunakan pipeline utama yang sama.

---

# Integrasi Vendor

## 1. Beacon / Monitoring4System

Beacon merupakan salah satu sumber Server Telemetri utama.

### Konfigurasi

Environment Variables:

```text
BEACON_USERNAME
BEACON_PASSWORD
```

Opsional:

```text
BBWS_BASE_URL=https://bbwsso.monitoring4system.com
BEACON_USERNAME_FIELD=username
BEACON_PASSWORD_FIELD=password
BBWS_TIMEOUT=45
PARAMETER_CACHE_TTL=600
MAX_QUERY_DAYS=25
```

### Mekanisme

Backend melakukan autentikasi ke server Beacon menggunakan credential yang disimpan di backend, kemudian:

```text
Login
  ↓
Ambil katalog pos/logger
  ↓
Ambil parameter
  ↓
Request data historis
  ↓
Normalisasi
  ↓
Pipeline aplikasi
```

Credential **tidak dikirim ke frontend**.

### Pengambilan Historis

Untuk sumber yang menggunakan mekanisme chunking, konfigurasi utama adalah:

```text
MAX_QUERY_DAYS=25
```

Nilai ini menentukan ukuran rentang maksimum per request historis dan dapat diubah melalui Environment Variable tanpa mengedit source code.

---

## 2. Tatonas

Adapter Tatonas terintegrasi langsung ke backend tanpa membawa UI downloader lokal. UI/UX, pemrosesan jam-jaman, grafik, dan ekspor tetap menggunakan aplikasi utama.

### Konfigurasi

Nilai sumber saat ini:

```text
TATONAS_BASE_URL=https://tatonas.co.id
TATONAS_PLANT=028
```

Credential:

```text
TATONAS_USERNAME
TATONAS_PASSWORD
```

### Metadata Sensor

Metadata parameter diambil dari katalog plant-level:

```text
/admin/p/trs_local_mst_sensor_list2?plant=028
```

Backend mengikuti pola autentikasi Tatonas dengan:

- session login;
- CSRF token dari HTML;
- XSRF token dari cookie;
- metadata sensor yang kemudian di-cache.

Daftar parameter tidak bergantung pada tersedia/tidaknya data pada satu tanggal tertentu.

### Pos yang Teridentifikasi

| Logger | Pos | Jenis |
|---|---|---|
| 4101 | Penungkulan | Curah Hujan |
| 4102 | Kutoarjo | Curah Hujan |
| 4104 | Sempor | Curah Hujan |
| 4105 | Opak Bintaran | Tinggi Muka Air |
| 4106 | Sermo | Curah Hujan / Klimatologi |

### Profil Sensor

**Penungkulan**
- Rain
- Device

**Kutoarjo**
- Rain
- Device

**Sempor**
- Rain
- Device

**Opak Bintaran**
- Water
- Factory
- Device

**Sermo**
- katalog klimatologi yang tersedia pada logger, termasuk hujan dan parameter meteorologi lainnya.

### Parser Data

Parser memprioritaskan:

```text
data_table[].date_act
data_table[].sensor.<kd_sensor>.value
```

Struktur `data_graph` tetap didukung sebagai fallback kompatibilitas.

Alias parameter hujan seperti:

```text
rainfall
curahhujan
```

diperlakukan sebagai parameter hujan utama yang ekuivalen bila metadata dan payload menggunakan penamaan berbeda.

### TMA Opak Bintaran

Data TMA sumber Tatonas dipertahankan sesuai unit sumber pada adapter dan dikonversi oleh pipeline aplikasi agar tidak terjadi konversi ganda.

---

## 3. Higertech

Higertech diintegrasikan sebagai adapter Server tanpa mengubah UI/UX dan pipeline utama.

### Konfigurasi

```text
HIGERTECH_USERNAME
HIGERTECH_PASSWORD
```

Opsional:

```text
HIGERTECH_BASE_URL=https://bbwsserayuopak.higertech.com
```

Credential Higertech sengaja **terpisah dari Beacon**.

### Metadata Pos

Backend menggunakan:

```text
POST /DownloadData/GetDatatableStation
```

untuk membaca daftar stasiun/device.

### Data Historis

Backend menggunakan:

```text
POST /DownloadData/Export
```

dengan:

```text
selecedData=minute
```

sehingga data sumber yang diambil menggunakan resolusi **per 5 menit**.

Untuk periode panjang:

```text
periode yang dipilih
      ↓
pecah berdasarkan bulan
      ↓
download export bulanan Higertech
      ↓
parse workbook
      ↓
gabungkan data
      ↓
filter sesuai periode pengguna
      ↓
pipeline aplikasi
```

### Parser Export 5 Menit

Format export yang didukung antara lain:

```text
Tanggal
Jam/Menit
TMA
Debit (m3/s)
Curah Hujan (mm)
```

Parser memprioritaskan kolom:

```text
Jam/Menit
```

sebagai timestamp.

Format nama bulan Indonesia dan waktu seperti:

```text
00.05
```

dinormalisasi menjadi timestamp yang dapat diproses aplikasi.

Kolom utama dipetakan eksplisit:

```text
TMA              → Tinggi Muka Air
Curah Hujan (mm) → Curah Hujan
```

Agregasi jam-jaman tetap dilakukan oleh pipeline aplikasi.

---

## 4. Dashindo / Scadash

Integrasi Dashindo mengambil **algoritma sumber data** dari Dashindo Downloader Local v1.5.3. UI downloader lokal tidak dibawa ke repository.

Server Dashindo yang telah diidentifikasi digunakan untuk **AWLR / Tinggi Muka Air**.

### Konfigurasi

```text
DASHINDO_USERNAME
DASHINDO_PASSWORD
```

Opsional:

```text
DASHINDO_BASE_URL=http://202.180.30.82
DASHINDO_SOCKET_URL=http://202.180.30.82:8000
DASHINDO_WAIT_TIMEOUT=45
```

### Login

Alur login:

```text
GET halaman login
      ↓
ambil const token
      ↓
SHA-256 password
      ↓
POST /API/login.php
      ↓
PHPSESSID + scadash_user_token
```

### Metadata AWLR

Metadata stasiun dibaca dari:

```text
/dashboard/API/get-mqtt-awlr.php
```

Endpoint membutuhkan session serta `Referer` yang sesuai.

Mapping field menggunakan **ID Sensor**, bukan hanya ID Alat, karena satu alat dapat memiliki lebih dari satu field. Contoh:

```text
SOWL008 / ID 171 → tma
SOWL008 / ID 172 → tma2
```

### Nama Mapping Pos

Semua nama operator lintas vendor dikendalikan dari satu sumber:

```text
data/station_aliases.json
```

Kunci yang dipakai adalah `id_logger` (Beacon), `deviceId` (Higertech), `kd_hardware` (Tatonas), dan `id` sensor (Dashindo). Jika ID belum memiliki alias, aplikasi memakai nama asli vendor sebagai fallback. Dengan demikian perubahan seperti `Bintaran` menjadi `Opak Bintaran` cukup dilakukan di satu file dan tidak perlu menyentuh `api/core.py`.

Dropdown menggunakan nama operator yang lebih ringkas.

Urutannya:

1. nama tanpa kata **Irigasi**, A–Z;
2. nama dengan kata **Irigasi**, A–Z.

Contoh:

```text
Bengkok
Clereng
Ngrancah 2
Pekik Jamal
Pengasih
Safari
Secang
Sermo Outflow
Sermo Waduk
...
Secang Irigasi
```

### Historis Dashindo

Dashindo tidak menggunakan endpoint HTTP historis biasa. Backend mengikuti Engine.IO v4 menggunakan **manual HTTP long-polling**, tanpa `python-socketio` dan tanpa harus mempertahankan koneksi WebSocket.

Alur:

```text
GET /socket.io/?EIO=4&transport=polling
      ↓
parse SID dari handshake
      ↓
POST packet 40
      ↓
event ehlo
      ↓
POST /dashboard/API/websocket-auth.php
      ↓
event auth
      ↓
emit downloadcsv
      ↓
event download_csv
      ↓
decode Base64 CSV
      ↓
parse _time + _value
      ↓
pipeline aplikasi
```

### Resolusi Sumber

CSV historis yang diminta backend adalah **raw Dashindo sekitar 1 menit**, bukan sampling 5 menit.

Contoh struktur sumber:

```csv
id,_field,_time,_value
SOWL025,tma,2026-07-31 18:04:13,0.03
```

Data raw tersebut kemudian diteruskan ke pipeline aplikasi untuk pemrosesan berikutnya.

---

## Faktor Koreksi

Faktor koreksi bersifat opsional.

### Curah Hujan

Menggunakan faktor pengali:

```text
nilai_koreksi = nilai_asli × faktor
```

### Tinggi Muka Air

Menggunakan koreksi dalam meter:

```text
nilai_koreksi = nilai_asli + koreksi_meter
```

Jika koreksi tidak diaktifkan, nilai asli tidak diubah.

---

# Menjalankan Secara Lokal

## Persyaratan

- Python 3.11+ disarankan
- pip
- koneksi internet untuk sumber Server Telemetri

Install dependency:

```bash
python -m pip install -r requirements.txt
```

Jalankan aplikasi dari root repository:

```bash
python -m api.app
```

Kemudian buka:

```text
http://127.0.0.1:5050
```

Untuk Windows, Environment Variables dapat diset pada sistem, terminal, atau menggunakan konfigurasi lokal privat yang **tidak di-commit ke GitHub**.

---

# Struktur Backend

Backend telah dipisahkan agar perubahan route tidak bercampur dengan adapter telemetri:

```text
api/
├── app.py                 # entry point Flask / Vercel
├── core.py                # adapter vendor, parser, cache, dan pengolahan inti
├── routes/
│   ├── auth.py            # autentikasi aplikasi + health
│   ├── telemetry.py       # metadata dan API data vendor
│   ├── monitoring.py      # halaman + endpoint Monitoring
│   └── download.py        # export Excel Pengolahan
└── services/
    └── monitoring.py      # agregasi dan pengambilan Monitoring terpadu
```

`api/app.py` sengaja dibuat tipis agar entry point Vercel tetap sederhana. Adapter vendor belum diubah algoritmanya dalam refactor ini.

---

# Environment Variables

## Wajib untuk akses aplikasi

```text
APP_PASSWORDS
SESSION_SECRET
```

`APP_PASSWORDS` digunakan untuk melindungi fitur Server Telemetri dan dapat memuat beberapa password. Gunakan daftar dipisahkan koma, misalnya `APP_PASSWORDS=password_admin,password_operator,password_lapangan`. Format JSON array juga didukung.

`SESSION_SECRET` sebaiknya berupa string panjang, acak, dan tidak dibagikan.

## Beacon

```text
BEACON_USERNAME
BEACON_PASSWORD
```

## Tatonas

```text
TATONAS_USERNAME
TATONAS_PASSWORD
```

## Higertech

```text
HIGERTECH_USERNAME
HIGERTECH_PASSWORD
```

## Dashindo

```text
DASHINDO_USERNAME
DASHINDO_PASSWORD
```

## Konfigurasi Opsional

```text
BBWS_BASE_URL=https://bbwsso.monitoring4system.com

BEACON_USERNAME_FIELD=username
BEACON_PASSWORD_FIELD=password

HIGERTECH_BASE_URL=https://bbwsserayuopak.higertech.com

DASHINDO_BASE_URL=http://202.180.30.82
DASHINDO_SOCKET_URL=http://202.180.30.82:8000
DASHINDO_WAIT_TIMEOUT=45

BBWS_TIMEOUT=45
PARAMETER_CACHE_TTL=600
MAX_QUERY_DAYS=25
```

Tatonas saat ini menggunakan:

```text
TATONAS_BASE_URL=https://tatonas.co.id
TATONAS_PLANT=028
```

yang sudah ditetapkan pada konfigurasi project.

---

# Deploy GitHub + Vercel

## 1. Siapkan Repository GitHub

Upload seluruh isi repository hasil ZIP ini ke GitHub.

Jangan commit:

```text
.env
.env.*
credential asli
password
token
session lokal
.venv/
venv/
__pycache__/
*.pyc
```

File `.gitignore` sudah disediakan untuk membantu mencegah file lokal ikut ter-commit.

Repository dapat dibuat **Private** bila aplikasi hanya digunakan internal.

---

## 2. Import Repository ke Vercel

Di Vercel:

```text
Add New
→ Project
→ Import Git Repository
```

Pilih repository ini.

Gunakan root repository sebagai:

```text
Root Directory
```

Project menggunakan Flask/Python melalui:

```text
api/app.py
```

dan routing dikendalikan oleh:

```text
vercel.json
```

---

## 3. Tambahkan Environment Variables

Masuk ke:

```text
Project
→ Settings
→ Environment Variables
```

Tambahkan minimal credential vendor yang akan digunakan.

Untuk seluruh integrasi:

```text
BEACON_USERNAME
BEACON_PASSWORD

TATONAS_USERNAME
TATONAS_PASSWORD

HIGERTECH_USERNAME
HIGERTECH_PASSWORD

DASHINDO_USERNAME
DASHINDO_PASSWORD

APP_PASSWORDS
SESSION_SECRET
```

Set Environment Variable untuk environment yang diperlukan:

```text
Production
Preview
Development
```

sesuai kebutuhan deployment.

Setelah mengubah Environment Variables, lakukan **Redeploy**.

---

## 4. Vercel Function Duration

`vercel.json` pada repository mengatur:

```json
{
  "functions": {
    "api/app.py": {
      "maxDuration": 60
    }
  }
}
```

Dashindo menggunakan:

```text
DASHINDO_WAIT_TIMEOUT=45
```

secara default agar proses polling memiliki guard timeout yang lebih kecil dari konfigurasi function repository.

Higertech dapat membutuhkan waktu lebih lama untuk periode panjang karena backend mengambil export per bulan dengan resolusi 5 menit.

---

## 5. Catatan Koneksi Dashindo di Vercel

Dashindo menggunakan koneksi HTTP keluar ke:

```text
DASHINDO_BASE_URL
DASHINDO_SOCKET_URL
```

dengan Engine.IO v4 HTTP long-polling ke port `8000`.

Deployment harus dapat melakukan outbound HTTP ke server Dashindo tersebut.

Jika Dashindo dapat berjalan lokal tetapi gagal hanya di Vercel, periksa:

- akses outbound ke host Dashindo;
- akses port `8000`;
- timeout function;
- respons handshake Engine.IO;
- log function Vercel.

---

## 6. Verifikasi Setelah Deploy

Setelah deployment selesai:

1. Buka URL production Vercel.
2. Masukkan password Server Telemetri.
3. Uji satu vendor terlebih dahulu.
4. Pastikan daftar pos berhasil dimuat.
5. Pastikan parameter muncul.
6. Gunakan periode pendek untuk pengujian awal.
7. Jalankan **Proses Data**.
8. Periksa preview, grafik, dan hasil Excel.
9. Ulangi untuk vendor lainnya.

Disarankan menguji vendor dengan periode pendek terlebih dahulu sebelum melakukan request bulanan atau tahunan.

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
│   ├── base.html                         # header/navbar/footer bersama
│   ├── index.html                        # Olah Data Jam-Jaman
│   └── monitoring.html                   # Monitoring Telemetri Terpadu
├── static/
│   ├── css/
│   │   └── app.css                       # style bersama berbasis UI Olah Data
│   └── js/
│       ├── common.js                     # theme + helper UI bersama
│       ├── index.js                      # logika halaman Olah Data
│       └── monitoring.js                 # logika halaman Monitoring
├── data/
│   ├── station_aliases.json              # override nama pos seluruh vendor
│   ├── beacon/
│   │   ├── positions.json
│   │   └── parameter_catalog.json
│   ├── higertech/
│   │   ├── positions.json
│   │   └── parameter_catalog.json
│   ├── tatonas/
│   │   ├── positions.json
│   │   └── parameter_catalog.json
│   └── dashindo/
│       ├── positions.json
│       └── parameter_catalog.json
├── config.py
├── requirements.txt
├── vercel.json
├── run.bat
├── .gitignore
├── .vercelignore
└── README.md
```

Seluruh dokumentasi integrasi vendor dan deployment telah digabungkan ke file `README.md` ini agar repository GitHub cukup memiliki satu dokumentasi utama.

---

# Keamanan

Credential seluruh vendor harus berada di backend.

Jangan pernah memasukkan credential asli ke:

- HTML
- JavaScript frontend
- README
- repository GitHub
- screenshot publik
- file contoh yang ikut di-commit

Gunakan Environment Variables pada Vercel.

Prinsip lain:

- gunakan `SESSION_SECRET` acak;
- gunakan beberapa nilai `APP_PASSWORDS` yang kuat dan berbeda untuk pengguna/kelompok akses;
- jangan log password/token;
- validasi input periode;
- batasi file upload;
- jangan mengekspos cookie/session vendor ke frontend;
- hindari menampilkan raw error yang mengandung secret.

---

# Catatan Operasional

## Cache

Metadata tertentu menggunakan cache untuk mengurangi request berulang dan mempercepat pengalaman pengguna.

Contoh konfigurasi:

```text
PARAMETER_CACHE_TTL=600
```

Cache pada deployment serverless bersifat **best effort** karena instance Vercel dapat dibuat ulang sewaktu-waktu.

## Periode Panjang

Periode tahunan atau rentang panjang dapat memerlukan banyak request ke server vendor.

Karakteristik sumber:

| Vendor | Sumber Historis | Resolusi Sumber yang Digunakan |
|---|---|---|
| Beacon | API historis | mengikuti sumber/API |
| Tatonas | telemetry response | mengikuti response logger |
| Higertech | export Excel bulanan | 5 menit |
| Dashindo | CSV `downloadcsv` | raw sekitar 1 menit |

## Validasi Data

Data telemetry dapat memiliki:

- gap;
- timestamp tidak kontinu;
- duplicate;
- perubahan interval;
- nilai kosong;
- gangguan komunikasi alat.

Jumlah record yang lebih sedikit dari perkiraan tidak selalu berarti parser gagal. Selalu cocokkan hasil dengan sumber bila digunakan untuk pekerjaan resmi.

---

## Optimasi Request / Paralel (versi ini)

Optimasi yang diterapkan:

- metadata `positions.json` dan `parameter_catalog.json` tersedia untuk Beacon, Higertech, Tatonas, dan Dashindo; pada local metadata hasil refresh ditulis kembali ke folder `data/<vendor>/`, sedangkan Vercel menggunakan repo sebagai seed dan `/tmp` sebagai cache runtime;
- cache metadata browser tetap digunakan untuk mengurangi request berulang;
- **Beacon** maksimal 25 hari per bagian request. Aset `*_bbws` memakai endpoint cepat `/analisa/data_chunk`, sedangkan aset non-BBWS/`*_psda` memakai kembali tabel HTML `/analisa/data/...` karena endpoint chunk upstream memang menolak aset non-BBWS; retry bagian lebih kecil tetap diterapkan bila upstream bermasalah;
- **Tatonas** dan **Dashindo** default maksimal 3 bulan kalender per bagian request dan akan diperkecil lagi jika terdeteksi timeout;
- **Higertech** mempertahankan mekanisme export bulanan bawaan dan cache export yang sudah ada;
- request monitoring dijalankan paralel antar-vendor; request antar-pos non-Beacon juga paralel secara konservatif;
- progress pengambilan data pada halaman Olah Data mengikuti jumlah bagian request yang benar-benar selesai;
- periode Bulanan/Tahunan mempertahankan seluruh tanggal periode pada tabel/Excel walaupun awal atau akhir periode kosong.

Environment variable opsional untuk tuning:

```text
BEACON_CHUNK_DAYS=25
BEACON_PARALLEL_WORKERS=3
TATONAS_CHUNK_MONTHS=3
TATONAS_PARALLEL_WORKERS=2
HIGERTECH_CHUNK_MONTHS=1
HIGERTECH_PARALLEL_WORKERS=3
HIGERTECH_EXPORT_TIMEOUT=120
HIGERTECH_EXPORT_CACHE_TTL=900
HIGERTECH_EXPORT_CACHE_MAX=12
DASHINDO_CHUNK_MONTHS=3
DASHINDO_PARALLEL_WORKERS=3
MONITORING_CACHE_TTL=300
MONITORING_BEACON_WORKERS=3
```

`BEACON_CHUNK_DAYS` tetap di-clamp maksimal **25 hari** oleh aplikasi. `MAX_QUERY_DAYS` masih diterima sebagai fallback kompatibilitas untuk konfigurasi lama.

# Pengembangan

Beberapa pengembangan berikutnya yang memungkinkan:

- quality control missing/duplicate/outlier;
- cache historis;
- optimasi request periode panjang;
- monitoring kesehatan tiap integrasi vendor;
- logging diagnostik yang lebih terstruktur;
- penyimpanan dataset historis;
- integrasi spreadsheet otomatis;
- integrasi sumber telemetry tambahan.

---

## Status

Repository ini merupakan aplikasi pengolah data hidrologi terpadu dengan dukungan:

```text
Beacon
Tatonas
Higertech
Dashindo
Upload Excel/CSV Manual
```

Seluruh vendor menggunakan satu UI/UX dan satu pipeline pengolahan utama, sementara perbedaan protokol sumber ditangani oleh adapter backend masing-masing.

---

## Optimasi Request & Monitoring Terpadu (update Agustus 2026)

Versi ini menambahkan peningkatan reliabilitas/performa tanpa mengganti pipeline olah jam-jaman yang sudah ada:

- **Beacon**: maksimal 25 hari per request data; label `Bendung` disembunyikan dari nama pos, sedangkan `Bendungan` tetap dipertahankan.
- **Tatonas**: maksimal 3 bulan kalender per request, retry otomatis pada timeout, serta sensor valid tidak dianggap hilang hanya karena satu sub-periode kosong.
- **Higertech**: export bulanan tetap digunakan; nama stasiun uppercase dinormalisasi ke title case (contoh `KRANGGAN` menjadi `Kranggan`).
- **Dashindo**: maksimal 3 bulan kalender per request dan timestamp sumber tetap dikonversi UTC → WIB sesuai adapter sebelumnya.
- Metadata semua vendor memiliki seed/cache JSON persisten (`positions.json` + `parameter_catalog.json`).
- Progress **Mengambil data dari server** menjadi determinate berdasarkan bagian request yang selesai.
- Ringkasan grafik memakai **Data Terakhir, Tertinggi, Terendah**, plus **Akumulasi** untuk hujan atau **Rerata** untuk parameter lain; judul grafik juga memuat nama pos.
- Bulanan dan tahunan selalu menampilkan seluruh tanggal periode yang dipilih, termasuk tanggal kosong pada awal/akhir rentang; ekspor Excel mengikuti tabel.
- Pratinjau hasil tidak lagi dibatasi 15 baris.
- Halaman **Monitoring** memakai style/navigasi yang sama dengan Olah Data, mendukung Bootstrap datepicker, Harian/Bulanan/Tahunan/Rentang Tanggal, Jam-jaman/Harian, orientasi Horizontal/Vertikal, serta ekspor Excel.
- Header monitoring jam-jaman horizontal menggunakan dua lapis: **tanggal** lalu **jam**.
- Monitoring memprioritaskan kanal hujan nomor 2 (mis. `Curah Hujan 2` / `Precipitation Intensity 2`) bila tersedia; bila hanya satu kanal, kanal itu dipakai.
- Monitoring menjalankan vendor secara paralel agar durasi total mendekati vendor paling lambat, bukan penjumlahan semua vendor.

Environment Variable performa opsional:

```text
PARAMETER_CACHE_TTL=21600
BEACON_CHUNK_DAYS=25
BEACON_PARALLEL_WORKERS=3
TATONAS_CHUNK_MONTHS=3
TATONAS_PARALLEL_WORKERS=2
HIGERTECH_CHUNK_MONTHS=1
HIGERTECH_PARALLEL_WORKERS=3
HIGERTECH_EXPORT_TIMEOUT=120
DASHINDO_CHUNK_MONTHS=3
DASHINDO_PARALLEL_WORKERS=3
MONITORING_CACHE_TTL=300
MONITORING_BEACON_WORKERS=3
```

> `BEACON_CHUNK_DAYS` selalu dibatasi maksimal 25 hari. `MAX_QUERY_DAYS` tetap didukung sebagai fallback konfigurasi lama.
