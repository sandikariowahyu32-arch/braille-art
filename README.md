# ⠿ Braille Art

Ubah gambar menjadi seni Braille yang siap ditempel di kolom komentar TikTok, X / Twitter, Instagram, dan YouTube. Dibuat dengan Streamlit, dirancang untuk dipakai dari layar HP.

## Fitur Utama

- **Preset platform**: TikTok (150), X / Twitter (280), Instagram (2.200), YouTube (10.000), atau batas Custom.
- **Auto-Fit**: lebar gambar otomatis menyesuaikan batas karakter yang dipilih, sehingga kuota terpakai semaksimal mungkin.
- **Smart Cuts**: saat hasil dipecah menjadi beberapa komentar, titik potong dicari di baris paling kosong agar tidak memotong mata, mulut, atau bagian penting objek.
- **Auto-Trim**: baris kosong di bagian atas dan bawah dibuang otomatis agar tidak memakan kuota karakter.
- **Dua gaya**: Siluet / Logo untuk gambar tegas, dan Foto Berbayang (dithering Floyd–Steinberg) untuk foto.
- **Koreksi rasio aspek**: gambar tidak terlihat memanjang karena jarak antarbaris font di HP.
- **Zoom dan geser**, **Invert Warna** untuk Dark Mode, serta **pratinjau mode gelap**.
- **Format gambar**: JPG, PNG, WebP, dan BMP.
- **Cepat dan responsif**: hasil konversi di-cache, sehingga mengubah pengaturan ringan terasa instan.

## Menjalankan Secara Lokal

Prasyarat: Python 3.9 atau lebih baru.

```bash
git clone https://github.com/USERNAME/braille-art.git
cd braille-art

python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
streamlit run app.py
```

Aplikasi akan terbuka di `http://localhost:8501`.

## Deploy ke Streamlit Community Cloud

1. Unggah proyek ini ke repository GitHub.
2. Buka [share.streamlit.io](https://share.streamlit.io) dan login dengan akun GitHub.
3. Klik **Create app**, lalu pilih repository, branch `main`, dan file utama `app.py`.
4. Klik **Deploy**.

## Struktur Proyek

```
.
├── .streamlit/
│   └── config.toml
├── .gitignore
├── README.md
├── app.py
├── packages.txt
└── requirements.txt
```

## Catatan Penggunaan

- Batas karakter X / Twitter dihitung berbobot: karakter non-Latin dapat dihitung 2. Bila hasil ditolak, gunakan **Custom** dengan batas sekitar 140.
- Lebar di atas 30 karakter bisa terpotong (wrap) di layar HP yang sempit. Aktifkan **Kunci lebar aman HP** di menu Lanjutan bila perlu.
- Aktifkan **Invert Warna** bila komentar Anda akan dilihat di Dark Mode.