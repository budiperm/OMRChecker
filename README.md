<p align="center">
  <img src="assets/icon_512.png" width="96" alt="Ikon Pemindai LJK">
</p>

<h1 align="center">Pemindai LJK</h1>

<p align="center">
  Aplikasi Windows berbahasa Indonesia untuk memindai, memeriksa, dan menilai LJK (Lembar Jawaban Komputer).<br>
  Dibangun di atas mesin OMR dari <a href="https://github.com/Udayraj123/OMRChecker">Udayraj123/OMRChecker</a>.
</p>

<p align="center">
  <a href="../../releases/latest"><b>Unduh versi terbaru</b></a> ·
  <a href="PANDUAN.pdf">Panduan (PDF)</a> ·
  <a href="PERSYARATAN.txt">Persyaratan sistem</a>
</p>

---

## Apa ini?

Pemindai LJK membuat pemeriksaan LJK bisa dikerjakan tanpa menyentuh kode atau berkas konfigurasi. Cukup siapkan LJK kosong, kunci jawaban, dan hasil scan lembar jawaban peserta; aplikasi menuntun Anda langkah demi langkah sampai rekap nilai siap dibuka di Excel.

Aplikasi berjalan sepenuhnya di komputer Anda (luring). Tidak perlu memasang Python atau program lain.

## Fitur

- **Wizard 6 langkah** bergaya Windows 11: pilih template, kunci jawaban, folder scan, folder hasil, proses, rekap. Pemeriksaan baru berjalan setelah tombol **Proses LJK** diklik.
- **Scan langsung dari scanner** (TWAIN atau WIA): semua lembar di ADF sekaligus, 200/300 dpi, abu-abu atau warna, A4/F4.
- **Pembuat template** dari LJK kosong (PDF atau hasil scan): bulatan, kolom identitas, dan bagian soal dideteksi otomatis, lalu bisa diedit manual.
- **Kunci jawaban** per kode naskah dan per bagian, dengan bobot nilai per soal (mis. `1-10=2, 11-20=1`).
- **Koreksi manual** hasil baca, daftar peserta dari Excel, dan analisis butir soal.
- **Ekspor rekap ke Excel**: nilai per bagian, jawaban per soal, analisis butir, dan peserta yang tidak ikut.
- **Tahan terhadap scan yang kurang rapi**: penyelarasan memakai kotak hitam di sudut LJK, lembar terbalik diputar otomatis, lembar terpotong atau kosong ditandai tanpa menggagalkan proses.

## Mulai cepat

1. Unduh `OMRChecker-windows.zip` dari [Releases](../../releases/latest), lalu ekstrak.
2. Jalankan `OMRChecker.exe`. Bila Windows SmartScreen memberi peringatan, klik **More info** lalu **Run anyway**.
3. Ikuti langkah di layar. Panduan bergambar ada di `PANDUAN.pdf` di dalam zip.

### Persyaratan singkat

- Windows 10 / 11 64-bit, RAM 4 GB (disarankan 8 GB), ruang disk 500 MB, layar minimal 1366×768.
- Untuk membuka rekap: Microsoft Excel, LibreOffice Calc, atau WPS Office.
- Scan 200–300 dpi (JPG, PNG, atau PDF); keempat kotak sudut LJK harus ikut terscan.
- Untuk scan langsung: driver scanner dari situs produsen sudah terpasang. Cek scanner yang terdeteksi dengan `OMRChecker-debug.exe --cek-scanner`.

Rincian lengkap ada di [PERSYARATAN.txt](PERSYARATAN.txt).

### Mode lain

- `OMRChecker.exe --lanjutan` membuka mode lanjutan.
- `OMRChecker.exe --process <folder scan> <folder hasil> [--template <folder template>]` memproses satu folder tanpa jendela (mode batch).

## Pengembangan

- Menjalankan dari kode: `pip install -r requirements.gui.txt` lalu `python gui.py` (Python 3.10+).
- Build exe di Windows: `build_windows.bat`; dari Linux (Docker + Wine): `./build_windows_docker.sh`.
- Rilis: naikkan `VERSION` di `wizard.py`, tulis catatan di `docs/rilis/vX.Y.Z.md`, lalu push tag `vX.Y.Z` (atau Actions → *Rilis Windows* → *Run workflow* dengan isian tag). GitHub Actions mem-build exe di Windows dan menerbitkan rilis berisi `OMRChecker-windows.zip` dan `OMRChecker-debug.exe`. Tag `vX.Y.Z-rc1` menjadi pre-release.
- Panduan PDF dibuat ulang dengan `docs/panduan/shots.py` lalu `docs/panduan/build.py`.
- Test: `pytest tests_gui -o addopts=""`. Beberapa test memakai contoh LJK asli di `tests_gui/data/` yang tidak ikut di repo; test itu otomatis dilewati.

Kode aplikasi ada di `gui.py`, `wizard.py`, `scanner.py`, `scan_dialog.py`, `template_builder.py`, `template_editor.py`, `ujian.py`, dan `theme.py`. Mesin pembaca OMR ada di `src/` dan `main.py` dari proyek asal.

## Atribusi dan lisensi

Pemindai LJK adalah fork dari **[OMRChecker](https://github.com/Udayraj123/OMRChecker)** karya [Udayraj Deshmukh](https://github.com/Udayraj123) dan para kontributornya. Pembacaan dan penilaian lembar OMR (deteksi bulatan, penyelarasan, evaluasi) memakai mesin dari proyek tersebut; aplikasi Windows, wizard, pembuat template, integrasi scanner, dan ekspor Excel ditambahkan di fork ini.

- README asli proyek OMRChecker (bahasa Inggris) disimpan di [docs/upstream/README.md](docs/upstream/README.md).
- Dokumentasi mesin OMR, format `template.json`, dan opsi baris perintah: [wiki OMRChecker](https://github.com/Udayraj123/OMRChecker/wiki).
- Daftar kontributor proyek asal: [Contributors.md](Contributors.md).

Kode dirilis di bawah [Lisensi MIT](LICENSE), sama dengan proyek asal. Pemberitahuan hak cipta asli di berkas `LICENSE` tetap dipertahankan.

Bila aplikasi ini bermanfaat, pertimbangkan juga memberi bintang atau dukungan untuk [proyek asalnya](https://github.com/Udayraj123/OMRChecker).
