"""Builds PANDUAN.pdf (user guide, Indonesian) from the screenshots of shots.py.
usage: python docs/panduan/build.py <screenshot dir> <output pdf>
Needs reportlab and Pillow; uses the Carlito font when installed."""

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Flowable,
    Image as RLImage,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parents[2]
VERSION = "1.2.0"
ACCENT = colors.HexColor("#005fb8")
SOFT = colors.HexColor("#eef4fc")
MUTED = colors.HexColor("#5f6b7a")
WARN_BG = colors.HexColor("#fff4e5")
BADGE = (232, 89, 12)

# numbered markers drawn on the screenshots: name -> [(x, y), ...] in screenshot pixels
CALLOUTS = {  # each marker sits on the top-left corner of what it points at
    "01_template": [(296, 155), (280, 684), (1147, 753)],
    "02_editor": [(10, 8), (700, 84), (692, 466), (1146, 564), (700, 703), (700, 743)],
    "03_kunci": [(280, 108), (496, 198), (656, 255), (280, 676)],
    "04_folder": [(808, 137), (889, 137), (1060, 137), (296, 181), (285, 232), (293, 617)],
    "05_scan_dialog": [(22, 30), (22, 90), (22, 182), (22, 218), (460, 390)],
    "06_hasil": [(293, 137), (293, 219), (296, 262)],
    "07_siap": [(279, 108), (770, 104)],
    "08_proses": [(285, 183), (868, 199), (1090, 108), (264, 716)],
    "09_koreksi": [(14, 40), (14, 106), (10, 637), (847, 637)],
    "10_rekap": [(264, 118), (293, 165), (279, 682), (1037, 682)],
    "11_tutup": [(484, 343), (562, 343), (736, 343)],
}
PAD_LEFT = {"05_scan_dialog": 44}  # white margin added on the left for the markers


class Badge(Flowable):
    """Orange numbered circle matching the markers on the screenshots."""

    def __init__(self, n, size=6 * mm):
        super().__init__()
        self.n, self.size = n, size

    def wrap(self, *_):
        return self.size, self.size

    def draw(self):
        c, r = self.canv, self.size / 2
        c.setFillColorRGB(*[v / 255 for v in BADGE])
        c.circle(r, r - 1, r, stroke=0, fill=1)
        c.setFillColor(colors.white)
        c.setFont(BADGE_FONT[0], 9.5)
        c.drawCentredString(r, r - 4.3, str(self.n))


BADGE_FONT = ["Helvetica-Bold"]


def fonts():
    base = Path("/usr/share/fonts/truetype/crosextra")
    try:
        for name, file in (("Body", "Carlito-Regular.ttf"), ("Body-Bold", "Carlito-Bold.ttf"),
                           ("Body-Italic", "Carlito-Italic.ttf"), ("Body-BoldItalic", "Carlito-BoldItalic.ttf")):  # fmt: skip
            pdfmetrics.registerFont(TTFont(name, str(base / file)))
        pdfmetrics.registerFontFamily("Body", normal="Body", bold="Body-Bold", italic="Body-Italic",
                                      boldItalic="Body-BoldItalic")  # fmt: skip
        return "Body", "Body-Bold"
    except Exception:
        return "Helvetica", "Helvetica-Bold"


def annotate(src, dst, points, pad=0):
    img = Image.open(src).convert("RGB")
    if pad:
        wide = Image.new("RGB", (img.width + pad, img.height), "white")
        wide.paste(img, (pad, 0))
        img = wide
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 15)
    except OSError:
        font = ImageFont.load_default()
    for n, (x, y) in enumerate(points, 1):
        r = 13
        d.ellipse([x - r - 3, y - r - 3, x + r + 3, y + r + 3], fill="white")
        d.ellipse([x - r, y - r, x + r, y + r], fill=BADGE)
        d.text((x, y), str(n), fill="white", font=font, anchor="mm")
    img.save(dst, quality=88)
    return dst


def main(shots, out_pdf):
    shots, out_pdf = Path(shots), Path(out_pdf)
    work = out_pdf.parent / "_panduan_img"
    work.mkdir(parents=True, exist_ok=True)
    body_font, bold_font = fonts()
    BADGE_FONT[0] = bold_font

    st = {
        "body": ParagraphStyle("body", fontName=body_font, fontSize=11, leading=15.5, spaceAfter=5),
        "small": ParagraphStyle("small", fontName=body_font, fontSize=9.5, leading=13, textColor=MUTED),
        "h1": ParagraphStyle("h1", fontName=bold_font, fontSize=21, leading=26, textColor=ACCENT, spaceBefore=4,
                             spaceAfter=8),  # fmt: skip
        "h2": ParagraphStyle("h2", fontName=bold_font, fontSize=14, leading=18, spaceBefore=10, spaceAfter=5),
        "eyebrow": ParagraphStyle("eyebrow", fontName=bold_font, fontSize=9.5, leading=12, textColor=ACCENT),
        "cell": ParagraphStyle("cell", fontName=body_font, fontSize=10, leading=13.5),
        "cellb": ParagraphStyle("cellb", fontName=bold_font, fontSize=10, leading=13.5),
        "cover": ParagraphStyle("cover", fontName=bold_font, fontSize=34, leading=40, alignment=TA_CENTER),
        "coversub": ParagraphStyle("coversub", fontName=body_font, fontSize=15, leading=20, alignment=TA_CENTER,
                                   textColor=MUTED),  # fmt: skip
    }
    W = A4[0] - 40 * mm

    def p(text, style="body"):
        return Paragraph(text, st[style])

    def shot(name, width=W, caption=None):
        src = shots / f"{name}.png"
        img = annotate(src, work / f"{name}.jpg", CALLOUTS.get(name, []), PAD_LEFT.get(name, 0))
        w, h = Image.open(img).size
        flow = [RLImage(str(img), width=width, height=width * h / w)]
        frame = Table([[flow[0]]], colWidths=[width + 2])
        frame.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#d0d7de")),
                                   ("LEFTPADDING", (0, 0), (-1, -1), 1), ("RIGHTPADDING", (0, 0), (-1, -1), 1),
                                   ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))  # fmt: skip
        items = [frame]
        if caption:
            items += [Spacer(1, 3), p(caption, "small")]
        return KeepTogether(items + [Spacer(1, 6)])

    def numbered(rows):
        """Explanations matching the orange markers."""
        data = []
        for n, text in enumerate(rows, 1):
            badge = Badge(n)
            data.append([badge, Paragraph(text, st["cell"])])
        t = Table(data, colWidths=[10 * mm, W - 10 * mm])
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                               ("LEFTPADDING", (0, 0), (-1, -1), 0)]))  # fmt: skip
        return t

    def note(text, kind="tip"):
        bg, label = (SOFT, "Tips") if kind == "tip" else (WARN_BG, "Penting")
        t = Table([[Paragraph(f"<b>{label}:</b> {text}", st["cell"])]], colWidths=[W])
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), bg), ("LEFTPADDING", (0, 0), (-1, -1), 9),
                               ("RIGHTPADDING", (0, 0), (-1, -1), 9), ("TOPPADDING", (0, 0), (-1, -1), 7),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                               ("LINEBEFORE", (0, 0), (0, -1), 3, ACCENT if kind == "tip" else colors.HexColor("#e8590c"))]))  # fmt: skip
        return KeepTogether([Spacer(1, 2), t, Spacer(1, 6)])

    def table(rows, widths, header=True):
        data = [[Paragraph(c, st["cellb" if header and i == 0 else "cell"]) for c in r] for i, r in enumerate(rows)]
        t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
        style = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d0d7de")),
                 ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                 ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]  # fmt: skip
        if header:
            style.append(("BACKGROUND", (0, 0), (-1, 0), SOFT))
        t.setStyle(TableStyle(style))
        return t

    def step_head(n, title):
        return [p(f"LANGKAH {n} DARI 6", "eyebrow"), p(title, "h1")]

    story = []
    # ---- cover
    story += [Spacer(1, 45 * mm), RLImage(str(ROOT / "assets" / "icon_512.png"), width=42 * mm, height=42 * mm),
              Spacer(1, 10 * mm), p("Panduan Pemindai LJK", "cover"), Spacer(1, 4 * mm),
              p("Memeriksa Lembar Jawaban Komputer langkah demi langkah", "coversub"), Spacer(1, 2 * mm),
              p(f"OMRChecker versi {VERSION}", "coversub"), PageBreak()]  # fmt: skip

    # ---- overview
    story += [p("Isi panduan", "h1")]
    story += [table([["Bagian", "Isi"],
                     ["Sebelum mulai", "Persyaratan, memasang program, menyiapkan scanner, tips scan LJK"],
                     ["Langkah 1", "Memilih atau membuat template LJK"],
                     ["Langkah 2", "Mengisi kunci jawaban dan aturan nilai"],
                     ["Langkah 3", "Memilih folder LJK peserta atau scan langsung dari scanner; daftar peserta"],
                     ["Langkah 4", "Folder hasil dan nama ujian"],
                     ["Langkah 5", "Memproses LJK, memeriksa baris merah, koreksi manual"],
                     ["Langkah 6", "Rekap nilai, analisis butir soal, ekspor ke Excel"],
                     ["Jika ada masalah", "Masalah umum dan cara mengatasinya"]], [38 * mm, W - 38 * mm])]  # fmt: skip
    story += [Spacer(1, 8), p("Cara kerja singkat", "h2"),
              p("Program membaca bulatan yang dihitamkan peserta pada hasil scan LJK, mencocokkannya dengan kunci "
                "jawaban, lalu menghitung nilai. Satu kali pemeriksaan selalu melalui <b>6 langkah</b> yang tampil "
                "di sisi kiri jendela. Langkah yang sudah selesai diberi tanda centang hijau; langkah yang sedang "
                "dikerjakan disorot biru. Klik <b>Lanjut</b> di kanan bawah untuk pindah ke langkah berikutnya, "
                "atau klik nama langkah di sisi kiri untuk kembali."),
              p("Pengaturan terakhir (template, kunci, folder) disimpan otomatis, jadi saat program dibuka lagi "
                "Anda bisa melanjutkan pekerjaan yang sama.")]
    story += [note("Angka oranye pada setiap gambar di panduan ini dijelaskan di daftar bernomor di bawah gambarnya.")]
    story.append(PageBreak())

    # ---- before starting
    story += [p("Sebelum mulai", "h1"), p("Persyaratan komputer", "h2"),
              table([["Komponen", "Kebutuhan"],
                     ["Sistem operasi", "Windows 10 atau Windows 11, 64-bit"],
                     ["Memori (RAM)", "Minimal 4 GB, disarankan 8 GB untuk ratusan LJK sekaligus"],
                     ["Ruang disk", "Minimal 500 MB kosong"],
                     ["Layar", "Minimal 1366 × 768"],
                     ["Membuka rekap nilai", "Microsoft Excel, LibreOffice Calc, atau WPS Office"]],
                    [45 * mm, W - 45 * mm]),  # fmt: skip
              p("Memasang dan membuka program", "h2"),
              numbered(["Ekstrak <b>OMRChecker-windows.zip</b> ke folder mana saja, misalnya <i>Dokumen</i>. "
                        "Tidak perlu memasang Python atau program lain.",
                        "Klik dua kali <b>OMRChecker.exe</b>. Pembukaan pertama bisa memakan waktu 10–20 detik.",
                        "Bila muncul peringatan <i>Windows protected your PC</i>, klik <b>More info</b> lalu "
                        "<b>Run anyway</b>. Peringatan ini muncul karena program belum bertanda tangan digital."]),
              p("Menyiapkan scanner (bila ingin scan langsung dari program)", "h2"),
              p("Pasang driver scanner dari situs produsennya, misalnya <b>Epson Scan 2</b> untuk Epson DS-410 atau "
                "L3210, dan driver Plustek untuk SmartOffice PS283. Setelah driver terpasang, scanner akan muncul "
                "di Langkah 3. Scanner yang punya dua driver tampil dua kali, bertanda <b>(TWAIN)</b> dan "
                "<b>(WIA)</b>."),
              p("Tips scan LJK", "h2"),
              table([["Hal", "Saran"],
                     ["Resolusi", "200–300 dpi. Abu-abu sudah cukup dan file lebih kecil daripada berwarna."],
                     ["Kotak hitam di sudut", "Keempat kotak hitam di sudut LJK harus ikut terscan, jangan terpotong."],
                     ["Ukuran kertas", "Pilih A4 atau F4/Folio sesuai LJK. Kaca scanner A4 (mis. Epson L3210) "
                                       "tidak muat LJK F4."],
                     ["Arah kertas", "Lembar yang terbalik atas-bawah diputar otomatis."],
                     ["Format file", "JPG, PNG, atau PDF (PDF boleh berisi banyak halaman)."],
                     ["Foto HP", "Bisa dipakai (mis. CamScanner), asalkan kertas rata dan terang."]],
                    [40 * mm, W - 40 * mm]),  # fmt: skip
              PageBreak()]

    # ---- step 1
    story += step_head(1, "Pilih template LJK")
    story += [p("Template adalah peta letak semua bulatan di LJK. Template cukup dibuat <b>sekali per desain LJK</b>, "
                "lalu dipakai terus untuk ujian-ujian berikutnya."),
              shot("01_template"),
              numbered(["Daftar template yang sudah ada. Klik salah satu; gambar LJK-nya tampil di kanan.",
                        "<b>+ Buat baru dari LJK kosong</b> untuk desain LJK yang belum punya template. "
                        "<b>Edit</b> mengubah template terpilih. <b>Ekspor</b> menyimpan template sebagai satu file "
                        "<i>.ljk</i> untuk dipakai di komputer lain, dan <b>Impor</b> membukanya di sana. "
                        "<b>Hapus</b> menghapus template.",
                        "Klik <b>Lanjut</b> bila template yang benar sudah dipilih."]),
              PageBreak(),
              p("Membuat template baru dari LJK kosong", "h2"),
              p("Siapkan hasil scan LJK yang <b>belum diisi</b> (JPG/PNG/PDF). Klik <b>+ Buat baru dari LJK kosong</b>, "
                "lalu pilih file tersebut. Program langsung mendeteksi semua kelompok bulatan (disebut <i>blok</i>)."),
              shot("02_editor"),
              numbered(["<b>Buka scan LJK kosong</b>: memilih file LJK kosong (bisa diulang bila salah file).",
                        "<b>Daftar blok</b>. Kotak biru = blok soal pilihan ganda, kotak hijau = blok angka "
                        "(No. peserta, kode soal, tanggal). Klik blok di daftar atau di gambar untuk memilihnya; "
                        "blok terpilih berwarna merah.",
                        "<b>Isi blok terpilih</b>. Untuk blok angka, isi <b>Nama kolom</b>: misalnya <i>NoPeserta</i>, "
                        "<i>KodeSoal</i>, <i>TglLahir</i>. Blok dengan nama kolom sama digabung berurutan "
                        "(TGL, BLN, THN → TglLahir). Untuk blok soal, periksa <b>No. soal awal</b> dan "
                        "<b>Pilihan</b> (A–E).",
                        "Klik <b>Terapkan</b> setiap selesai mengubah isi blok.",
                        "<b>Simpan ke pustaka template</b>, lalu beri nama template (mis. <i>LJK Ujian Umum</i>).",
                        "<b>Uji dengan LJK terisi</b> (disarankan): pilih satu LJK yang sudah diisi peserta untuk "
                        "memastikan bacaan program sudah benar."])]
    story += [note("Blok yang terlewat bisa dibuat sendiri dengan menarik kotak di gambar. Blok yang bukan bulatan "
                   "jawaban (mis. logo) bisa dihapus atau diberi jenis <i>Abaikan</i>. Bila satu blok berisi beberapa "
                   "kolom soal sekaligus, pakai <b>Pecah per kolom</b> / <b>Pecah per baris</b>."),
              PageBreak()]

    # ---- step 2
    story += step_head(2, "Kunci jawaban & penilaian")
    story += [p("Ketik kunci jawaban berurutan. Spasi dan nomor soal boleh ikut diketik, misalnya "
                "<font name='Courier'>ABCDA BCDAB</font> atau <font name='Courier'>1A 2B 3C</font>. Bagian yang "
                "tidak dinilai boleh dikosongkan."),
              shot("03_kunci"),
              numbered(["<b>Satu kunci untuk semua LJK</b>, atau <b>kunci berbeda per kode naskah</b> bila ada "
                        "paket soal A/B/C. Untuk pilihan kedua, pilih kolom yang berisi kode naskah lalu isi kunci "
                        "untuk setiap kode.",
                        "Kotak kunci jawaban per bagian soal. Gambar kecil di kiri menunjukkan letak bagian itu di LJK. "
                        "Penghitung di kanan atas (mis. <i>60 / 60 terisi</i>) memberi tahu bila kunci kurang atau "
                        "kelebihan.",
                        "<b>Bobot benar</b> (opsional): nilai berbeda per nomor soal, mis. <font name='Courier'>"
                        "1-10:2, 11-20:1</font> artinya soal 1–10 bernilai 2 dan soal 11–20 bernilai 1.",
                        "<b>Penilaian</b>: poin untuk jawaban benar, salah, dan kosong; centang <b>Nilai dalam skala "
                        "0-100</b> untuk nilai akhir 0–100; isi <b>Nilai batas lulus</b> bila ingin tahu jumlah peserta yang lulus."]),
              note("Nilai salah boleh negatif (mis. -0,25) bila ujian memakai sistem pengurangan nilai."),
              PageBreak()]

    # ---- step 3
    story += step_head(3, "Folder LJK peserta & daftar peserta")
    story += [p("Tentukan folder berisi hasil scan LJK peserta. Ada dua cara: memilih folder yang sudah berisi hasil scan, "
                "atau scan langsung dari scanner ke folder itu."),
              shot("04_folder"),
              numbered(["<b>Pilih...</b>: memilih folder berisi file JPG/PNG/PDF. Subfolder ikut dibaca.",
                        "<b>Scan dari scanner...</b>: scan LJK langsung ke folder ini (lihat halaman berikut).",
                        "<b>Arsipkan scan lama...</b>: sebelum scan ulang, pindahkan file scan lama ke subfolder "
                        "<i>_arsip\\[tanggal jam]</i> di folder ini. File tidak dihapus dan tidak ikut diproses lagi, "
                        "jadi LJK tidak terhitung dua kali. Hasil pemeriksaan lama otomatis diganti saat diproses ulang "
                        "(Langkah 4 memilih <b>Hapus hasil lama lalu proses ulang</b>).",
                        "<b>Ingat folder ini untuk ujian berikutnya</b>: bila dicentang, folder ini dipakai lagi untuk "
                        "ujian berikutnya. Bawaannya tidak dicentang: setelah rekap diekspor atau saat <b>Ujian baru</b>, "
                        "kolom folder dikosongkan (file di folder tidak dihapus), jadi scan baru tidak tercampur dengan LJK lama.",
                        "Daftar file yang ditemukan. Pastikan jumlahnya sesuai jumlah LJK.",
                        "<b>Daftar peserta</b> (opsional): file Excel/CSV berisi No. Peserta (atau NIS/NIP/NIK), nama, dan kelompok (kelas/divisi). Pilih kolom yang "
                        "sesuai. Dengan daftar ini, nama dan kelompok otomatis masuk rekap, dan peserta yang tidak ikut "
                        "ujian ikut terdaftar."]),
              PageBreak(),
              p("Scan langsung dari scanner", "h2"),
              p("Klik <b>Scan dari scanner...</b>. Bila folder belum dipilih, program meminta Anda memilih atau membuat "
                "folder dulu. Lalu muncul jendela berikut:"),
              shot("05_scan_dialog", width=W * 0.8),
              numbered(["<b>Scanner</b>: pilih scanner. Klik <b>Cari ulang</b> bila scanner baru dinyalakan. "
                        "Coba versi <b>(TWAIN)</b> dulu; bila gagal, pakai versi <b>(WIA)</b>.",
                        "<b>Sumber</b>: <b>ADF</b> untuk scanner dengan pengumpan kertas (semua lembar di-scan "
                        "sekaligus), atau <b>Kaca (flatbed)</b> untuk satu lembar per scan. Centang <b>Dua sisi</b> "
                        "hanya bila LJK dicetak bolak-balik.",
                        "<b>Resolusi</b> 200 atau 300 dpi, <b>Abu-abu</b> atau <b>Berwarna</b>.",
                        "<b>Ukuran kertas</b>: Bawaan scanner, A4, atau F4/Folio.",
                        "Masukkan LJK ke scanner, klik <b>Mulai scan</b>. File tersimpan sebagai scan_0001.jpg, "
                        "scan_0002.jpg, dan seterusnya. File lama tidak ditimpa, jadi Anda bisa scan per tumpukan. "
                        "Klik <b>Tutup</b> bila sudah selesai."]),
              note("Bila scan langsung gagal, centang <b>Tampilkan jendela driver scanner</b> lalu scan lewat jendela "
                   "driver. Lembar yang sudah ter-scan tetap tersimpan meskipun terjadi kertas macet."),
              PageBreak()]

    # ---- step 4
    story += step_head(4, "Folder hasil & nama ujian")
    story += [p("Tentukan nama ujian dan folder tempat menyimpan hasil. Folder hasil harus <b>terpisah</b> dari folder "
                "scan; program otomatis mengusulkan folder <i>[nama folder scan]_hasil</i>."),
              shot("06_hasil"),
              numbered(["<b>Nama ujian</b>: muncul sebagai judul di rekap Excel, mis. <i>Tes Rekrutmen Batch 3</i> atau <i>PTS IPA Kelas 9A</i>.",
                        "<b>Folder hasil</b>: berisi nilai dan gambar LJK yang sudah ditandai. Klik <b>Pilih...</b> "
                        "untuk folder lain.",
                        "<b>Ingat folder ini untuk ujian berikutnya</b>: sama seperti di Langkah 3. Bila tidak dicentang, "
                        "program mengusulkan folder hasil baru di samping folder scan."]),
              p("Bila folder hasil sudah berisi hasil sebelumnya, muncul tiga pilihan:"),
              table([["Pilihan", "Kapan dipakai"],
                     ["Hapus hasil lama lalu proses ulang", "Kunci atau template diubah dan semua LJK perlu dinilai ulang."],
                     ["Simpan di subfolder baru (tanggal & jam)", "Ingin menyimpan hasil lama sebagai arsip."],
                     ["Pakai hasil yang sudah ada", "Hanya ingin melihat atau mengekspor ulang hasil sebelumnya."]],
                    [70 * mm, W - 70 * mm]),  # fmt: skip
              PageBreak()]

    # ---- step 5
    story += step_head(5, "Proses & periksa")
    story += [p("Saat langkah ini dibuka, pemeriksaan <b>belum berjalan</b>. Program menunggu sampai Anda menekan tombol."),
              shot("07_siap", caption="Tampilan sebelum diproses."),
              numbered(["Klik <b>Proses LJK</b> untuk mulai memeriksa. Kemajuan terlihat di bilah sebelahnya; "
                        "<b>Stop</b> menghentikan proses. Bila dihentikan, klik <b>Proses LJK</b> lagi dan pilih "
                        "<b>Lanjutkan sisanya</b>: LJK yang sudah diperiksa tidak diulang. Pilihan yang sama muncul "
                        "bila ada scan baru yang ditambahkan ke folder.",
                        "Jumlah LJK yang akan diproses, sudah terlihat sebelum tombol ditekan. Halaman PDF "
                        "dihitung satu per satu."]),
              PageBreak(),
              p("Membaca hasil", "h2"),
              shot("08_proses"),
              numbered(["<b>Baris merah = perlu dicek.</b> Pilih baris itu; alasannya tampil di atas gambar LJK "
                        "(lihat tabel di bawah).",
                        "Gambar LJK dari baris terpilih, dengan jawaban yang terbaca ditandai. Klik "
                        "<b>Buka di aplikasi</b> untuk melihatnya lebih besar.",
                        "<b>Koreksi...</b> (atau klik dua kali baris) untuk membetulkan bacaan. <b>Log</b> menampilkan "
                        "catatan teknis proses.",
                        "Ringkasan: jumlah LJK, yang perlu dicek, rata-rata, nilai tertinggi dan terendah."]),
              p("Alasan baris merah", "h2"),
              table([["Keterangan", "Yang perlu dilakukan"],
                     ["LJK tidak terbaca (kotak sudut/halaman tidak ditemukan)",
                      "Lembar kosong, terpotong, atau buram. Scan ulang lembar itu, lalu proses lagi."],
                     ["Jawaban ganda", "Peserta menghitamkan lebih dari satu pilihan. Periksa gambar, koreksi bila perlu."],
                     ["No. peserta kosong / tidak ada di daftar peserta", "Periksa nomor peserta di LJK, lalu betulkan lewat Koreksi."],
                     ["No. peserta dobel", "Dua LJK memakai nomor peserta yang sama. Periksa kedua lembar."],
                     ["Nama tidak ada di daftar peserta", "Cocokkan dengan daftar peserta, betulkan lewat Koreksi."],
                     ["Kode naskah tidak punya kunci jawaban", "Isi kunci untuk kode itu di Langkah 2."]],
                    [70 * mm, W - 70 * mm]),  # fmt: skip
              PageBreak(),
              p("Koreksi manual", "h2"),
              p("Bila program salah membaca (mis. bulatan tipis atau bekas hapusan), betulkan lewat jendela Koreksi:"),
              shot("09_koreksi", width=W * 0.85),
              numbered(["<b>Identitas</b>: nomor peserta, kode soal, tanggal lahir, dan isian lain yang terbaca.",
                        "<b>Jawaban</b>: satu huruf per soal. Tanda <b>-</b> berarti kosong; <b>(AC)</b> berarti lebih "
                        "dari satu tanda.",
                        "<b>Kembalikan ke hasil scan</b>: membatalkan semua koreksi untuk LJK ini.",
                        "<b>Simpan koreksi</b>: nilai langsung dihitung ulang. Baris yang sudah dikoreksi berwarna biru."]),
              note("Koreksi tetap tersimpan meskipun LJK diproses ulang, karena koreksi dicatat per file."),
              PageBreak()]

    # ---- step 6
    story += step_head(6, "Rekap & ekspor")
    story += [shot("10_rekap"),
              numbered(["Ringkasan nilai: jumlah LJK, rata-rata, tertinggi, terendah, jumlah lulus (bila nilai batas lulus diisi), "
                        "dan yang perlu dicek.",
                        "<b>Analisis butir soal</b>: persentase benar tiap soal dan sebaran jawaban A–E. Kategori: "
                        "<b>Mudah</b> (lebih dari 70% benar), <b>Sedang</b> (30–70%), <b>Sukar</b> (kurang dari 30%).",
                        "<b>Ekspor ke Excel...</b> menyimpan rekap lengkap, termasuk kolom <b>Peringkat</b>. "
                        "<b>Laporan per peserta (PDF)...</b> membuat satu halaman hasil untuk setiap peserta (identitas, "
                        "nilai, peringkat, dan jawaban dibandingkan dengan kunci) yang siap dicetak atau dibagikan. "
                        "<b>Urutan rekap &amp; laporan</b> mengatur urutan baris: nilai tertinggi dulu, kelompok lalu "
                        "nama, atau nama file. <b>Buka folder hasil</b> membuka folder "
                        "berisi gambar LJK bertanda. Di sebelahnya tertulis status ekspor: <i>Belum diekspor</i>, "
                        "<i>Sudah diekspor</i>, atau <i>Ada perubahan sejak ekspor terakhir</i> (mis. setelah koreksi).",
                        "<b>Ujian baru (template sama)</b>: mulai ujian berikutnya. Kunci, folder, dan koreksi "
                        "dikosongkan; template tetap."]),
              p("Isi file Excel", "h2"),
              table([["Sheet", "Isi"],
                     ["Rekap Nilai", "Nama, No. Peserta, kelompok, jumlah benar/salah/kosong dan nilai per bagian, "
                                     "nilai akhir, peringkat"],
                     ["Jawaban", "Jawaban setiap peserta untuk setiap soal"],
                     ["Analisis Butir", "Tingkat kesukaran dan sebaran jawaban tiap soal"],
                     ["Tidak Ikut Ujian", "Peserta di daftar peserta yang tidak punya LJK (bila daftar peserta dipakai)"]],
                    [38 * mm, W - 38 * mm]),  # fmt: skip
              PageBreak(),
              p("Selesai dan menutup program", "h2"),
              p("Klik <b>Selesai</b> di kanan bawah. Bila rekap <b>belum diekspor</b>, atau ada perubahan sejak "
                "ekspor terakhir, program bertanya dulu. Pertanyaan yang sama muncul bila jendela ditutup dengan "
                "tombol X."),
              shot("11_tutup"),
              numbered(["<b>Batal</b>: kembali ke program.",
                        "<b>Tutup tanpa ekspor</b>: hasil pemeriksaan tetap tersimpan di folder hasil, jadi rekap bisa "
                        "diekspor lain kali.",
                        "<b>Ekspor ke Excel...</b>: simpan rekap, lalu program ditutup."]),
              p("Bila rekap sudah diekspor, tombol <b>Selesai</b> membuka layar <b>Pemeriksaan selesai</b> dengan "
                "pilihan <b>Buka rekap Excel</b>, <b>Buka folder hasil</b>, <b>Ujian baru</b>, atau "
                "<b>Tutup aplikasi</b>. Semua pengaturan (template, kunci, folder) tersimpan otomatis."),
              p("Membuka ujian lama", "h2"),
              p("Setiap ujian menyimpan pengaturannya (kunci, bobot, koreksi, daftar peserta) di folder hasilnya, "
                "dalam file <i>ujian.json</i>. Untuk membuka lagi ujian yang sudah lewat, misalnya untuk ekspor "
                "ulang atau koreksi susulan, klik <b>Buka ujian lama...</b> di kiri bawah lalu pilih folder hasil "
                "ujian itu. Program langsung membuka langkah Rekap."),
              p("Bantuan", "h2"),
              p("Tombol <b>Bantuan</b> di kiri bawah berisi panduan ini, folder data &amp; log, tautan ke halaman "
                "unduhan versi terbaru, dan <b>Tentang</b> (versi dan lisensi)."),
              PageBreak()]

    # ---- troubleshooting
    story += [p("Jika ada masalah", "h1"),
              table([["Masalah", "Penyebab dan solusi"],
                     ["Program tidak mau terbuka / langsung tertutup",
                      "Tunggu 20 detik pada pembukaan pertama. Bila tetap gagal, lihat file "
                      "<i>%APPDATA%\\OMRChecker\\crash.log</i>, atau jalankan <b>OMRChecker-debug.exe</b> dari "
                      "Command Prompt untuk melihat pesan kesalahannya."],
                     ["Scanner tidak muncul di daftar",
                      "Pastikan scanner menyala dan kabel USB terpasang, driver dari produsen sudah diinstal, lalu klik "
                      "<b>Cari ulang</b>. Cek dari Command Prompt: <b>OMRChecker-debug.exe --cek-scanner</b>."],
                     ["Pesan <i>TWAINDSM.dll tidak ditemukan</i>",
                      "Driver TWAIN 64-bit belum terpasang. Pasang driver terbaru dari situs produsen, atau pakai versi "
                      "<b>(WIA)</b> scanner yang sama."],
                     ["Pesan <i>Tidak ada kertas di ADF</i>", "Masukkan LJK ke pengumpan, lalu klik Mulai scan lagi."],
                     ["Banyak LJK tidak terbaca",
                      "Periksa keempat kotak hitam di sudut ikut terscan, resolusi 200–300 dpi, dan template yang dipilih "
                      "sesuai desain LJK."],
                     ["Banyak jawaban salah baca",
                      "Peserta memakai pensil terlalu tipis, atau template kurang pas. Coba <b>Uji dengan LJK terisi</b> "
                      "di editor template, lalu perbaiki blok yang meleset."],
                     ["Nama peserta tidak muncul di rekap",
                      "Pilih daftar peserta di Langkah 3 dan pastikan kolom No. Peserta/Nama dipilih dengan benar."],
                     ["Kunci ditandai <i>kelebihan</i>",
                      "Jumlah huruf kunci melebihi jumlah soal bagian itu. Mungkin kunci untuk bagian lain."]],
                    [52 * mm, W - 52 * mm]),  # fmt: skip
              Spacer(1, 10),
              note("Untuk pengguna mahir tersedia <b>Mode lanjutan</b> (<font name='Courier'>OMRChecker.exe --lanjutan</font>) dan mode batch: "
                   "<font name='Courier'>OMRChecker.exe --process &lt;folder scan&gt; &lt;folder hasil&gt;</font>.")]

    def decorate(canvas, doc):
        if doc.page == 1:
            return
        canvas.saveState()
        canvas.setFont(body_font, 9)
        canvas.setFillColor(MUTED)
        canvas.drawString(20 * mm, 12 * mm, f"Panduan Pemindai LJK  •  OMRChecker v{VERSION}")
        canvas.drawRightString(A4[0] - 20 * mm, 12 * mm, f"Halaman {doc.page}")
        canvas.setStrokeColor(colors.HexColor("#e1e4ea"))
        canvas.line(20 * mm, 16 * mm, A4[0] - 20 * mm, 16 * mm)
        canvas.restoreState()

    doc = SimpleDocTemplate(str(out_pdf), pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm,
                            bottomMargin=22 * mm, title="Panduan Pemindai LJK", author="OMRChecker",
                            subject="Panduan langkah demi langkah")  # fmt: skip
    doc.build(story, onFirstPage=decorate, onLaterPages=decorate)
    for f in work.iterdir():
        f.unlink()
    work.rmdir()


if __name__ == "__main__":
    main(*sys.argv[1:3])
