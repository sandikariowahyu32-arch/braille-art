"""
Braille Art – tool konversi gambar ke Braille untuk kolom komentar (Android).
Jalankan dengan:  streamlit run app.py
"""

from __future__ import annotations

import hashlib
import html
import io
import math
from typing import Any

import numpy as np
import streamlit as st
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

# ----------------------------------------------------------------------------
# Konstanta
# ----------------------------------------------------------------------------
LIMIT_DEFAULT = 150          # batas karakter per komentar (TikTok / Custom awal)
MOBILE_SAFE_WIDTH = 30       # lebar aman (karakter) agar tidak wrap di layar HP
MAX_WIDTH_LIMIT = 150        # lebar mutlak tertinggi bila kunci lebar HP dimatikan
BRAILLE_BASE = 0x2800        # U+2800 = Braille Pattern Blank
BLANK = "⠀"             # area kosong (tidak dipotong aplikasi)
DOT_FILLER = "⠄"        # titik kecil, lebarnya sama dengan karakter Braille lain
MAX_SIDE = 1600              # gambar besar diperkecil dulu agar cepat
ASPECT_FIX = 0.85            # kompensasi line-height font HP (cegah gambar memanjang)
SILHOUETTE_THICKEN = 1       # penebalan titik tetap untuk gaya siluet

STYLE_LOGO = "Siluet / Logo"
STYLE_PHOTO = "Foto Berbayang"

PLATFORM_LIMITS = {
    "TikTok (150)": 150,
    "X / Twitter (280)": 280,
    "Instagram (2.200)": 2200,
    "YouTube (10.000)": 10000,
}
PLATFORM_CUSTOM = "Custom"

try:
    LANCZOS = Image.Resampling.LANCZOS
except AttributeError:  # Pillow lama
    LANCZOS = Image.LANCZOS

# st.fragment (Streamlit >= 1.37) membuat pratinjau bisa diubah tanpa menjalankan
# ulang seluruh skrip. Di versi lama dipakai fallback agar tetap berjalan normal.
fragment = (
    getattr(st, "fragment", None)
    or getattr(st, "experimental_fragment", None)
    or (lambda func: func)
)

# Bobot bit sel Braille 2 kolom x 4 baris (titik 1-8):
#   0x01 0x08
#   0x02 0x10
#   0x04 0x20
#   0x40 0x80
DOT_WEIGHTS = np.array(
    [[0x01, 0x08], [0x02, 0x10], [0x04, 0x20], [0x40, 0x80]], dtype=np.uint16
)


# ----------------------------------------------------------------------------
# Gambar
# ----------------------------------------------------------------------------
@st.cache_resource(show_spinner=False, max_entries=4)
def load_image(key: str, _upload: Any) -> Image.Image:
    """Buka gambar, perbaiki orientasi, ratakan transparansi ke latar putih, perkecil.
    `_upload` tidak ikut di-hash; cache dikunci oleh `key`, jadi byte file hanya
    dibaca saat gambar baru diunggah."""
    img = Image.open(io.BytesIO(_upload.getvalue()))
    img.draft("RGB", (MAX_SIDE, MAX_SIDE))  # mempercepat JPEG besar
    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        background = Image.new("RGBA", img.size, (255, 255, 255, 255))
        background.alpha_composite(img)
        img = background
    img = img.convert("RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE), LANCZOS)
    if img.width < 1 or img.height < 1:
        raise ValueError("Ukuran gambar tidak valid.")
    return img


def zoom_crop(img: Image.Image, zoom: float, shift_x: float, shift_y: float) -> Image.Image:
    """Zoom ke tengah gambar; shift_x / shift_y (-1..1) menggeser area zoom."""
    if zoom <= 1.0:
        return img
    w, h = img.size
    cw, ch = max(1, round(w / zoom)), max(1, round(h / zoom))
    left = round((w - cw) * (0.5 + shift_x / 2))
    top = round((h - ch) * (0.5 + shift_y / 2))
    return img.crop((left, top, left + cw, top + ch))


def upload_key(uploaded: Any) -> str:
    """Kunci unik file unggahan. Memakai file_id bila tersedia (tanpa membaca isi file)."""
    file_id = getattr(uploaded, "file_id", None)
    if file_id:
        return str(file_id)
    return hashlib.blake2b(uploaded.getvalue(), digest_size=16).hexdigest()


# ----------------------------------------------------------------------------
# Ukuran
# ----------------------------------------------------------------------------
def pixel_height(px_w: int, aspect: float) -> int:
    """Tinggi dalam titik untuk lebar titik tertentu, sudah dikoreksi ASPECT_FIX."""
    return max(1, round(px_w * aspect * ASPECT_FIX))


def rows_for_width(width: int, aspect: float) -> int:
    """Total baris karakter untuk lebar tertentu (aspect = tinggi / lebar gambar)."""
    return max(1, math.ceil(pixel_height(width * 2, aspect) / 4))


def fit_width(max_w: int, aspect: float, parts: int, limit: int) -> int:
    """Lebar terbesar (<= max_w) yang membuat tiap komentar <= limit karakter."""
    width = max_w
    while width > 1:
        rows_per_part = math.ceil(rows_for_width(width, aspect) / parts)
        if width * rows_per_part + rows_per_part - 1 <= limit:
            break
        width -= 1
    return width


def max_rows_per_part(width: int, limit: int) -> int:
    """Baris terbanyak per komentar: width*r + (r-1) <= limit."""
    return (limit + 1) // (width + 1)


# ----------------------------------------------------------------------------
# Titik
# ----------------------------------------------------------------------------
def otsu_threshold(pixels: np.ndarray) -> int:
    """Threshold otomatis (Otsu), piksel < nilai = gelap."""
    hist = np.bincount(pixels.ravel(), minlength=256).astype(np.float64)
    total = hist.sum()
    sum_all = float(np.dot(np.arange(256), hist))
    w_bg = s_bg = 0.0
    best_var, best_t = -1.0, 128
    for t in range(256):
        w_bg += hist[t]
        if w_bg == 0:
            continue
        w_fg = total - w_bg
        if w_fg == 0:
            break
        s_bg += t * hist[t]
        var = w_bg * w_fg * (s_bg / w_bg - (sum_all - s_bg) / w_fg) ** 2
        if var > best_var:
            best_var, best_t = var, t + 1
    return int(best_t)


def floyd_steinberg(pixels: np.ndarray, threshold: int) -> np.ndarray:
    """Dithering Floyd–Steinberg (list Python, jauh lebih cepat dari indeks numpy)."""
    h, w = pixels.shape
    shift = 128 - threshold
    if shift == 0:  # jalur cepat: nilai piksel sudah 0..255, tidak perlu di-clamp
        rows = pixels.astype(np.float64).tolist()
    else:
        rows = [[min(255.0, max(0.0, v + shift)) for v in row] for row in pixels.tolist()]
    dots = [[False] * w for _ in range(h)]
    for y in range(h):
        row = rows[y]
        nxt = rows[y + 1] if y + 1 < h else None
        out = dots[y]
        for x in range(w):
            old = row[x]
            if old >= 128:
                err = old - 255.0
            else:
                err = old
                out[x] = True
            if err:
                if x + 1 < w:
                    row[x + 1] += err * 0.4375
                if nxt is not None:
                    if x > 0:
                        nxt[x - 1] += err * 0.1875
                    nxt[x] += err * 0.3125
                    if x + 1 < w:
                        nxt[x + 1] += err * 0.0625
    return np.array(dots, dtype=bool)


def neighbor_count(dots: np.ndarray) -> np.ndarray:
    """Jumlah tetangga bertitik (8 arah) untuk tiap titik."""
    h, w = dots.shape
    padded = np.pad(dots, 1)
    total = np.zeros((h, w), dtype=np.uint8)
    for dy in (0, 1, 2):
        for dx in (0, 1, 2):
            if dy == 1 and dx == 1:
                continue
            total += padded[dy : dy + h, dx : dx + w]
    return total


def thicken(dots: np.ndarray, times: int) -> np.ndarray:
    """Tebalkan titik agar yang berdekatan menyatu."""
    h, w = dots.shape
    for _ in range(times):
        padded = np.pad(dots, 1)
        out = dots.copy()
        for dy in (0, 1, 2):
            for dx in (0, 1, 2):
                out |= padded[dy : dy + h, dx : dx + w]
        dots = out
    return dots


def detail_to_contrast(detail: int) -> float:
    """Slider Ketajaman 0..100 -> faktor kontras 0.5x..2.0x (50 = netral)."""
    return 2.0 ** ((detail - 50) / 50.0)


def make_dots(
    img: Image.Image,
    width: int,
    style: str,
    invert: bool,
    detail: int,
) -> np.ndarray:
    """Gambar -> array titik (bool)."""
    gray = img.convert("L")
    aspect = gray.height / gray.width
    px_w = width * 2
    px_h = pixel_height(px_w, aspect)

    if gray.width > px_w * 4:  # perkecil bertahap agar halus
        mid_w = px_w * 4
        gray = gray.resize((mid_w, max(1, round(mid_w * aspect))), LANCZOS)
    small = gray.resize((px_w, px_h), LANCZOS)

    photo = style == STYLE_PHOTO
    small = ImageOps.equalize(small) if photo else ImageOps.autocontrast(small, cutoff=1)
    contrast = detail_to_contrast(detail)
    if contrast != 1.0:
        small = ImageEnhance.Contrast(small).enhance(contrast)
    if not photo:
        small = small.filter(ImageFilter.UnsharpMask(radius=1, percent=150, threshold=0))

    pixels = np.asarray(small, dtype=np.uint8)

    if photo:
        dots = floyd_steinberg(pixels, 128)
    else:
        dots = pixels < otsu_threshold(pixels)

    if invert:
        dots = ~dots
    if not photo:
        dots &= neighbor_count(dots) > 0  # buang titik tunggal (noise)
        dots = thicken(dots, SILHOUETTE_THICKEN)
    return dots


# ----------------------------------------------------------------------------
# Teks Braille
# ----------------------------------------------------------------------------
def dots_to_codes(dots: np.ndarray) -> np.ndarray:
    """Array titik -> kode sel Braille (baris x kolom), 2x4 titik per karakter."""
    h, w = dots.shape
    pad = (-h) % 4
    if pad:
        dots = np.vstack([dots, np.zeros((pad, w), dtype=bool)])
    rows, cols = dots.shape[0] // 4, w // 2
    blocks = dots.reshape(rows, 4, cols, 2).astype(np.uint16)
    return (blocks * DOT_WEIGHTS[None, :, None, :]).sum(axis=(1, 3))


def trim_codes(codes: np.ndarray) -> np.ndarray:
    """Auto-Trim: buang baris kosong paling atas dan paling bawah (jika ada isi)."""
    filled = np.flatnonzero(codes.any(axis=1))
    if filled.size == 0:
        return codes
    return codes[filled[0] : filled[-1] + 1]


def row_weights(codes: np.ndarray) -> list[int]:
    """Jumlah titik menyala di tiap baris karakter."""
    bits = np.unpackbits(codes.astype(np.uint8)[..., None], axis=-1)
    return bits.sum(axis=(1, 2)).tolist()


def codes_to_lines(codes: np.ndarray, filler: str) -> list[str]:
    """Kode sel -> baris teks Braille (vektorisasi: satu kali decode untuk semua sel)."""
    codepoints = np.where(
        codes == 0, ord(filler), codes.astype(np.uint32) + BRAILLE_BASE
    ).astype("<u4")
    rows, cols = codepoints.shape
    text = codepoints.tobytes().decode("utf-32-le")
    return [text[i * cols : (i + 1) * cols] for i in range(rows)]


def even_cuts(n: int, parts: int) -> list[int]:
    """Titik potong rata (atas ke bawah)."""
    per_part = math.ceil(n / parts)
    return list(range(per_part, n, per_part))


def smart_cuts(weights: list[int], parts: int, max_rows: int) -> list[int] | None:
    """Titik potong di baris paling kosong di sekitar posisi ideal, supaya batas
    antar komentar jatuh di latar, bukan di tengah objek. Tiap bagian dijaga
    <= max_rows agar tetap muat di batas karakter. None bila tidak memungkinkan."""
    n = len(weights)
    if parts <= 1 or n <= parts or max_rows < 1 or n > parts * max_rows:
        return None
    window = max(1, round(n / parts * 0.25))
    cuts: list[int] = []
    prev = 0
    for k in range(1, parts):
        ideal = round(k * n / parts)
        hard_lo = max(prev + 1, n - (parts - k) * max_rows)
        hard_hi = min(prev + max_rows, n - (parts - k))
        if hard_lo > hard_hi:
            return None
        lo, hi = max(hard_lo, ideal - window), min(hard_hi, ideal + window)
        if lo > hi:
            lo, hi = hard_lo, hard_hi
        # potong di antara baris c-1 dan c: pilih yang titiknya paling sedikit
        best = min(
            range(lo, hi + 1),
            key=lambda c: (weights[c - 1] + weights[c], abs(c - ideal)),
        )
        cuts.append(best)
        prev = best
    return cuts


def split_lines(lines: list[str], cuts: list[int]) -> list[str]:
    """Bagi baris menjadi beberapa komentar menurut titik potong."""
    bounds = [0, *cuts, len(lines)]
    return ["\n".join(lines[a:b]) for a, b in zip(bounds, bounds[1:]) if b > a]


def dots_preview(dots: np.ndarray, dark: bool = False) -> Image.Image:
    """Pratinjau titik: terang di mode gelap, hitam di mode terang.
    Skala dinamis agar pratinjau tidak raksasa pada resolusi tinggi."""
    lit, bg = (255, 0) if dark else (0, 255)
    img = Image.fromarray(np.where(dots, lit, bg).astype(np.uint8))
    scale = max(1, min(6, 480 // max(1, img.width)))
    return img.resize((img.width * scale, img.height * scale), Image.NEAREST)


# ----------------------------------------------------------------------------
# Pipeline (dua tahap)
# ----------------------------------------------------------------------------
@st.cache_data(show_spinner=False, max_entries=24)
def build_dots(
    key: str,
    _upload: Any,
    limit: int,
    parts: int,
    max_w: int,
    style: str,
    invert: bool,
    detail: int,
    zoom: float,
    shift_x: float,
    shift_y: float,
) -> tuple[np.ndarray, int]:
    """Tahap berat (resize, dithering, dst.), di-cache. Opsi yang hanya memengaruhi
    teks (Dot Filler) sengaja tidak ada di sini agar perubahannya instan."""
    img = zoom_crop(load_image(key, _upload), zoom, shift_x, shift_y)
    aspect = img.height / img.width
    final_w = fit_width(max_w, aspect, parts, limit)  # Auto-Fit selalu aktif
    return make_dots(img, final_w, style, invert, detail), final_w


def compose_text(
    dots: np.ndarray, final_w: int, limit: int, parts: int, dot_filler: bool
) -> tuple[list[str], int]:
    """Tahap ringan: titik -> teks Braille per komentar."""
    codes = trim_codes(dots_to_codes(dots))  # Auto-Trim selalu aktif
    lines = codes_to_lines(codes, DOT_FILLER if dot_filler else BLANK)

    cuts = None
    if parts > 1:  # potong cerdas (otomatis)
        cuts = smart_cuts(row_weights(codes), parts, max_rows_per_part(final_w, limit))
    if cuts is None:
        cuts = even_cuts(len(lines), parts)
    return split_lines(lines, cuts), len(lines)


# ----------------------------------------------------------------------------
# UI
# ----------------------------------------------------------------------------
st.set_page_config(
    page_title="Braille Art",
    page_icon="⠿",
    layout="centered",
    initial_sidebar_state="collapsed",
    menu_items={"Get help": None, "Report a bug": None, "About": None},
)

st.markdown(
    """
    <style>
    /* Tampilan app murni: sembunyikan elemen bawaan Streamlit. */
    #MainMenu, footer, [data-testid="stToolbar"], [data-testid="stDecoration"],
    [data-testid="stStatusWidget"], header[data-testid="stHeader"] { display: none !important; }
    .block-container, [data-testid="stMainBlockContainer"] {
        padding: 1rem 1rem 3rem !important; max-width: 720px;
    }

    [data-testid="stCode"] pre, [data-testid="stCode"] code, [data-testid="stCode"] span {
        font-family: 'Noto Sans Symbols', 'Noto Sans Symbols 2', 'Noto Sans',
                     'Roboto', monospace !important;
        line-height: 1.0 !important;
        letter-spacing: 0 !important;
        font-size: 18px !important;
    }
    [data-testid="stCode"] pre { white-space: pre !important; overflow-x: auto; }
    .bpre {
        font-family: 'Noto Sans Symbols', 'Noto Sans Symbols 2', 'Noto Sans',
                     'Roboto', monospace;
        line-height: 1.1; letter-spacing: 0; font-size: 18px;
        white-space: pre; overflow-x: auto;
        padding: 12px; border-radius: 8px; margin: 0 0 .75rem 0;
    }
    .ok  { color:#1b8a3a; font-weight:700; margin-top:.5rem; }
    .bad { color:#d62828; font-weight:700; margin-top:.5rem; }
    /* Jaga kolom tetap sebaris di layar HP (Streamlit biasanya menumpuknya). */
    @media (max-width: 640px) {
        [data-testid="stHorizontalBlock"] {
            flex-direction: row !important; flex-wrap: nowrap !important; gap: .5rem !important;
        }
        [data-testid="stColumn"], [data-testid="column"] {
            min-width: 0 !important; width: auto !important; flex: 1 1 0 !important;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


@fragment
def preview_panel(chunks: list[str], dots: np.ndarray) -> None:
    """Pratinjau; berjalan sebagai fragment sehingga togglenya tidak memicu
    konversi ulang, dan tidak dirender sama sekali selama dimatikan."""
    if not st.toggle("Pratinjau", False):
        return
    dark = st.toggle(
        "Mode gelap", False,
        help="Simulasi kolom komentar gelap: titik putih di latar hitam. "
        "Jika hasil terlihat terbalik, aktifkan Invert Warna.",
    )
    bg, fg = ("#000000", "#ffffff") if dark else ("#ffffff", "#000000")
    for chunk in chunks:
        st.markdown(
            f'<pre class="bpre" style="background:{bg};color:{fg}">{html.escape(chunk)}</pre>',
            unsafe_allow_html=True,
        )
    st.image(dots_preview(dots, dark))


st.markdown("#### ⠿ Braille Art")

# --- Kontrol utama (3) ------------------------------------------------------
uploaded = st.file_uploader(
    "Gambar (JPG, PNG, WebP, BMP)", type=["jpg", "jpeg", "png", "webp", "bmp"]
)

platform = st.radio(
    "Target platform",
    [*PLATFORM_LIMITS, PLATFORM_CUSTOM],
    horizontal=True,
)
if platform == PLATFORM_CUSTOM:
    limit = int(
        st.number_input(
            "Batas karakter / komentar",
            min_value=30, max_value=50000, value=LIMIT_DEFAULT, step=50,
        )
    )
else:
    limit = PLATFORM_LIMITS[platform]

col_style, col_invert = st.columns([3, 2])
style = col_style.radio("Gaya", [STYLE_LOGO, STYLE_PHOTO], horizontal=True)
invert = col_invert.checkbox(
    "Invert Warna", False, help="Aktifkan bila komentar Anda tampil di Dark Mode."
)

# --- Lanjutan ---------------------------------------------------------------
with st.expander("Lanjutan"):
    detail = st.slider(
        "Ketajaman / Detail", 0, 100, 50,
        help="Naikkan untuk kontras lebih tegas dan detail lebih banyak; turunkan untuk hasil lebih lembut.",
    )
    parts = int(st.slider("Pecah Komentar", 1, 10, 1))
    zoom_pct = st.slider("Zoom (%)", 100, 300, 100, 10)
    zoom = zoom_pct / 100
    shift_x = shift_y = 0.0
    if zoom_pct > 100:
        col_h, col_v = st.columns(2)
        shift_x = col_h.slider("Geser Horizontal", -100, 100, 0) / 100
        shift_y = col_v.slider("Geser Vertikal", -100, 100, 0) / 100
    dot_filler = st.checkbox(
        "Ratakan Baris (Dot Filler)", False,
        help="Isi sel kosong dengan titik kecil bila baris terlihat bergeser.",
    )
    # Default mengikuti platform: aktif untuk batas kecil, mati untuk IG / YouTube.
    lock_width = st.checkbox(
        "Kunci lebar aman HP (maks 30 karakter)",
        value=(limit <= 280),
        help="Matikan agar gambar melebar sampai memenuhi kuota karakter (maks 150 karakter).",
    )
max_w = MOBILE_SAFE_WIDTH if lock_width else MAX_WIDTH_LIMIT

if uploaded is None:
    st.stop()

try:
    dots, final_w = build_dots(
        upload_key(uploaded), uploaded, limit, parts, max_w, style, invert,
        detail, zoom, shift_x, shift_y,
    )
    chunks, n_rows = compose_text(dots, final_w, limit, parts, dot_filler)
except Exception as exc:  # file rusak / format tidak didukung
    st.error(f"Gagal memproses gambar: {exc}")
    st.stop()

if not (dots.any() and not dots.all()):
    st.warning("Hasil satu warna saja (kosong/penuh). Coba ubah Ketajaman atau Invert Warna.")

if final_w > MOBILE_SAFE_WIDTH:
    st.info(
        f"Gambar memakai lebar ekstra ({final_w} karakter) agar sangat detail, "
        f"tetapi baris bisa terpotong (wrap) di layar HP yang sempit."
    )

for i, chunk in enumerate(chunks, start=1):
    count = len(chunk)
    if len(chunks) > 1:
        st.markdown(f"**Bagian {i} dari {len(chunks)}**")
    if count <= limit:
        st.markdown(
            f'<div class="ok">Total Karakter: {count} / {limit} ✅ Aman</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f'<div class="bad">Total Karakter: {count} / {limit} '
            f"❌ Melebihi batas! Naikkan Pecah Komentar atau perbesar batas.</div>",
            unsafe_allow_html=True,
        )
    st.code(chunk, language=None)  # tombol Copy bawaan di pojok kanan atas

st.caption(f"{final_w} × {n_rows} karakter • {len(chunks)} komentar")

preview_panel(chunks, dots)