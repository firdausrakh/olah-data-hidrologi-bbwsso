# Shared UI Components

Pengolahan dan Monitoring memakai komponen Jinja bersama dari `templates/components/ui.html` dan styling dasar dari `static/css/ui-components.css`.

Komponen utama:

- `three_column_layout(...)`: shell tiga kolom reusable untuk Pengolahan dan Monitoring. Lebar kolom, gap, alignment, breakpoint tablet/mobile, dan urutan kolom ditentukan satu kali di `ui-components.css`.
- `card(...)`: surface/card utama dengan radius, border, shadow, dan spacing yang sama.
- `card_header(...)`: header card dengan props judul, deskripsi, ikon, varian ikon (`box`/`inline`), level heading, serta area action.
- `field(...)`: wrapper input/select dengan props label, target input, bantuan tooltip, kelas tambahan, dan id wrapper/label bila dibutuhkan JavaScript.
- `stat_card(...)`: card statistik reusable untuk nilai terakhir, tertinggi, terendah, dan akumulasi/rerata pada Pengolahan.
- `status_card(...)`: card status proses/request.
- `summary_table(...)`: tabel ringkasan compact, scrollable, sticky-header, dan memiliki tombol Excel. Dipakai oleh ringkasan puncak Monitoring.
- `info_item(...)`: baris informasi singkat dengan ikon.

Semua komponen menggunakan semantic theme tokens dari `static/css/app.css`. Page CSS (`processing.css` dan `monitoring.css`) hanya mengatur layout dan perilaku khusus halaman, bukan mendefinisikan ulang warna light/dark komponen.

## Dark mode

Dark mode tidak mengandalkan warna navy light yang di-hardcode pada masing-masing halaman. Token seperti `--component-icon`, `--component-heading`, `--surface-raised`, `--icon-soft`, `--primary-action-*`, dan `--tooltip-*` memiliki pasangan light/dark sehingga komponen otomatis mendapatkan kontras yang konsisten.

## Three-column layout

Pengolahan dan Monitoring menggunakan macro `three_column_layout(...)` dengan struktur `left`, `center`, dan `right` yang sama. Kolom samping sekarang bersifat fluid dengan minimum aman, bukan fixed-width: kiri minimal 340 px dan kanan minimal 300 px pada desktop, sementara kolom tengah mengambil ruang tersisa. Pada viewport yang lebih kecil minimum tersebut turun melalui breakpoint bersama sebelum akhirnya menjadi satu kolom pada mobile.

Pendekatan ini menjaga kedua halaman tetap sejajar, tetapi memberi cukup ruang untuk dua input tanggal `yyyy-mm-dd` agar tidak terpotong.

Radius utama seluruh `ui-card` menggunakan satu token `--radius-xl` (16 px) pada desktop maupun mobile; page stylesheet tidak boleh mengubah radius card utama.
