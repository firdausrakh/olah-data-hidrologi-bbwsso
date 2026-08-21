# V9 — Monitoring Classification & Freshness

Perubahan utama:

- Nilai Curah Hujan pada **Data Monitoring Terpadu** memakai warna klasifikasi yang sama dengan Ringkasan Tertinggi.
- Export Excel Data Monitoring Terpadu ikut memberi fill warna hanya pada sel nilai yang terklasifikasi.
- Kartu **Klasifikasi Curah Hujan** berada langsung di bawah Data Monitoring Terpadu dan kelompok Intensitas/Harian ditumpuk vertikal.
- Label rentang klasifikasi disederhanakan (contoh `1–5`, `>50`).
- Status Pengambilan: **Berhasil**, **Gagal**, **Peringatan**, **Terputus**.
- Pada v10, status gap diperbarui menjadi gap kosong kontinyu terpanjang per hari; lihat `MIGRATION_V10.md`.
- Nilai `0.0` tetap dianggap data valid karena freshness dihitung dari timestamp data mentah, bukan dari besar nilai.
- Primary action: biru PU dengan teks/ikon kuning PU.
- Secondary/export action: kuning PU dengan teks/ikon biru PU.
