"""

 OMRChecker wizard: the main window, step by step.

   1 Template LJK   2 Kunci jawaban   3 Folder LJK peserta
   4 Folder hasil   5 Proses & periksa   6 Rekap & ekspor

 Settings are kept between sessions (ujian.Exam). The previous main window
 stays available with --lanjutan ("Mode lanjutan").

"""

import base64
import multiprocessing as mp
import queue
import shutil
import subprocess
import sys
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

import theme
import ujian

APP_TITLE = "OMRChecker - Pemindai LJK"
VERSION = "1.6.0"
STEPS = ["Template LJK", "Kunci jawaban", "Folder LJK peserta", "Folder hasil",
         "Proses & periksa", "Rekap & ekspor"]  # fmt: skip
PROJECT_URL = "https://github.com/budiperm/OMRChecker"
RELEASES_URL = PROJECT_URL + "/releases"
# (file put next to the exe by the installer, file bundled in the exe as a fallback)
LICENSE_FILES = ("LISENSI.txt", "LICENSE")  # this program: GNU AGPL-3.0
NOTICE_FILES = ("PEMBERITAHUAN-PIHAK-KETIGA.txt", "LICENSE-OMRChecker-asli-MIT.txt")  # upstream MIT and others
SCAN_TYPES = (".jpg", ".jpeg", ".png", ".pdf")
ARCHIVE_DIR = ujian.ARCHIVE_DIR  # old scans moved here by "Arsipkan scan lama"; never read
RED, BLUE = "#ffd7d5", "#dbe9ff"


def scan_files(folder):
    folder = Path(folder)
    if not folder.is_dir():
        return []
    return sorted(
        (p for p in folder.rglob("*")
         if p.suffix.lower() in SCAN_TYPES and p.is_file() and ARCHIVE_DIR not in p.relative_to(folder).parts),
        key=lambda p: ujian.natural_key(str(p.relative_to(folder))),
    )


def open_path(path):
    import gui

    gui.open_path(path)


def photo_of(img_bgr, width=None, height=None, master=None):
    """Tk PhotoImage of an OpenCV image scaled to fit width/height."""
    import cv2

    h, w = img_bgr.shape[:2]
    z = min((width or w) / w, (height or h) / h)
    shown = cv2.resize(img_bgr, (max(1, int(w * z)), max(1, int(h * z))), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".png", shown)
    return tk.PhotoImage(master=master, data=base64.b64encode(buf.tobytes()))


def read_image(path):
    import cv2
    import numpy as np

    return cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_COLOR)


class ImagePreview(ttk.Frame):
    """Scrollable image with zoom buttons; fits the width by default."""

    def __init__(self, master, title=""):
        super().__init__(master)
        bar = ttk.Frame(self)
        bar.pack(fill="x")
        ttk.Button(bar, text="−", width=2, style="Small.TButton", command=lambda: self.zoom(1 / 1.25)).pack(side="left")
        ttk.Button(bar, text="+", width=2, style="Small.TButton", command=lambda: self.zoom(1.25)).pack(side="left", padx=2)
        ttk.Button(bar, text="Pas lebar", style="Small.TButton", command=lambda: self.zoom(None)).pack(side="left", padx=2)
        self.open_btn = ttk.Button(bar, text="Buka di aplikasi", style="Small.TButton", command=self.open_external)
        self.open_btn.pack(side="left")
        self.caption = tk.StringVar(value=title)
        ttk.Label(self, textvariable=self.caption, foreground=theme.MUTED).pack(anchor="w")
        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(frame, background="#e4e8ee", highlightthickness=0)
        vs = ttk.Scrollbar(frame, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=vs.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        vs.grid(row=0, column=1, sticky="ns")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        self.canvas.bind("<Configure>", lambda e: self.render())
        self.canvas.bind("<MouseWheel>", lambda e: self.canvas.yview_scroll(int(-e.delta / 40), "units"))
        self.canvas.bind("<Button-4>", lambda e: self.canvas.yview_scroll(-3, "units"))
        self.canvas.bind("<Button-5>", lambda e: self.canvas.yview_scroll(3, "units"))
        self.img = None
        self.path = None
        self.photo = None
        self.factor = None

    def show(self, path, caption=None):
        self.path = Path(path) if path else None
        self.img = read_image(self.path) if self.path and self.path.is_file() else None
        self.caption.set(caption if caption is not None else (self.path.name if self.img is not None else "Gambar tidak ditemukan."))
        self.render()

    def zoom(self, factor):
        if factor is None or self.img is None:
            self.factor = None
        else:
            self.factor = min(max((self.factor or self.fit()) * factor, 0.1), 4.0)
        self.render()

    def fit(self):
        return max(self.canvas.winfo_width(), 100) / self.img.shape[1]

    def render(self):
        self.canvas.delete("all")
        if self.img is None:
            self.photo = None
            return
        z = self.factor or self.fit()
        h, w = self.img.shape[:2]
        self.photo = photo_of(self.img, int(w * z), int(h * z), master=self.canvas)
        self.canvas.create_image(0, 0, image=self.photo, anchor="nw")
        self.canvas.configure(scrollregion=(0, 0, int(w * z), int(h * z)))

    def open_external(self):
        if not self.path:
            return
        try:
            open_path(self.path)
        except OSError as e:
            messagebox.showerror(APP_TITLE, f"Windows tidak bisa membuka gambar:\n{e}", parent=self)


class ScrollFrame(ttk.Frame):
    """A frame whose content scrolls vertically (`self.inner`)."""

    def __init__(self, master, **kw):
        super().__init__(master, **kw)
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0)
        vs = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=vs.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        self.inner = ttk.Frame(self.canvas)
        self.window = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self.window, width=e.width))
        for w in (self.canvas, self.inner):
            w.bind("<Enter>", lambda e: self.bind_all("<MouseWheel>", self.on_wheel))
            w.bind("<Leave>", lambda e: self.unbind_all("<MouseWheel>"))

    def on_wheel(self, event):
        self.canvas.yview_scroll(int(-event.delta / 40), "units")


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------


class Step(ttk.Frame):
    title = ""
    hint = ""

    def __init__(self, wizard):
        super().__init__(wizard.body)
        self.wizard = wizard
        self.exam = wizard.exam

    def enter(self):
        pass

    def leave(self):
        """Validate before moving on; return False to stay."""
        return True


class TemplateStep(Step):
    title = "Pilih template LJK"
    hint = "Template = peta posisi bulatan di lembar LJK. Buat sekali per desain LJK, lalu pakai terus."

    def __init__(self, wizard):
        super().__init__(wizard)
        # list 55 % / preview 45 %, whatever the column widths ask for
        self.columnconfigure(0, weight=11, uniform="split")
        self.columnconfigure(1, weight=9, uniform="split")
        self.rowconfigure(0, weight=1)
        left = ttk.Frame(self)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        self.tree = ttk.Treeview(left, columns=("soal", "dibuat"), show="tree headings", selectmode="browse")
        self.tree.heading("#0", text="Template")
        self.tree.heading("soal", text="Isi")
        self.tree.heading("dibuat", text="Dibuat")
        self.tree.column("#0", width=180)
        self.tree.column("soal", width=200)
        self.tree.column("dibuat", width=130, stretch=False)
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.on_select())
        self.tree.bind("<Double-1>", lambda e: self.wizard.next())
        bar = ttk.Frame(left)
        bar.pack(fill="x", pady=6)
        ttk.Button(bar, text="+  Buat baru dari LJK kosong...", command=self.create, style="Accent.TButton").pack(side="left")
        ttk.Button(bar, text="Edit...", command=self.edit).pack(side="left", padx=4)
        ttk.Button(bar, text="Impor...", command=self.import_file).pack(side="left")
        ttk.Button(bar, text="Ekspor...", command=self.export_file).pack(side="left", padx=4)
        ttk.Button(bar, text="Hapus", command=self.delete).pack(side="left")
        self.preview = ImagePreview(self)
        self.preview.grid(row=0, column=1, sticky="nsew")
        self.templates = []

    def enter(self):
        self.reload(select=self.exam.template)

    def reload(self, select=None):
        self.templates = ujian.list_templates(self.wizard.library)
        self.tree.delete(*self.tree.get_children())
        for i, t in enumerate(self.templates):
            self.tree.insert("", "end", iid=str(i), text=t.name, values=(t.summary(), t.created))
        target = next((i for i, t in enumerate(self.templates) if str(t.path) == str(select)), 0)
        if self.templates:
            self.tree.selection_set(str(target))
            self.tree.see(str(target))
        else:
            self.preview.show(None, "Belum ada template. Klik 'Buat baru dari scan LJK kosong...'.")

    def selected(self):
        sel = self.tree.selection()
        return self.templates[int(sel[0])] if sel else None

    def on_select(self):
        t = self.selected()
        if t:
            self.preview.show(t.preview, f"{t.name} — {t.summary()}")

    def editor(self, **kw):
        import gui
        from template_editor import TemplateEditor

        return TemplateEditor(
            self.wizard, on_saved=lambda folder: self.reload(select=folder),
            run_worker=gui.run_worker, library=self.wizard.library, **kw,
        )  # fmt: skip

    def create(self):
        ed = self.editor()
        ed.after(100, ed.open_scan)

    def edit(self):
        t = self.selected()
        if not t:
            return
        if not ujian.can_edit(t.path):
            messagebox.showinfo(APP_TITLE, "Template hasil impor tidak bisa diedit visual. Buat ulang dari scan LJK kosong.", parent=self)
            return
        self.editor(edit_folder=t.path)

    def import_file(self):
        """A .ljk file from another computer, or a template.json (advanced mode)."""
        path = filedialog.askopenfilename(
            parent=self, title="Impor template LJK",
            filetypes=[("Template LJK", f"*{ujian.TEMPLATE_EXT} template.json"), ("Semua file", "*.*")],
        )  # fmt: skip
        if not path:
            return
        try:
            folder = ujian.import_template_file(path, self.wizard.library)
        except (ValueError, OSError) as e:
            messagebox.showerror(APP_TITLE, str(e), parent=self)
            return
        self.reload(select=folder)

    def export_file(self):
        t = self.selected()
        if not t:
            messagebox.showinfo(APP_TITLE, "Pilih template yang akan diekspor.", parent=self)
            return
        path = filedialog.asksaveasfilename(
            parent=self, title="Ekspor template LJK", defaultextension=ujian.TEMPLATE_EXT,
            initialfile=f"{ujian.safe_name(t.name)}{ujian.TEMPLATE_EXT}",
            filetypes=[("Template LJK", f"*{ujian.TEMPLATE_EXT}")],
        )  # fmt: skip
        if not path:
            return
        try:
            ujian.export_template_file(t.path, path)
        except OSError as e:
            messagebox.showerror(APP_TITLE, f"Template tidak bisa disimpan:\n{e}", parent=self)
            return
        messagebox.showinfo(APP_TITLE, f"Template tersimpan:\n{path}\n\nDi komputer lain, buka dengan tombol 'Impor...'.",
                            parent=self)  # fmt: skip

    def delete(self):
        t = self.selected()
        if t and messagebox.askyesno(APP_TITLE, f"Hapus template '{t.name}'?", parent=self):
            ujian.delete_template(t.path)
            self.reload()

    def leave(self):
        t = self.selected()
        if not t:
            messagebox.showinfo(APP_TITLE, "Pilih atau buat template dulu.", parent=self)
            return False
        ujian.switch_template(self.exam, t.path)  # each template keeps its own keys
        try:
            if ujian.upgrade_template(t.path):  # templates saved by older versions
                t = ujian.read_library_template(t.path)
        except Exception:
            pass
        self.wizard.template = t
        return True


class KeyStep(Step):
    title = "Kunci jawaban & penilaian"
    hint = "Ketik jawaban berurutan, mis. ABCDA BCDAB … (spasi dan nomor boleh). Kosongkan bagian yang tidak dinilai."

    def __init__(self, wizard):
        super().__init__(wizard)
        top = ttk.Frame(self)
        top.pack(fill="x")
        self.mode = tk.StringVar(value="single")
        ttk.Radiobutton(top, text="Satu kunci untuk semua LJK", variable=self.mode, value="single",
                        command=self.on_mode).pack(side="left")  # fmt: skip
        ttk.Radiobutton(top, text="Kunci berbeda per kode naskah, dibaca dari kolom:", variable=self.mode,
                        value="code", command=self.on_mode).pack(side="left", padx=(16, 4))  # fmt: skip
        self.code_col = tk.StringVar()
        self.code_box = ttk.Combobox(top, textvariable=self.code_col, state="readonly", width=18)
        self.code_box.pack(side="left")
        files = ttk.Frame(self)  # keys kept for the next exam on the same LJK template
        files.pack(fill="x", pady=(6, 0))
        ttk.Button(files, text="Buka kunci...", command=self.import_keys).pack(side="left")
        ttk.Button(files, text="Simpan kunci...", command=self.export_keys).pack(side="left", padx=4)
        ttk.Label(files, text="file kunci jawaban, untuk dipakai lagi dengan template LJK yang sama",
                  foreground=theme.MUTED).pack(side="left", padx=4)  # fmt: skip

        mid = ttk.Frame(self)
        mid.pack(fill="both", expand=True, pady=8)
        self.codes_frame = ttk.LabelFrame(mid, text="Kode naskah")
        self.codes = tk.Listbox(self.codes_frame, width=14, exportselection=False)
        self.codes.pack(fill="both", expand=True, padx=4, pady=4)
        self.codes.bind("<<ListboxSelect>>", lambda e: self.show_code())
        cb = ttk.Frame(self.codes_frame)
        cb.pack(fill="x", padx=4, pady=(0, 4))
        ttk.Button(cb, text="Tambah", command=self.add_code).pack(side="left")
        ttk.Button(cb, text="Hapus", command=self.remove_code).pack(side="left", padx=4)
        keys_box = ttk.LabelFrame(mid, text="Kunci (gambar kecil = letak bagian itu di LJK)")
        keys_box.pack(side="right", fill="both", expand=True)
        self.keys_scroll = ScrollFrame(keys_box)
        self.keys_scroll.pack(fill="both", expand=True)
        self.keys_frame = self.keys_scroll.inner
        self.thumbs = []
        self.texts = {}
        self.counters = {}
        self.current_code = ujian.ALL_CODES

        sc = ttk.LabelFrame(self, text="Penilaian")
        sc.pack(fill="x")
        self.correct = tk.StringVar()
        self.incorrect = tk.StringVar()
        self.unmarked = tk.StringVar()
        self.kkm = tk.StringVar()
        self.scale = tk.BooleanVar()
        for label, var in (("Benar", self.correct), ("Salah", self.incorrect), ("Kosong", self.unmarked)):
            ttk.Label(sc, text=label).pack(side="left", padx=(8, 2), pady=6)
            ttk.Entry(sc, textvariable=var, width=6).pack(side="left")
        ttk.Checkbutton(sc, text="Nilai dalam skala 0-100", variable=self.scale).pack(side="left", padx=16)
        ttk.Label(sc, text="Nilai batas lulus (opsional):").pack(side="left")
        ttk.Entry(sc, textvariable=self.kkm, width=6).pack(side="left", padx=4)

    def enter(self):
        t = self.wizard.template
        e = self.exam
        self.code_box["values"] = t.columns
        self.mode.set("code" if e.code_column else "single")
        default = next((c for c in t.columns if "kode" in c.lower()), t.columns[0] if t.columns else "")
        self.code_col.set(e.code_column or default)
        for var, v in ((self.correct, e.correct), (self.incorrect, e.incorrect), (self.unmarked, e.unmarked)):
            var.set(f"{v:g}")
        self.kkm.set(f"{e.kkm:g}" if e.kkm else "")
        self.scale.set(e.scale_100)
        self.build_key_fields()
        self.on_mode()

    def build_key_fields(self):
        for w in self.keys_frame.winfo_children():
            w.destroy()
        self.texts, self.counters, self.weights, self.in_order, self.thumbs = {}, {}, {}, {}, []
        self.order_boxes = {}
        template = self.wizard.template
        for i, (part, labels) in enumerate(template.sections.items()):
            name = f"Bagian {part}" if part else "Jawaban"
            row = ttk.Frame(self.keys_frame)
            row.grid(row=i, column=0, sticky="ew", padx=4, pady=(6, 4))
            thumb = ujian.section_thumbnail(template.path, part)
            if thumb is not None:
                photo = photo_of(thumb, 240, 110, master=row)
                self.thumbs.append(photo)
                tk.Label(row, image=photo, relief="solid", borderwidth=1).grid(row=0, column=0, rowspan=4, sticky="nw", padx=(0, 8))
            head = ttk.Frame(row)
            head.grid(row=0, column=1, sticky="ew")
            ttk.Label(head, text=f"{name} ({len(labels)} soal)", style="Strong.TLabel").pack(side="left")
            if part and ujian.can_edit(template.path):
                ttk.Button(head, text="Ganti nama...", command=lambda p=part: self.rename(p)).pack(side="left", padx=8)
            counter = tk.StringVar()
            ttk.Label(head, textvariable=counter, foreground=theme.MUTED).pack(side="right")
            text = tk.Text(row, height=2, width=60, wrap="char", font=theme.mono(self, 11))
            text.grid(row=1, column=1, sticky="ew")
            text.bind("<KeyRelease>", lambda e, p=part: self.on_key_edit(p))
            weight = tk.StringVar(value=self.exam.weights.get(part, ""))
            weight.trace_add("write", lambda *a, p=part: self.on_weight_edit(p))
            wrow = ttk.Frame(row)
            wrow.grid(row=2, column=1, sticky="ew", pady=(2, 0))
            ttk.Label(wrow, text="Bobot benar (opsional):").pack(side="left")
            ttk.Entry(wrow, textvariable=weight, width=30).pack(side="left", padx=4)
            ttk.Label(wrow, text="mis. 1-10:2, 11-20:1", foreground=theme.MUTED).pack(side="left")
            in_order = tk.BooleanVar()  # per exam code: set in load_texts
            box = ttk.Checkbutton(row, text="Harus diisi berurutan (jawaban setelah soal kosong tidak dihitung)",
                                  variable=in_order, command=lambda p=part: self.on_in_order(p))  # fmt: skip
            box.grid(row=3, column=1, sticky="w", pady=(2, 0))
            self.order_boxes[part] = box
            row.columnconfigure(1, weight=1)
            self.texts[part], self.counters[part], self.weights[part] = text, counter, weight
            self.in_order[part] = in_order
        self.keys_frame.columnconfigure(0, weight=1)

    def rename(self, part):
        new = simpledialog.askstring(
            APP_TITLE,
            f"Nama bagian '{part}' sesuai yang tercetak di LJK (mis. Motivasi, TYPE, III):",
            parent=self, initialvalue=part,
        )
        if not new or new.strip() == part:
            return
        new = new.strip()
        if new in self.wizard.template.sections:
            messagebox.showerror(APP_TITLE, f"Bagian '{new}' sudah ada. Ganti dulu nama bagian itu.", parent=self)
            return
        typed = {p: t.get("1.0", "end") for p, t in self.texts.items()}
        try:
            mapping = ujian.rename_section(self.wizard.template.path, part, new)
        except ValueError as e:
            messagebox.showerror(APP_TITLE, str(e), parent=self)
            return
        ujian.rename_section_in_exam(self.exam, part, new, mapping)
        self.wizard.template = ujian.read_library_template(self.wizard.template.path)
        self.build_key_fields()
        self.load_texts()
        for p, t in typed.items():  # keep what was typed, under the new name
            target = new if p == part else p
            if target in self.texts and self.current_code is not None:
                self.texts[target].delete("1.0", "end")
                self.texts[target].insert("1.0", t.strip())
                self.on_key_edit(target)

    def on_weight_edit(self, part):
        text = self.weights[part].get().strip()
        if text:
            self.exam.weights[part] = text
        else:
            self.exam.weights.pop(part, None)
        self.update_counter(part)

    def on_in_order(self, part):
        if self.current_code is not None:
            ujian.set_in_order(self.exam, self.current_code, part, self.in_order[part].get())

    def on_mode(self):
        if self.mode.get() == "code":
            self.codes_frame.pack(side="left", fill="y", padx=(0, 8))
            self.code_box.configure(state="readonly")
            codes = [c for c in self.exam.keys if c != ujian.ALL_CODES]
            self.codes.delete(0, "end")
            for c in sorted(codes, key=ujian.natural_key):
                self.codes.insert("end", c)
            if codes:
                self.codes.selection_set(0)
            self.current_code = self.codes.get(0) if codes else None
        else:
            self.codes_frame.pack_forget()
            self.code_box.configure(state="disabled")
            self.current_code = ujian.ALL_CODES
        self.load_texts()

    def load_texts(self):
        keys = (ujian.keys_for(self.exam, self.current_code) or {}) if self.current_code else {}
        order = ujian.in_order_for(self.exam, self.current_code) if self.current_code else []
        for part, var in self.in_order.items():
            var.set(part in order)
            self.order_boxes[part].state(["disabled"] if self.current_code is None else ["!disabled"])
        for part, text in self.texts.items():
            text.configure(state="normal")
            text.delete("1.0", "end")
            text.insert("1.0", spaced(keys.get(part, "")))
            if self.current_code is None:
                text.configure(state="disabled")
            self.update_counter(part)

    def show_code(self):
        sel = self.codes.curselection()
        self.current_code = self.codes.get(sel[0]) if sel else None
        self.load_texts()

    def add_code(self):
        code = simpledialog.askstring(APP_TITLE, "Kode naskah (persis seperti terbaca di LJK, mis. 101 atau A):", parent=self)
        if not code or not code.strip():
            return
        code = code.strip()
        self.exam.keys.setdefault(code, {})
        self.on_mode()
        idx = list(self.codes.get(0, "end")).index(code)
        self.codes.selection_clear(0, "end")
        self.codes.selection_set(idx)
        self.show_code()

    def remove_code(self):
        if self.current_code and self.current_code != ujian.ALL_CODES:
            self.exam.keys.pop(self.current_code, None)
            if isinstance(self.exam.in_order, dict):
                self.exam.in_order.pop(self.current_code, None)
            self.on_mode()

    def on_key_edit(self, part):
        if self.current_code is None:
            return
        key, _ = ujian.parse_key(self.texts[part].get("1.0", "end"))
        keys = ujian.keys_for(self.exam, self.current_code) or {}
        keys = dict(keys)
        keys[part] = key
        self.exam.keys[self.current_code] = keys
        self.update_counter(part)

    def update_counter(self, part):
        labels = self.wizard.template.sections[part]
        key, invalid = ujian.parse_key(self.texts[part].get("1.0", "end"))
        note = f"{len(key)} / {len(labels)} terisi"
        weights, wrong = ujian.parse_weights(self.weights[part].get(), len(labels)) if part in self.weights else ({}, [])
        if weights and not wrong:
            best = sum(weights.get(n, self.exam.correct) for n in range(1, len(key) + 1))
            note += f"  •  skor maksimal {best:g}"
        if wrong:
            note += f"  — bobot: {wrong[0]}"
        if invalid:
            note += f"  — huruf tidak dikenal: {' '.join(sorted(set(invalid)))}"
        elif len(key) > len(labels):
            note += "  — kelebihan!"
        self.counters[part].set(note)

    def apply_scoring(self, e):
        """Scoring fields and the key mode from the screen into exam `e`;
        False (after telling why) when something is not filled in right."""
        try:
            e.correct, e.incorrect, e.unmarked = (float(v.get().replace(",", ".")) for v in (self.correct, self.incorrect, self.unmarked))
            e.kkm = float(self.kkm.get().replace(",", ".")) if self.kkm.get().strip() else 0
        except ValueError:
            messagebox.showerror(APP_TITLE, "Skor dan nilai batas lulus harus angka.", parent=self)
            return False
        e.scale_100 = self.scale.get()
        if self.mode.get() == "code":
            if not self.code_col.get():
                messagebox.showerror(APP_TITLE, "Pilih kolom yang berisi kode naskah.", parent=self)
                return False
            e.code_column = self.code_col.get()
        else:
            e.code_column = ""
        return True

    def export_keys(self):
        from copy import deepcopy

        e = deepcopy(self.exam)
        if not self.apply_scoring(e):
            return
        if not any(k for c in ujian.active_codes(e) for k in (ujian.keys_for(e, c) or {}).values()):
            messagebox.showinfo(APP_TITLE, "Belum ada kunci jawaban yang bisa disimpan.", parent=self)
            return
        t = self.wizard.template
        path = filedialog.asksaveasfilename(
            parent=self, title="Simpan kunci jawaban", defaultextension=ujian.KEYS_EXT,
            initialfile=f"{ujian.safe_name(self.exam.name or t.name)}{ujian.KEYS_EXT}",
            filetypes=[("Kunci jawaban", f"*{ujian.KEYS_EXT}")],
        )  # fmt: skip
        if not path:
            return
        try:
            ujian.export_keys_file(e, t.sections, path, t.name)
        except OSError as err:
            messagebox.showerror(APP_TITLE, f"Kunci jawaban tidak bisa disimpan:\n{err}", parent=self)
            return
        messagebox.showinfo(APP_TITLE, f"Kunci jawaban tersimpan:\n{path}\n\nPakai lagi dengan tombol 'Buka kunci...'.",
                            parent=self)  # fmt: skip

    def import_keys(self):
        path = filedialog.askopenfilename(
            parent=self, title="Buka kunci jawaban",
            filetypes=[("Kunci jawaban", f"*{ujian.KEYS_EXT}"), ("Semua file", "*.*")],
        )  # fmt: skip
        if not path:
            return
        e = self.exam
        if any(k for c in e.keys for k in (ujian.keys_for(e, c) or {}).values()) and not messagebox.askyesno(
            APP_TITLE, "Kunci jawaban yang sudah diisi akan diganti dengan isi file ini. Lanjutkan?", parent=self
        ):
            return
        t = self.wizard.template
        try:
            warnings = ujian.import_keys_file(path, e, t.sections, t.columns)
        except ValueError as err:
            messagebox.showerror(APP_TITLE, str(err), parent=self)
            return
        self.enter()
        if warnings:
            messagebox.showwarning(APP_TITLE, "Kunci jawaban dibuka, tapi periksa dulu:\n- " + "\n- ".join(warnings),
                                   parent=self)  # fmt: skip

    def leave(self):
        e = self.exam
        if not self.apply_scoring(e):
            return False
        # Keys and weights saved for sections of an earlier template (renamed,
        # deleted or switched) are not shown here and would never be scored.
        # The keys of the other mode (one key / per code) are kept: switching
        # back brings them back (ujian.active_codes).
        sections = self.wizard.template.sections
        for code in e.keys:
            e.keys[code] = {p: k for p, k in (ujian.keys_for(e, code) or {}).items() if p in sections}
        e.weights = {p: w for p, w in e.weights.items() if p in sections}
        if isinstance(e.in_order, list):
            e.in_order = [p for p in e.in_order if p in sections]
        else:
            e.in_order = {c: [p for p in parts if p in sections] for c, parts in e.in_order.items()
                          if c in e.keys and any(p in sections for p in parts)}  # fmt: skip
        problems = []
        for part, labels in self.wizard.template.sections.items():
            _, wrong = ujian.parse_weights(e.weights.get(part, ""), len(labels))
            problems += [f"Bobot bagian {part or '-'}: {w}" for w in wrong]
        for code in ujian.active_codes(e):
            for part, key in (ujian.keys_for(e, code) or {}).items():
                labels = sections[part]
                if len(key) > len(labels):
                    problems.append(
                        f"{'Kode ' + code + ', ' if code != ujian.ALL_CODES else ''}"
                        f"{'Bagian ' + part if part else 'Kunci'}: kunci berisi {len(key)} jawaban, "
                        f"padahal bagian ini hanya {len(labels)} soal. Lihat gambar kecil di sebelahnya: "
                        "mungkin kunci ini untuk bagian lain."
                    )
        if problems:
            messagebox.showerror(APP_TITLE, "Perbaiki dulu:\n- " + "\n- ".join(problems), parent=self)
            return False
        filled = any(k for code in ujian.active_codes(e) for k in (ujian.keys_for(e, code) or {}).values())
        if not filled and not messagebox.askyesno(
            APP_TITLE, "Belum ada kunci jawaban: LJK hanya dibaca, tidak dinilai. Lanjutkan?", parent=self
        ):
            return False
        return True


def spaced(key, group=5):
    return " ".join(key[i : i + group] for i in range(0, len(key), group))


def remember_box(parent, wizard, key):
    """'Remember this folder' checkbox, saved as an app preference (off by default)."""
    var = tk.BooleanVar(value=wizard.prefs[key])
    box = ttk.Checkbutton(parent, text="Ingat folder ini untuk ujian berikutnya", variable=var,
                          command=lambda: wizard.set_pref(key, var.get()))  # fmt: skip
    box.pack(anchor="w", padx=6, pady=(0, 4))
    box.var = var
    return box


class ScansStep(Step):
    title = "Folder LJK peserta & daftar peserta"
    hint = "Pilih folder hasil scan (JPG/PNG/PDF, subfolder ikut dibaca) atau scan langsung. Daftar peserta opsional."

    def __init__(self, wizard):
        super().__init__(wizard)
        f = ttk.LabelFrame(self, text="Folder hasil scan LJK")
        f.pack(fill="both", expand=True)
        row = ttk.Frame(f)
        row.pack(fill="x", padx=6, pady=6)
        self.folder = tk.StringVar()
        ttk.Entry(row, textvariable=self.folder).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Pilih...", command=self.pick).pack(side="left", padx=4)
        ttk.Button(row, text="Scan dari scanner...", command=self.scan_paper).pack(side="left")
        self.archive_btn = ttk.Button(row, text="Arsipkan scan lama...", command=self.archive)
        self.archive_btn.pack(side="left", padx=(4, 0))
        self.remember = remember_box(f, wizard, ujian.PREF_SCANS)
        self.count = tk.StringVar()
        ttk.Label(f, textvariable=self.count).pack(anchor="w", padx=6)
        self.files = tk.Listbox(f, height=8)
        self.files.pack(fill="both", expand=True, padx=6, pady=6)
        self.folder.trace_add("write", lambda *a: self.scan())

        s = ttk.LabelFrame(self, text="Daftar peserta (opsional): nama & kelompok diambil dari sini, peserta yang tidak ikut ketahuan")
        s.pack(fill="x", pady=(8, 0))
        row = ttk.Frame(s)
        row.pack(fill="x", padx=6, pady=6)
        self.students = tk.StringVar()
        ttk.Entry(row, textvariable=self.students).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Pilih Excel/CSV...", command=self.pick_students).pack(side="left", padx=4)
        ttk.Button(row, text="Tanpa daftar", command=lambda: self.students.set("")).pack(side="left")
        cols = ttk.Frame(s)
        cols.pack(fill="x", padx=6, pady=(0, 6))
        self.col_vars = {}
        self.col_boxes = {}
        for i, (key, label) in enumerate((("nis", "Kolom No. Peserta"), ("nama", "Kolom Nama"), ("kelas", "Kolom Kelompok"))):
            ttk.Label(cols, text=label).grid(row=0, column=i, sticky="w", padx=(0, 12))
            var = tk.StringVar()
            box = ttk.Combobox(cols, textvariable=var, state="readonly", width=15)
            box.grid(row=1, column=i, sticky="ew", padx=(0, 12))
            cols.columnconfigure(i, weight=1, uniform="cols")
            self.col_vars[key], self.col_boxes[key] = var, box
            box.bind("<<ComboboxSelected>>", lambda e: self.list_check())
        self.student_info = tk.StringVar()
        ttk.Label(s, textvariable=self.student_info, foreground=theme.MUTED).pack(anchor="w", padx=6, pady=(0, 6))
        self.students.trace_add("write", lambda *a: self.read_students())

    def enter(self):
        self.folder.set(self.exam.scans_dir)
        self.students.set(self.exam.students_file)
        for k, v in self.exam.students_cols.items():
            if k in self.col_vars and v:
                self.col_vars[k].set(v)

    def pick(self):
        d = filedialog.askdirectory(parent=self, title="Folder hasil scan LJK peserta", initialdir=self.folder.get() or None)
        if d:
            self.folder.set(d)

    def scan_paper(self):
        import scan_dialog

        folder = self.folder.get().strip()
        if not folder:
            folder = filedialog.askdirectory(parent=self, title="Folder untuk menyimpan hasil scan LJK", mustexist=False)
            if not folder:
                return
        try:
            Path(folder).mkdir(parents=True, exist_ok=True)
        except OSError as e:
            messagebox.showerror(APP_TITLE, f"Folder tidak bisa dibuat:\n{e}", parent=self)
            return
        self.folder.set(str(Path(folder)))
        dialog = scan_dialog.ScanDialog(self, self.folder.get(), on_page=lambda path: self.scan())
        self.wait_window(dialog)
        self.scan()

    def scan(self):
        files = scan_files(self.folder.get())
        self.files.delete(0, "end")
        for p in files[:500]:
            self.files.insert("end", str(p.relative_to(self.folder.get())))
        pdfs = sum(p.suffix.lower() == ".pdf" for p in files)
        self.count.set(f"{len(files)} file ditemukan ({len(files) - pdfs} gambar, {pdfs} PDF)" if self.folder.get() else "")
        self.archive_btn.configure(state="normal" if files else "disabled")

    def archive(self):
        """Move the scans out of the way (into _arsip/<date time>) so a re-scan
        starts clean, and make the next run replace the old results."""
        folder = self.folder.get().strip()
        files = scan_files(folder)
        if not files:
            return
        stamp = time.strftime("%Y-%m-%d %H.%M.%S")
        dest = Path(folder) / ARCHIVE_DIR / stamp
        choice = ChoiceDialog.ask(
            self, "Arsipkan scan lama?",
            f"{len(files)} file scan di folder ini akan dipindah ke subfolder {ARCHIVE_DIR}\\{stamp}.",
            [("batal", "Batal", False), ("arsip", "Arsipkan", True)],
            detail="File tidak dihapus dan tidak ikut diproses lagi. Hasil pemeriksaan lama akan diganti "
                   "saat LJK diproses ulang.",
        )  # fmt: skip
        if choice != "arsip":
            return
        moved = 0
        try:
            for p in files:
                target = dest / p.relative_to(folder)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(p), str(target))
                moved += 1
        except OSError as e:
            messagebox.showerror(APP_TITLE, f"Gagal memindahkan file scan ({moved} dari {len(files)} sudah dipindah):\n{e}",
                                 parent=self)  # fmt: skip
        self.scan()
        if moved:
            ujian.clear_corrections(self.exam)  # keyed by file name: a new scan_0001.jpg is another sheet
            self.wizard.scans_archived = True

    def pick_students(self):
        f = filedialog.askopenfilename(parent=self, title="Daftar peserta",
                                       filetypes=[("Excel / CSV", "*.xlsx *.xls *.csv"), ("Semua file", "*.*")])  # fmt: skip
        if f:
            self.students.set(f)

    def read_students(self):
        path = self.students.get().strip()
        for box in self.col_boxes.values():
            box["values"] = []
        if not path:
            self.student_info.set("")
            return
        try:
            headers, rows = ujian.read_table(path)
        except Exception as e:
            self.student_info.set(f"Gagal membaca: {e}")
            return
        guess = ujian.guess_student_columns(headers)
        for k, box in self.col_boxes.items():
            box["values"] = [""] + headers
            if self.col_vars[k].get() not in headers:
                self.col_vars[k].set(guess.get(k, ""))
        self.list_check()

    def list_check(self):
        """Count the participants and warn about No. Peserta listed twice
        (only the first of them can be matched to a sheet)."""
        path = self.students.get().strip()
        cols = {k: v.get() for k, v in self.col_vars.items() if v.get()}
        try:
            students, _, _ = ujian.load_students(path, cols)
        except Exception:  # no usable column chosen yet: leave() explains
            self.student_info.set("")
            return
        dup = ujian.duplicate_numbers(students)
        more = f" Perhatian: No. Peserta dobel di daftar: {', '.join(dup[:5])}{' ...' if len(dup) > 5 else ''}" if dup else ""
        self.student_info.set(f"{len(students)} peserta di daftar.{more}")

    def leave(self):
        folder = self.folder.get().strip()
        if not folder or not Path(folder).is_dir():
            messagebox.showerror(APP_TITLE, "Pilih folder hasil scan LJK.", parent=self)
            return False
        if not scan_files(folder):
            messagebox.showerror(APP_TITLE, "Tidak ada file JPG/PNG/PDF di folder ini.", parent=self)
            return False
        if Path(folder).resolve() != Path(self.exam.scans_dir or ".").resolve():
            ujian.clear_corrections(self.exam)
            if not self.wizard.prefs[ujian.PREF_OUTPUT]:
                self.exam.output_dir = ""
        self.exam.scans_dir = str(Path(folder))
        path = self.students.get().strip()
        cols = {k: v.get() for k, v in self.col_vars.items() if v.get()}
        if path:
            if not cols.get("nis") and not cols.get("nama"):
                messagebox.showerror(APP_TITLE, "Pilih kolom No. Peserta atau Nama di daftar peserta.", parent=self)
                return False
            try:
                ujian.load_students(path, cols)
            except Exception as e:
                messagebox.showerror(APP_TITLE, f"Daftar peserta tidak bisa dibaca:\n{e}", parent=self)
                return False
        self.exam.students_file, self.exam.students_cols = path, cols if path else {}
        return True


class OutputStep(Step):
    title = "Folder hasil & nama ujian"
    hint = "Hasil (nilai, gambar LJK bertanda) disimpan di folder ini, terpisah dari scan."

    def __init__(self, wizard):
        super().__init__(wizard)
        f = ttk.LabelFrame(self, text="Nama ujian (judul rekap)")
        f.pack(fill="x")
        self.name = tk.StringVar()
        ttk.Entry(f, textvariable=self.name).pack(fill="x", padx=6, pady=6)
        f = ttk.LabelFrame(self, text="Folder hasil")
        f.pack(fill="x", pady=8)
        row = ttk.Frame(f)
        row.pack(fill="x", padx=6, pady=6)
        self.folder = tk.StringVar()
        ttk.Entry(row, textvariable=self.folder).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Pilih...", command=self.pick).pack(side="left", padx=4)
        self.remember = remember_box(f, wizard, ujian.PREF_OUTPUT)
        self.existing = tk.StringVar()
        ttk.Label(f, textvariable=self.existing, foreground=theme.WARN).pack(anchor="w", padx=6)
        self.policy = tk.StringVar(value="replace")
        self.replace_rb = ttk.Radiobutton(f, text="Hapus hasil lama lalu proses ulang", variable=self.policy, value="replace")
        self.new_rb = ttk.Radiobutton(f, text="Simpan di subfolder baru (tanggal & jam)", variable=self.policy, value="new")
        self.keep_rb = ttk.Radiobutton(f, text="Pakai hasil yang sudah ada (tanpa proses ulang)", variable=self.policy, value="keep")
        self.folder.trace_add("write", lambda *a: self.check())

    def enter(self):
        e = self.exam
        default = str(Path(e.scans_dir).parent / (Path(e.scans_dir).name + "_hasil"))
        self.folder.set(e.output_dir or default)
        self.name.set(e.name or Path(e.scans_dir).name)
        if self.wizard.scans_archived:  # results of the archived scans would double up
            self.policy.set("replace")

    def pick(self):
        d = filedialog.askdirectory(parent=self, title="Folder hasil")
        if d:
            self.folder.set(d)

    def has_results(self):
        out = Path(self.folder.get().strip() or ".")
        return out.is_dir() and any(ujian.current(out, "Results/Results_*.csv"))

    def check(self):
        for rb in (self.replace_rb, self.new_rb, self.keep_rb):
            rb.pack_forget()
        if self.has_results():
            self.existing.set("Folder ini sudah berisi hasil sebelumnya:")
            for rb in (self.keep_rb, self.replace_rb, self.new_rb):
                rb.pack(anchor="w", padx=18)
            if self.policy.get() not in ("keep", "replace", "new"):
                self.policy.set("keep")
        else:
            self.existing.set("")

    def leave(self):
        import gui

        out = self.folder.get().strip()
        scans = Path(self.exam.scans_dir).resolve()
        if not out:
            messagebox.showerror(APP_TITLE, "Pilih folder hasil.", parent=self)
            return False
        out_p = Path(out).resolve()
        if out_p == scans or scans in out_p.parents or out_p in scans.parents:
            messagebox.showerror(APP_TITLE, "Folder hasil harus terpisah dari folder scan (tidak di dalamnya dan tidak memuatnya).", parent=self)
            return False
        self.wizard.reprocess = True
        if self.has_results():
            policy = self.policy.get()
            if policy == "keep":
                self.wizard.reprocess = False
            elif policy == "new":
                out_p = out_p / time.strftime("%Y-%m-%d %H.%M")
            elif policy == "replace":
                stray = gui.foreign_files(out_p)
                if stray:
                    messagebox.showerror(APP_TITLE, "Folder hasil berisi file lain (bukan hasil OMRChecker), tidak dihapus:\n"
                                         + "\n".join(str(p.relative_to(out_p)) for p in stray[:5]), parent=self)  # fmt: skip
                    return False
        if str(out_p) != self.exam.output_dir:
            ujian.clear_corrections(self.exam)
        self.exam.output_dir = str(out_p)
        self.exam.name = self.name.get().strip()
        self.wizard.clear_old = self.has_results() and self.policy.get() == "replace"
        self.wizard.scans_archived = False
        return True


class ProcessStep(Step):
    title = "Proses & periksa"
    hint = "Baris merah perlu dicek. Pilih baris untuk melihat LJK-nya; 'Koreksi' untuk membetulkan bacaan."

    def __init__(self, wizard):
        super().__init__(wizard)
        top = ttk.Frame(self)
        top.pack(fill="x")
        self.run_btn = ttk.Button(top, text="▶  Proses LJK", command=self.start, style="Accent.TButton")
        self.run_btn.pack(side="left")
        self.stop_btn = ttk.Button(top, text="■  Stop", command=self.stop, state="disabled")
        self.stop_btn.pack(side="left", padx=4)
        self.progress = ttk.Progressbar(top, length=260)
        self.progress.pack(side="left", padx=8)
        self.progress_text = tk.StringVar()
        ttk.Label(top, textvariable=self.progress_text).pack(side="left")
        ttk.Button(top, text="Log", command=self.show_log).pack(side="right")
        ttk.Button(top, text="Koreksi...", command=self.correct).pack(side="right", padx=4)

        split = ttk.Panedwindow(self, orient="horizontal")
        split.pack(fill="both", expand=True, pady=6)
        self.split = split
        table = ttk.Frame(split, width=400, height=200)
        table.grid_propagate(False)
        split.add(table, weight=3)
        self.tree = ttk.Treeview(table, show="headings", selectmode="browse")
        vs = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        hs = ttk.Scrollbar(table, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vs.grid(row=0, column=1, sticky="ns")
        hs.grid(row=1, column=0, sticky="ew")
        table.rowconfigure(0, weight=1)
        table.columnconfigure(0, weight=1)
        self.tree.tag_configure("flag", background=RED)
        self.tree.tag_configure("fixed", background=BLUE)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.on_select())
        self.tree.bind("<Double-1>", lambda e: self.correct())
        self.preview = ImagePreview(split)
        split.add(self.preview, weight=2)
        split.bind("<Configure>", self.place_sash)
        split.bind("<ButtonRelease-1>", lambda e: setattr(self, "user_sash", True))
        self.user_sash = False
        self.summary = tk.StringVar()
        ttk.Label(self, textvariable=self.summary).pack(anchor="w")
        self.proc = None
        self.q = None
        self.log = []
        self.results = []

    def place_sash(self, _e=None):
        w = self.split.winfo_width()
        if not self.user_sash and w > 300:
            self.split.sashpos(0, int(w * 0.6))

    def enter(self):
        # never starts by itself: the user clicks "Proses LJK" when ready
        self.total = ujian.count_sheets(scan_files(self.exam.scans_dir))
        self.load_results()
        if self.proc is None:  # how many sheets there are, before anything runs
            self.progress.configure(maximum=max(1, self.total), value=0)
            self.progress_text.set(f"{self.total} LJK akan diproses" if self.wizard.reprocess
                                   else f"{self.total} LJK di folder scan")  # fmt: skip
        if self.wizard.reprocess:
            old = " Hasil lama di folder ini akan diganti." if self.results and self.wizard.clear_old else ""
            self.summary.set(f"Siap memeriksa {self.total} LJK. Klik '▶ Proses LJK' untuk mulai.{old}")

    def start(self):
        if self.proc and self.proc.is_alive():
            return
        import gui

        out = Path(self.exam.output_dir)
        if self.wizard.clear_old and out.is_dir():
            shutil.rmtree(out)
            self.wizard.clear_old = False
        skip = ujian.done_sheets(out)
        if skip and len(skip) < self.total:  # an earlier run was stopped part way
            choice = ChoiceDialog.ask(
                self, "Lanjutkan pemeriksaan?",
                f"{len(skip)} dari {self.total} LJK sudah diperiksa sebelumnya.",
                [("batal", "Batal", False), ("ulang", "Periksa ulang semua", False),
                 ("lanjut", f"Lanjutkan sisanya ({self.total - len(skip)})", True)],
                detail="Koreksi manual yang sudah dibuat tetap tersimpan.",
            )  # fmt: skip
            if choice in (None, "batal"):
                return
            if choice == "ulang":
                for entry in out.iterdir():  # results only: ujian.json and foreign files stay
                    if entry.name == ujian.EXAM_FILE:
                        continue
                    if entry.is_dir() and (entry.name in gui.RESULT_ENTRIES or not gui.foreign_files(entry)):
                        shutil.rmtree(entry)
                    elif entry.name in gui.RESULT_ENTRIES:
                        entry.unlink()
                skip = []
        else:
            skip = []  # everything (or nothing) read before: read it all again
        self.wizard.reprocess = False  # corrections stay: they are keyed by file
        self.log = []
        self.done_count = 0
        self.progress.configure(maximum=max(1, self.total), value=0)
        self.progress_text.set(f"0 / {self.total}")
        ctx = mp.get_context("spawn")
        self.q = ctx.Queue()
        options = {"template_dir": self.exam.template, "skip": skip}
        self.proc = ctx.Process(target=gui.run_worker, args=(self.q, self.exam.scans_dir, str(out), options), daemon=True)
        self.proc.start()
        self.run_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.wizard.set_busy(True)
        self.after(150, self.poll)

    def stop(self):
        if self.proc and self.proc.is_alive():
            self.proc.terminate()
        self.finish(False, None)

    def poll(self):
        done = None
        try:
            while True:
                msg = self.q.get_nowait()
                if msg[0] == "log":
                    self.log.append(msg[1])
                elif msg[0] == "progress":
                    self.done_count = msg[1]
                else:
                    done = msg
        except (queue.Empty, EOFError, OSError):
            pass
        self.progress.configure(value=min(self.done_count, self.total))
        self.progress_text.set(f"{self.done_count} / {self.total}")
        if done:
            self.finish(done[1], done[2])
        elif self.proc and not self.proc.is_alive():
            self.finish(False, f"Proses keluar tidak normal (kode {self.proc.exitcode}).")
        elif self.proc:
            self.after(150, self.poll)

    def finish(self, ok, message):
        if self.proc is None:
            return
        self.proc = None
        self.run_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.wizard.set_busy(False)
        if ok:
            self.progress.configure(value=self.total)
            self.exam.save(self.wizard.settings)  # ujian.json in the (new or emptied) output folder
            self.load_results()
            if not self.results:
                messagebox.showwarning(
                    APP_TITLE,
                    f"Proses selesai, tetapi tidak ada LJK yang terbaca dari {self.total} file.\n\n"
                    "Klik 'Log' untuk melihat rinciannya.",
                    parent=self,
                )
        elif message is None:  # stopped by the user
            self.load_results()
            done = len(ujian.done_sheets(self.exam.output_dir))
            self.progress_text.set("Dihentikan")
            self.summary.set(f"Dihentikan: {done} dari {self.total} LJK sudah diperiksa. "
                             "Klik '▶ Proses LJK' untuk melanjutkan sisanya.")  # fmt: skip
        else:
            self.progress_text.set("Gagal")
            messagebox.showerror(APP_TITLE, f"Proses gagal:\n{message}", parent=self)

    def columns(self):
        """No, File, the template's identity fields (Nama from the student
        list when there is one), Kelompok, Benar, Nilai, Catatan."""
        ident = [c for c in self.wizard.template.columns]
        if "Nama" not in ident:
            ident.insert(0, "Nama")
        cols = [("No", 40), ("File", 150)] + [(c, 170 if c == "Nama" else 100) for c in ident]
        if self.wizard.students:
            cols.append(("Kelompok", 80))
        cols += [("Benar", 60), ("Nilai", 60), ("Catatan", 340)]
        return cols

    def row_values(self, i, r):
        values = [i + 1, r.file_id]
        for c in [c for c, _ in self.columns()][2:]:
            if c == "Nama":
                values.append(r.name)
            elif c == "Kelompok":
                values.append(r.kelas)
            elif c == "Benar":
                values.append(r.correct if r.grade is not None else "")
            elif c == "Nilai":
                values.append("" if r.grade is None else f"{r.grade:g}")
            elif c == "Catatan":
                values.append("; ".join(r.flags))
            else:
                values.append(r.info.get(c, "").strip())
        return values

    def load_results(self):
        self.results = self.wizard.compute_results()
        cols = self.columns()
        self.tree["columns"] = [c for c, _ in cols]
        for c, w in cols:
            self.tree.heading(c, text=c)
            self.tree.column(c, width=w, anchor="w" if c in ("File", "Nama", "Catatan") else "center", stretch=False)
        self.tree.delete(*self.tree.get_children())
        for i, r in enumerate(self.results):
            tag = "flag" if r.flags else "fixed" if r.corrected else ""
            self.tree.insert("", "end", iid=str(i), tags=(tag,), values=self.row_values(i, r))
        s = ujian.summary(self.results)
        if self.results:
            self.summary.set(
                f"{s['peserta']} LJK  •  perlu dicek: {s['perlu_dicek']}  •  rata-rata: {s['rata']}  "
                f"•  tertinggi: {s['tertinggi']}  •  terendah: {s['terendah']}"
            )
            self.tree.selection_set("0")
        else:
            self.summary.set("Belum ada hasil. Klik 'Proses LJK'.")
            self.preview.show(None, "")
        self.after_idle(self.place_sash)

    def selected(self):
        sel = self.tree.selection()
        return self.results[int(sel[0])] if sel and int(sel[0]) < len(self.results) else None

    def on_select(self):
        r = self.selected()
        if r:
            self.preview.show(r.image, f"{r.file_id}" + (f" — {'; '.join(r.flags)}" if r.flags else ""))

    def correct(self):
        r = self.selected()
        if r is None or r.unreadable:
            if r is not None:
                messagebox.showinfo(APP_TITLE, "LJK ini tidak terbaca sama sekali. Scan ulang lalu proses lagi.", parent=self)
            return
        CorrectionDialog(self, r, self.wizard.template.sections, self.exam, on_done=self.after_correction)

    def after_correction(self):
        sel = self.tree.selection()
        fid = self.results[int(sel[0])].file_id if sel else None
        self.load_results()
        for i, r in enumerate(self.results):
            if r.file_id == fid:
                self.tree.selection_set(str(i))
                self.tree.see(str(i))

    def show_log(self):
        win = tk.Toplevel(self)
        win.title("Log proses")
        win.geometry("900x500")
        text = tk.Text(win, wrap="none", font=theme.mono(self, 9))
        text.insert("1.0", "".join(self.log) or "Belum ada log.")
        text.pack(fill="both", expand=True)

    def leave(self):
        if self.proc is not None:
            messagebox.showinfo(APP_TITLE, "Tunggu sampai proses selesai.", parent=self)
            return False
        if not self.results:
            messagebox.showinfo(APP_TITLE, "Belum ada hasil. Klik 'Proses LJK'.", parent=self)
            return False
        return True


def answers_text(answers, labels):
    """'A B - (AC) ...' : '-' blank, (..) several marks."""
    out = []
    for q in labels:
        a = answers.get(q, "")
        out.append("-" if a == "" else a if len(a) == 1 else f"({a})")
    return " ".join(out)


def parse_answers_text(text):
    tokens, i, text = [], 0, text.upper()
    while i < len(text):
        ch = text[i]
        if ch == "(":
            j = text.find(")", i)
            if j < 0:
                raise ValueError("kurung ( tidak ditutup")
            tokens.append(text[i + 1 : j].replace(" ", ""))
            i = j + 1
            continue
        if ch in "-.":
            tokens.append("")
        elif ch.isalpha():
            tokens.append(ch)
        i += 1
    return tokens


class CorrectionDialog(tk.Toplevel):
    """Fix what was read for one sheet; stored as corrections in the exam."""

    def __init__(self, master, result, sections, exam, on_done):
        super().__init__(master)
        self.title(f"Koreksi — {result.file_id}")
        self.geometry(f"900x{min(720, self.winfo_screenheight() - 100)}")
        self.result, self.sections, self.exam, self.on_done = result, sections, exam, on_done
        # Buttons first, at the bottom, so a tall sheet never pushes them off-screen
        bar = ttk.Frame(self)
        bar.pack(side="bottom", fill="x", padx=8, pady=8)
        ttk.Button(bar, text="Simpan koreksi", command=self.save, style="Accent.TButton").pack(side="right")
        ttk.Button(bar, text="Batal", command=self.destroy).pack(side="right", padx=4)
        ttk.Button(bar, text="Kembalikan ke hasil scan", command=self.revert).pack(side="left")
        ttk.Label(self, text="Ubah yang salah baca. '-' = kosong, (AC) = lebih dari satu tanda.",
                  foreground=theme.MUTED).pack(anchor="w", padx=8, pady=6)  # fmt: skip
        ident = ttk.LabelFrame(self, text="Identitas")
        ident.pack(fill="x", padx=8)
        self.fields = {}
        for i, (k, v) in enumerate(result.info.items()):
            ttk.Label(ident, text=k).grid(row=i // 3, column=(i % 3) * 2, sticky="w", padx=4, pady=3)
            var = tk.StringVar(value=v)
            ttk.Entry(ident, textvariable=var, width=24).grid(row=i // 3, column=(i % 3) * 2 + 1, padx=4)
            self.fields[k] = var
        box = ttk.LabelFrame(self, text="Jawaban")
        box.pack(fill="both", expand=True, padx=8, pady=6)
        scroll = ScrollFrame(box)
        scroll.pack(fill="both", expand=True)
        ans = scroll.inner
        self.texts = {}
        for part, labels in sections.items():
            ttk.Label(ans, text=f"Bagian {part} ({len(labels)} soal)" if part else f"Jawaban ({len(labels)} soal)").pack(anchor="w", padx=4)
            t = tk.Text(ans, height=3, wrap="word", font=theme.mono(self, 10))
            t.insert("1.0", answers_text(result.answers, labels))
            t.pack(fill="x", padx=4, pady=(0, 6))
            self.texts[part] = t
        self.transient(master)

    def save(self):
        scanned = self.result.raw  # as read from the scan, before any correction
        fixes = {}
        for k, var in self.fields.items():
            fixes[k] = var.get().strip()
        for part, labels in self.sections.items():
            try:
                tokens = parse_answers_text(self.texts[part].get("1.0", "end"))
            except ValueError as e:
                messagebox.showerror(APP_TITLE, f"Bagian {part}: {e}", parent=self)
                return
            if len(tokens) != len(labels):
                messagebox.showerror(APP_TITLE, f"{'Bagian ' + part if part else 'Jawaban'}: {len(tokens)} isian untuk {len(labels)} soal.", parent=self)
                return
            fixes.update(dict(zip(labels, tokens)))
        changed = {k: v for k, v in fixes.items() if scanned.get(k, "") != v}
        if changed:
            self.exam.corrections[self.result.file_id] = changed
        else:
            self.exam.corrections.pop(self.result.file_id, None)
        self.finish()

    def revert(self):
        self.exam.corrections.pop(self.result.file_id, None)
        self.finish()

    def finish(self):
        wizard = self.master.wizard
        self.exam.save(wizard.settings)
        self.destroy()
        self.on_done()


class ExportStep(Step):
    title = "Rekap & ekspor"
    hint = "Ekspor rekap ke Excel (nilai per bagian, jawaban per soal, analisis butir, peserta tidak ikut) atau ke CSV untuk program lain."

    def __init__(self, wizard):
        super().__init__(wizard)
        self.stats = tk.StringVar()
        ttk.Label(self, textvariable=self.stats, style="Big.TLabel").pack(anchor="w", pady=(0, 6))
        self.absent_row = ttk.Frame(self)
        self.absent_info = tk.StringVar()
        ttk.Label(self.absent_row, textvariable=self.absent_info).pack(side="left")
        ttk.Button(self.absent_row, text="Lihat daftarnya...", command=self.show_absent).pack(side="left", padx=8)
        f = ttk.LabelFrame(self, text="Analisis butir soal")
        f.pack(fill="both", expand=True)
        self.item_legend = tk.StringVar()
        ttk.Label(f, textvariable=self.item_legend, foreground=theme.MUTED).pack(side="bottom", anchor="w", padx=6)
        self.item_note = tk.StringVar()
        ttk.Label(f, textvariable=self.item_note, foreground=theme.WARN).pack(side="bottom", anchor="w", padx=6)
        cols = ("kode", "soal", "kunci", "bobot", "benar", "kategori", "daya_beda", "terbanyak",
                "A", "B", "C", "D", "E", "Kosong", "Ganda")  # fmt: skip
        names = {"kode": "Kode", "benar": "% Benar", "daya_beda": "Daya beda"}
        self.tree = ttk.Treeview(f, columns=cols, show="headings")
        for c in cols:
            self.tree.heading(c, text=names.get(c, c.capitalize() if len(c) > 1 else c))
            self.tree.column(c, width=80 if c in ("soal", "kunci", "kategori", "daya_beda", "terbanyak") else 55,
                             anchor="center")  # fmt: skip
        self.tree.tag_configure("check", background="#FFE699")
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.show_item_note())
        vs = ttk.Scrollbar(f, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vs.pack(side="left", fill="y")
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=8)
        ttk.Button(bar, text="Ekspor ke Excel...", command=self.export, style="Accent.TButton").pack(side="left")
        ttk.Button(bar, text="Ekspor CSV...", command=self.export_csv).pack(side="left", padx=(6, 0))
        ttk.Button(bar, text="Ekspor lanjutan...", command=self.export_advanced).pack(side="left", padx=(6, 0))
        ttk.Button(bar, text="Laporan per peserta (PDF)...", command=self.export_reports).pack(side="left", padx=6)
        order = ttk.Frame(self)  # second row: the export buttons fill the first one on a small window
        order.pack(fill="x")
        ttk.Label(order, text="Urutan rekap & laporan:").pack(side="left")
        self.order = tk.StringVar()
        self.order_box = ttk.Combobox(order, textvariable=self.order, state="readonly", width=24,
                                      values=list(ujian.RANK_ORDERS.values()))  # fmt: skip
        self.order_box.pack(side="left", padx=6)
        ttk.Button(order, text="Ujian baru (template sama)", command=self.new_exam).pack(side="right")
        ttk.Button(order, text="Buka folder hasil", command=lambda: open_path(self.exam.output_dir)).pack(side="right", padx=6)
        self.export_info = tk.StringVar()
        self.export_label = ttk.Label(self, textvariable=self.export_info, foreground=theme.MUTED)
        self.export_label.pack(anchor="w", pady=(6, 0))
        self.order_box.bind("<<ComboboxSelected>>", lambda e: self.on_order())

    def show_export_status(self):
        if not self.wizard.export_pending():
            self.export_info.set(f"✓ Sudah diekspor: {Path(self.exam.exported_file).name}" if self.exam.exported_file else "")
            self.export_label.configure(foreground=theme.DONE)
        elif self.exam.exported_file:
            self.export_info.set("Ada perubahan sejak ekspor terakhir: ekspor ulang")
            self.export_label.configure(foreground=theme.WARN)
        else:
            self.export_info.set("Belum diekspor")
            self.export_label.configure(foreground=theme.WARN)

    def on_order(self):
        label = self.order.get()
        self.exam.rekap_order = next((k for k, v in ujian.RANK_ORDERS.items() if v == label), "nama")
        self.exam.save(self.wizard.settings)
        self.show_export_status()

    def export_reports(self):
        choice = ChoiceDialog.ask(
            self, "Laporan per peserta (PDF)", "Satu halaman per peserta: nilai, jawaban, dan kunci.",
            [("batal", "Batal", False), ("pisah", "Satu file per peserta", False), ("satu", "Satu file", True)],
            detail="Satu file per peserta cocok untuk dikirim ke masing-masing peserta; nama file berisi "
                   "No. Peserta dan nama.",
        )  # fmt: skip
        if choice not in ("satu", "pisah"):
            return
        name = ujian.safe_name(f"Laporan {self.exam.name or 'Ujian'}")
        if choice == "satu":
            path = filedialog.asksaveasfilename(
                parent=self, title="Simpan laporan per peserta", defaultextension=".pdf",
                initialdir=self.exam.output_dir, initialfile=f"{name}.pdf", filetypes=[("PDF", "*.pdf")],
            )  # fmt: skip
        else:
            folder = filedialog.askdirectory(parent=self, title="Folder untuk laporan per peserta",
                                             initialdir=self.exam.output_dir or None, mustexist=False)  # fmt: skip
            path = str(Path(folder) / name) if folder else ""
        if not path:
            return
        results = self.wizard.compute_results()
        try:
            ujian.export_reports_pdf(path, results, self.exam, self.wizard.template.sections, self.exam.name,
                                     separate=choice == "pisah")  # fmt: skip
        except (OSError, RuntimeError) as e:
            messagebox.showerror(APP_TITLE, f"Laporan tidak bisa disimpan (mungkin sedang dibuka?):\n{e}", parent=self)
            return
        if choice == "pisah":
            if messagebox.askyesno(APP_TITLE, f"Laporan tersimpan di folder:\n{path}\n\nBuka foldernya?", parent=self):
                open_path(path)
        elif messagebox.askyesno(APP_TITLE, "Laporan tersimpan. Buka sekarang?", parent=self):
            open_file(path, self)

    def enter(self):
        self.order.set(ujian.RANK_ORDERS.get(self.exam.rekap_order, ujian.RANK_ORDERS["nama"]))
        results = self.wizard.compute_results()
        self.results = results
        s = ujian.summary(results)
        missing = ""
        self.absent = ujian.absent_students(results, self.wizard.students) if self.wizard.students else []
        if self.wizard.students:
            missing = f"   •   tidak ikut: {len(self.absent)}"
        if self.absent:
            self.absent_info.set(f"{len(self.absent)} peserta di daftar tidak ada LJK-nya.")
            self.absent_row.pack(fill="x", pady=(0, 6), before=self.tree.master)
        else:
            self.absent_row.pack_forget()
        kkm = f"   •   lulus (batas {self.exam.kkm:g}): {s['tuntas']}" if self.exam.kkm else ""
        self.stats.set(f"{s['peserta']} LJK   •   rata-rata {s['rata']}   •   tertinggi {s['tertinggi']}   "
                       f"•   terendah {s['terendah']}{kkm}{missing}   •   perlu dicek: {s['perlu_dicek']}")  # fmt: skip
        self.tree.delete(*self.tree.get_children())
        self.analysis = ujian.item_analysis(results, self.exam, self.wizard.template.sections)
        by_code = any(a["kode"] for a in self.analysis)
        self.tree["displaycolumns"] = [c for c in self.tree["columns"] if by_code or c != "kode"]
        for i, a in enumerate(self.analysis):
            power = "" if a["daya_beda"] is None else f"{a['daya_beda']:g}"
            self.tree.insert("", "end", iid=str(i), tags=("check",) if a["catatan"] else (),
                             values=(a["kode"], a["soal"], a["kunci"], f"{a['bobot']:g}", a["benar"], a["kategori"],
                                     power, a["terbanyak"], *[a[o] for o in ujian.OPTIONS_ORDER],
                                     a["Kosong"], a["Ganda"]))  # fmt: skip
        self.item_note.set("")
        flagged = sum(1 for a in self.analysis if a["catatan"])
        self.item_legend.set(f"Kuning: {flagged} soal perlu dicek (kunci mungkin salah ketik, atau peserta bernilai "
                             "rendah justru lebih banyak benar). Pilih barisnya untuk melihat alasan."
                             if flagged else "")  # fmt: skip
        self.show_export_status()

    def show_absent(self):
        """The participants on the list without a sheet, with the sheets whose
        number is not on the list next to them (often the same people)."""
        d = tk.Toplevel(self)
        d.title(f"Tidak ikut ujian ({len(self.absent)})")
        d.transient(self.winfo_toplevel())
        f = ttk.Frame(d, padding=12)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="Peserta di daftar yang LJK-nya tidak ditemukan:").pack(anchor="w")
        tree = ttk.Treeview(f, columns=("nis", "nama", "kelas"), show="headings", height=8)
        for c, label, w in (("nis", "No. Peserta", 120), ("nama", "Nama", 300), ("kelas", "Kelompok", 120)):
            tree.heading(c, text=label)
            tree.column(c, width=w, anchor="w")
        for s in self.absent:
            tree.insert("", "end", values=(s.get("nis", ""), s.get("nama", ""), s.get("kelas", "")))
        tree.pack(fill="both", expand=True, pady=(4, 0))
        odd = [r for r in self.results if any(fl.startswith(ujian.NOT_LISTED) for fl in r.flags)]
        if odd:
            ttk.Label(f, text=f"{len(odd)} LJK nomornya tidak ada di daftar. Mungkin salah isi; betulkan lewat "
                              "Koreksi di langkah 5:", wraplength=580, justify="left").pack(anchor="w", pady=(8, 0))  # fmt: skip
            box = tk.Listbox(f, height=min(6, len(odd)))
            for r in odd:
                note = next(fl for fl in r.flags if fl.startswith(ujian.NOT_LISTED))[len(ujian.NOT_LISTED):]
                box.insert("end", f"{r.file_id}: {r.nis}{note}")
            box.pack(fill="x", pady=(4, 0))
        ttk.Button(f, text="Tutup", command=d.destroy).pack(anchor="e", pady=(10, 0))
        d.bind("<Escape>", lambda e: d.destroy())
        return d

    def show_item_note(self):
        sel = self.tree.selection()
        a = self.analysis[int(sel[0])] if sel else None
        self.item_note.set(f"Soal {a['soal']}: {a['catatan']}" if a and a["catatan"] else "")

    def export(self, ask_open=True):
        """Save the Excel rekap; True when written."""
        name = ujian.safe_name(f"Rekap {self.exam.name or 'Ujian'}")
        last = Path(self.exam.exported_file) if self.exam.exported_file else None
        if last and last.suffix.lower() != ".xlsx":  # the last export was the CSV
            last = last.with_suffix(".xlsx")
        path = filedialog.asksaveasfilename(
            parent=self, title="Simpan rekap", defaultextension=".xlsx",
            initialdir=str(last.parent) if last and last.parent.is_dir() else self.exam.output_dir,
            initialfile=last.name if last else f"{name}.xlsx", filetypes=[("Excel", "*.xlsx")],
        )  # fmt: skip
        if not path:
            return False
        results = self.wizard.compute_results()  # fresh: corrections made in step 5 count
        try:
            ujian.export_excel(path, results, self.exam, self.wizard.template.sections,
                               self.wizard.students, self.exam.name)  # fmt: skip
        except PermissionError:
            messagebox.showerror(APP_TITLE, "File sedang dibuka di Excel. Tutup dulu lalu coba lagi.", parent=self)
            return False
        self.exam.exported_file = str(Path(path))
        self.exam.exported_state = ujian.rekap_state(self.exam)
        self.exam.save(self.wizard.settings)
        self.show_export_status()
        if ask_open and messagebox.askyesno(APP_TITLE, "Rekap tersimpan. Buka sekarang?", parent=self):
            open_file(path, self)
        return True

    def export_csv(self):
        """The rekap as CSV (nilai + every answer); counts as exported too."""
        name = ujian.safe_name(f"Rekap {self.exam.name or 'Ujian'}")
        path = filedialog.asksaveasfilename(
            parent=self, title="Simpan rekap CSV", defaultextension=".csv",
            initialdir=self.exam.output_dir, initialfile=f"{name}.csv", filetypes=[("CSV", "*.csv")],
        )  # fmt: skip
        if not path:
            return False
        results = self.wizard.compute_results()
        try:
            ujian.export_csv(path, results, self.exam, self.wizard.template.sections)
        except PermissionError:
            messagebox.showerror(APP_TITLE, "File sedang dibuka di program lain. Tutup dulu lalu coba lagi.", parent=self)
            return False
        self.exam.exported_file = str(Path(path))
        self.exam.exported_state = ujian.rekap_state(self.exam)
        self.exam.save(self.wizard.settings)
        self.show_export_status()
        messagebox.showinfo(APP_TITLE, f"Rekap CSV tersimpan:\n{path}", parent=self)
        return True

    def export_advanced(self):
        """Pick, order and rename the columns (e.g. to match the user's own
        template); counts as exported too. Returns the dialog (for tests)."""
        results = self.wizard.compute_results()
        headers, _ = ujian.export_table(results, self.exam, self.wizard.template.sections)
        dialog = ExportDialog(self, headers, self.wizard.settings)
        self.wait_window(dialog)
        if not dialog.result:
            return None
        columns, kind = dialog.result
        name = ujian.safe_name(f"Rekap {self.exam.name or 'Ujian'}")
        types = [("Excel", "*.xlsx")] if kind == "xlsx" else [("CSV", "*.csv")]
        path = filedialog.asksaveasfilename(
            parent=self, title="Simpan rekap", defaultextension=f".{kind}",
            initialdir=self.exam.output_dir, initialfile=f"{name}.{kind}", filetypes=types,
        )  # fmt: skip
        if not path:
            return None
        if Path(path).suffix.lower() not in (".xlsx", ".csv"):
            path = str(Path(path).with_suffix(f".{kind}"))
        results = self.wizard.compute_results()
        try:
            ujian.export_custom(path, results, self.exam, self.wizard.template.sections, columns)
        except PermissionError:
            messagebox.showerror(APP_TITLE, "File sedang dibuka di program lain. Tutup dulu lalu coba lagi.", parent=self)
            return None
        self.exam.exported_file = str(Path(path))
        self.exam.exported_state = ujian.rekap_state(self.exam)
        self.exam.save(self.wizard.settings)
        self.show_export_status()
        if messagebox.askyesno(APP_TITLE, "Rekap tersimpan. Buka sekarang?", parent=self):
            open_file(path, self)
        return path

    def new_exam(self):
        kept = any(self.wizard.prefs.values())
        cleared = "Kunci, koreksi, dan folder yang tidak diingat" if kept else "Kunci, folder, dan koreksi"
        if not messagebox.askyesno(APP_TITLE, f"Mulai ujian baru dengan template yang sama?\n({cleared} dikosongkan.)", parent=self):
            return
        exam = ujian.Exam(template=self.exam.template, scans_dir=self.exam.scans_dir, output_dir=self.exam.output_dir)
        ujian.forget_folders(exam, self.wizard.prefs)
        self.wizard.set_exam(exam)
        self.wizard.go(1)


def install_dir():
    """Folder of OMRChecker.exe (or of this file when run from source)."""
    return Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent


def license_text(files):
    """Text of the first file found: next to the exe (installer), then bundled
    in the exe (PyInstaller --add-data), then next to this file (source)."""
    installed, bundled = files
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    for path in (install_dir() / installed, base / bundled, install_dir() / bundled):
        if path.is_file():
            return path.read_text(encoding="utf-8", errors="replace")
    return f"Lihat {PROJECT_URL}"


def show_text(parent, title, text):
    win = tk.Toplevel(parent)
    win.title(title)
    win.geometry("640x480")
    win.transient(parent)
    box = tk.Text(win, wrap="word", font=theme.mono(win, 10), padx=12, pady=12)
    box.insert("1.0", text)
    box.configure(state="disabled")
    box.pack(fill="both", expand=True)
    ttk.Button(win, text="Tutup", command=win.destroy).pack(pady=8)


def open_file(path, parent):
    try:
        open_path(path)
    except OSError as e:
        messagebox.showerror(APP_TITLE, str(e), parent=parent)


class ExportDialog(tk.Toplevel):
    """"Ekspor lanjutan": tick the columns, order them, rename their headers
    and pick Excel or CSV. The settings can be saved as a named format; the
    last one used comes back next time. `result`: ([(column, header)], kind)."""

    def __init__(self, master, headers, settings=None):
        super().__init__(master)
        self.title("Ekspor lanjutan")
        self.transient(master.winfo_toplevel())
        self.settings = settings
        self.headers = list(headers)
        self.result = None
        self.formats = ujian.load_export_formats(settings)
        f = ttk.Frame(self, padding=(20, 16, 20, 16))
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="Pilih kolom yang diekspor, atur urutannya, dan ganti judulnya bila perlu "
                          "supaya cocok dengan format Anda.", wraplength=620, justify="left").pack(anchor="w")  # fmt: skip
        top = ttk.Frame(f)
        top.pack(fill="x", pady=(10, 6))
        ttk.Label(top, text="Format:").pack(side="left")
        self.fmt = tk.StringVar()
        self.fmt_box = ttk.Combobox(top, textvariable=self.fmt, state="readonly", width=28)
        self.fmt_box.pack(side="left", padx=6)
        self.fmt_box.bind("<<ComboboxSelected>>", lambda e: self.use_format(self.fmt.get()))
        ttk.Button(top, text="Simpan format...", command=self.save_format).pack(side="left")
        ttk.Button(top, text="Hapus format", command=self.delete_format).pack(side="left", padx=6)
        mid = ttk.Frame(f)
        mid.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(mid, columns=("pakai", "kolom", "judul"), show="headings", height=14, selectmode="browse")
        for c, text, width in (("pakai", "Ekspor", 60), ("kolom", "Kolom", 200), ("judul", "Judul di file", 260)):
            self.tree.heading(c, text=text)
            self.tree.column(c, width=width, anchor="center" if c == "pakai" else "w", stretch=c != "pakai")
        vs = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vs.pack(side="left", fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.on_select())
        self.tree.bind("<space>", lambda e: self.toggle())
        self.tree.bind("<Button-1>", self.on_click)
        side = ttk.Frame(mid)
        side.pack(side="left", fill="y", padx=(10, 0))
        for text, cmd in (("Centang / hapus", self.toggle), ("Naik", lambda: self.move(-1)), ("Turun", lambda: self.move(1)),
                          ("Centang semua", lambda: self.check_all(True)), ("Hapus semua", lambda: self.check_all(False))):  # fmt: skip
            ttk.Button(side, text=text, command=cmd).pack(fill="x", pady=(0, 6))
        edit = ttk.Frame(f)
        edit.pack(fill="x", pady=(8, 0))
        ttk.Label(edit, text="Judul kolom terpilih:").pack(side="left")
        self.title_var = tk.StringVar()
        self.title_entry = ttk.Entry(edit, textvariable=self.title_var, width=36)
        self.title_entry.pack(side="left", padx=6)
        self.title_var.trace_add("write", lambda *a: self.on_title())
        kind = ttk.Frame(f)
        kind.pack(fill="x", pady=(10, 0))
        ttk.Label(kind, text="Simpan sebagai:").pack(side="left")
        self.kind = tk.StringVar(value="xlsx")
        ttk.Radiobutton(kind, text="Excel (.xlsx)", value="xlsx", variable=self.kind).pack(side="left", padx=6)
        ttk.Radiobutton(kind, text="CSV (.csv)", value="csv", variable=self.kind).pack(side="left")
        self.info = tk.StringVar()
        ttk.Label(f, textvariable=self.info, foreground=theme.MUTED).pack(anchor="w", pady=(8, 0))
        bar = ttk.Frame(f)
        bar.pack(fill="x", pady=(12, 0))
        ttk.Button(bar, text="Ekspor...", style="Accent.TButton", command=self.ok).pack(side="right")
        ttk.Button(bar, text="Batal", command=self.destroy).pack(side="right", padx=8)
        self.bind("<Escape>", lambda e: self.destroy())
        self.rows = {}  # tree item -> [checked, column, header]
        self.refresh_formats()
        last = self.formats.get(ujian.LAST_EXPORT_FORMAT)
        self.load_columns(last["kolom"] if last else [[h, h] for h in self.headers], last["jenis"] if last else "xlsx")
        self.update_idletasks()
        owner = master.winfo_toplevel()
        x = owner.winfo_rootx() + (owner.winfo_width() - self.winfo_reqwidth()) // 2
        y = owner.winfo_rooty() + (owner.winfo_height() - self.winfo_reqheight()) // 3
        self.geometry(f"+{max(0, x)}+{max(0, y)}")
        self.grab_set()

    def refresh_formats(self):
        names = sorted(n for n in self.formats if n != ujian.LAST_EXPORT_FORMAT)
        self.fmt_box.configure(values=names)
        if self.fmt.get() not in names:
            self.fmt.set("")

    def load_columns(self, columns, kind):
        """Ticked columns first in their saved order, then the rest unticked."""
        self.tree.delete(*self.tree.get_children())
        self.rows = {}
        picked = [(c, t) for c, t in columns if c in self.headers]
        names = {c for c, _ in picked}
        rest = [(h, h) for h in self.headers if h not in names]
        for checked, items in ((True, picked), (False, rest)):
            for c, t in items:
                item = self.tree.insert("", "end")
                self.rows[item] = [checked, c, t or c]
                self.show(item)
        self.kind.set(kind)
        missing = len(columns) - len(picked)
        self.info.set(f"{missing} kolom di format ini tidak ada di ujian ini dan dilewati." if missing else "")
        first = self.tree.get_children()
        if first:
            self.tree.selection_set(first[0])

    def show(self, item):
        checked, c, t = self.rows[item]
        self.tree.item(item, values=("✓" if checked else "", c, t))

    def selected(self):
        sel = self.tree.selection()
        return sel[0] if sel else None

    def on_select(self):
        item = self.selected()
        self._editing = None  # no write-back while the entry is refilled
        self.title_var.set(self.rows[item][2] if item else "")
        self._editing = item

    def on_title(self):
        item = getattr(self, "_editing", None)
        if item in self.rows:
            self.rows[item][2] = self.title_var.get()
            self.show(item)

    def on_click(self, event):
        if self.tree.identify_column(event.x) == "#1" and self.tree.identify_row(event.y):
            self.tree.selection_set(self.tree.identify_row(event.y))
            self.toggle()
            return "break"

    def toggle(self):
        item = self.selected()
        if item:
            self.rows[item][0] = not self.rows[item][0]
            self.show(item)

    def check_all(self, value):
        for item in self.rows:
            self.rows[item][0] = value
            self.show(item)

    def move(self, step):
        item = self.selected()
        if item:
            index = self.tree.index(item) + step
            if 0 <= index < len(self.rows):
                self.tree.move(item, "", index)
                self.tree.see(item)

    def columns(self):
        out = []
        for item in self.tree.get_children():
            checked, c, t = self.rows[item]
            if checked:
                out.append([c, t.strip() or c])
        return out

    def use_format(self, name):
        fmt = self.formats.get(name)
        if fmt:
            self.load_columns(fmt["kolom"], fmt["jenis"])

    def store(self):
        try:
            ujian.save_export_formats(self.formats, self.settings)
        except OSError as e:
            messagebox.showerror(APP_TITLE, f"Format tidak bisa disimpan:\n{e}", parent=self)

    def save_format(self):
        if not self.columns():
            messagebox.showerror(APP_TITLE, "Centang minimal satu kolom dulu.", parent=self)
            return
        name = simpledialog.askstring(APP_TITLE, "Nama format (misalnya \"Format sekolah\"):",
                                      initialvalue=self.fmt.get(), parent=self)  # fmt: skip
        name = (name or "").strip()
        if not name:
            return
        if name in self.formats and name != self.fmt.get():
            if not messagebox.askyesno(APP_TITLE, f"Format \"{name}\" sudah ada. Timpa?", parent=self):
                return
        self.formats[name] = {"kolom": self.columns(), "jenis": self.kind.get()}
        self.store()
        self.refresh_formats()
        self.fmt.set(name)
        self.info.set(f"Format \"{name}\" tersimpan.")

    def delete_format(self):
        name = self.fmt.get()
        if not name or not messagebox.askyesno(APP_TITLE, f"Hapus format \"{name}\"?", parent=self):
            return
        self.formats.pop(name, None)
        self.store()
        self.refresh_formats()

    def ok(self):
        columns = self.columns()
        if not columns:
            messagebox.showerror(APP_TITLE, "Centang minimal satu kolom untuk diekspor.", parent=self)
            return
        self.formats[ujian.LAST_EXPORT_FORMAT] = {"kolom": columns, "jenis": self.kind.get()}
        self.store()
        self.result = ([tuple(c) for c in columns], self.kind.get())
        self.destroy()


class ChoiceDialog(tk.Toplevel):
    """Modal question: heading, text, an optional muted detail line and a row
    of buttons. ask() returns the key of the clicked button (None = closed)."""

    def __init__(self, master, heading, text, buttons, detail=""):
        super().__init__(master)
        self.title(APP_TITLE)
        self.transient(master.winfo_toplevel())
        self.resizable(False, False)
        self.choice = None
        f = ttk.Frame(self, padding=(28, 24, 28, 20))
        f.pack(fill="both", expand=True)
        ttk.Label(f, text=heading, style="Subtitle.TLabel").pack(anchor="w")
        ttk.Label(f, text=text, wraplength=520, justify="left").pack(anchor="w", pady=(8, 0))
        if detail:
            ttk.Label(f, text=detail, foreground=theme.MUTED, wraplength=520, justify="left").pack(anchor="w", pady=(6, 0))
        bar = ttk.Frame(f)
        bar.pack(fill="x", pady=(22, 0))
        self.buttons = {}
        for key, label, primary in reversed(buttons):  # right to left: the primary button ends up last
            b = ttk.Button(bar, text=label, style="Accent.TButton" if primary else "TButton",
                           command=lambda k=key: self.pick(k))  # fmt: skip
            b.pack(side="right", padx=(8, 0))
            self.buttons[key] = b
            if primary:
                b.focus_set()
                self.bind("<Return>", lambda e, k=key: self.pick(k))
        self.bind("<Escape>", lambda e: self.pick(None))
        self.protocol("WM_DELETE_WINDOW", lambda: self.pick(None))
        self.update_idletasks()
        top = master.winfo_toplevel()
        x = top.winfo_rootx() + (top.winfo_width() - self.winfo_reqwidth()) // 2
        y = top.winfo_rooty() + (top.winfo_height() - self.winfo_reqheight()) // 3
        self.geometry(f"+{max(0, x)}+{max(0, y)}")
        self.grab_set()

    def pick(self, key):
        self.choice = key
        self.destroy()

    @classmethod
    def ask(cls, master, heading, text, buttons, detail=""):
        dialog = cls(master, heading, text, buttons, detail)
        master.wait_window(dialog)
        return dialog.choice


# ---------------------------------------------------------------------------
# Window
# ---------------------------------------------------------------------------


class Wizard(tk.Tk):
    def __init__(self, library=None, settings=None):
        super().__init__()
        theme.apply(self)
        self.title(f"{APP_TITLE} v{VERSION}")
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        width, height = min(1200, sw - 40), min(800, sh - 90)  # leave room for the taskbar
        self.geometry(f"{width}x{height}+{max(0, (sw - width) // 2)}+0")
        if sw < 1300 or sh < 900:  # small or scaled screen: use all of it
            try:
                self.state("zoomed")
            except tk.TclError:
                pass
        self.minsize(1080, 660)
        self.library = Path(library or ujian.library_dir())
        self.settings = settings
        self.exam = ujian.Exam.load(settings)
        self.prefs = ujian.load_prefs(settings)
        if self.exam.exported_file:  # finished last time: the next exam starts with fresh folders
            ujian.forget_folders(self.exam, self.prefs)
        self.template = None
        self.students = []
        self.reprocess = False
        self.clear_old = False
        self.scans_archived = False  # step 3 archived the scans: old results must be replaced
        self.busy = False

        # sidebar: app name and the steps
        side = ttk.Frame(self, style="Side.TFrame", width=250)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        brand = tk.Frame(side, bg=theme.SIDEBAR)
        brand.pack(anchor="w", padx=20, pady=(22, 20))
        self.logo = theme.logo(self)
        if self.logo:
            tk.Label(brand, image=self.logo, bg=theme.SIDEBAR).pack(side="left", padx=(0, 10))
        names = tk.Frame(brand, bg=theme.SIDEBAR)
        names.pack(side="left")
        tk.Label(names, text="Pemindai LJK", bg=theme.SIDEBAR, fg=theme.FG, font="SunValleySubtitleFont").pack(anchor="w")
        tk.Label(names, text=f"OMRChecker v{VERSION}", bg=theme.SIDEBAR, fg=theme.MUTED, font="SunValleyCaptionFont").pack(
            anchor="w")  # fmt: skip
        self.stepper = theme.Stepper(side, STEPS, self.jump, width=250)
        self.stepper.pack(fill="x")
        # the old main window stays reachable with OMRChecker.exe --lanjutan
        self.help_btn = ttk.Button(side, text="Bantuan", command=self.show_help_menu)
        self.help_btn.pack(side="bottom", anchor="w", padx=20, pady=(4, 20))
        ttk.Button(side, text="Buka ujian lama...", command=self.open_exam).pack(side="bottom", anchor="w", padx=20, pady=4)

        main = ttk.Frame(self)
        main.pack(side="left", fill="both", expand=True)
        self.eyebrow = tk.StringVar()
        self.heading = tk.StringVar()
        self.hint = tk.StringVar()
        ttk.Label(main, textvariable=self.eyebrow, style="Eyebrow.TLabel", foreground=theme.ACCENT).pack(anchor="w", padx=28, pady=(22, 0))
        ttk.Label(main, textvariable=self.heading, style="Title.TLabel").pack(anchor="w", padx=28)
        ttk.Label(main, textvariable=self.hint, foreground=theme.MUTED).pack(anchor="w", padx=28, pady=(2, 0))

        foot = ttk.Frame(main, style="Footer.TFrame")
        foot.pack(side="bottom", fill="x")
        ttk.Separator(foot).pack(fill="x")
        self.back_btn = ttk.Button(foot, text="←  Kembali", command=self.back)
        self.back_btn.pack(side="left", padx=28, pady=12)
        self.next_btn = ttk.Button(foot, text="Lanjut  →", command=self.next, style="Accent.TButton")
        self.next_btn.pack(side="right", padx=28, pady=12)

        self.body = ttk.Frame(main)
        self.body.pack(fill="both", expand=True, padx=28, pady=(14, 14))

        self.steps = [cls(self) for cls in (TemplateStep, KeyStep, ScansStep, OutputStep, ProcessStep, ExportStep)]
        self.current = None
        self.reached = 0
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.go(0)

    # navigation
    def go(self, i):
        if self.current is not None:
            self.steps[self.current].pack_forget()
        self.current = i
        self.reached = max(self.reached, i)
        step = self.steps[i]
        self.eyebrow.set(f"LANGKAH {i + 1} DARI {len(STEPS)}")
        self.heading.set(step.title)
        self.hint.set(step.hint)
        step.pack(fill="both", expand=True)
        self.back_btn.configure(state="normal" if i > 0 else "disabled")
        self.next_btn.configure(text="Selesai" if i == len(STEPS) - 1 else "Lanjut  →")
        self.stepper.set(i, self.reached)
        step.enter()

    def next(self):
        if self.busy:
            return
        step = self.steps[self.current]
        if not step.leave():
            return
        self.exam.save(self.settings)
        if self.current == len(STEPS) - 1:
            self.finish()
            return
        self.go(self.current + 1)

    def back(self):
        if not self.busy and self.current > 0:
            self.exam.save(self.settings)
            self.go(self.current - 1)

    def jump(self, i):
        if self.busy or i == self.current:
            return
        if i < self.current:
            self.go(i)
            return
        # forward: pass through the steps in between so each is validated
        while self.current < i:
            before = self.current
            self.next()
            if self.current == before:
                return

    def set_busy(self, busy):
        self.busy = busy
        state = "disabled" if busy else "normal"
        self.next_btn.configure(state=state)
        self.back_btn.configure(state=state if self.current > 0 else "disabled")

    # data
    def compute_results(self):
        self.students = []
        if self.exam.students_file:
            try:
                self.students, _, _ = ujian.load_students(self.exam.students_file, self.exam.students_cols)
            except Exception:
                self.students = []
        rows, errors = ujian.read_results(self.exam.output_dir)
        return ujian.score_results(rows, errors, self.exam, self.template.sections, self.students,
                                   blank_source=self.template.source)  # fmt: skip

    def set_pref(self, key, value):
        self.prefs[key] = bool(value)
        try:
            ujian.save_prefs(self.prefs, self.settings)
        except OSError:
            pass

    def set_exam(self, exam):
        self.exam = exam
        for step in self.steps:
            step.exam = exam
        exam.save(self.settings)

    def open_exam(self):
        """Reopen an exam checked earlier, from its output folder (ujian.json)."""
        if self.busy:
            return
        folder = filedialog.askdirectory(parent=self, title="Pilih folder hasil ujian yang ingin dibuka")
        if not folder:
            return
        try:
            exam = ujian.open_exam(folder, self.library)
            template = ujian.read_library_template(exam.template)
        except (ValueError, OSError) as e:
            messagebox.showerror(APP_TITLE, str(e), parent=self)
            return
        if Path(folder).resolve() != Path(self.exam.output_dir or ".").resolve():
            if not self.ask_export_before_close("membuka ujian lain", "Buka tanpa ekspor"):
                return
        self.set_exam(exam)
        self.template = template
        self.reprocess = self.clear_old = False
        self.reached = len(STEPS) - 1
        self.go(len(STEPS) - 1)

    def show_help_menu(self):
        menu = tk.Menu(self, tearoff=False)
        menu.add_command(label="Panduan (PDF)", command=self.open_guide)
        menu.add_command(label="Buka folder data & log", command=lambda: open_file(ujian.app_data_dir(), self))
        menu.add_command(label="Cek versi terbaru (halaman unduhan)", command=self.open_releases)
        menu.add_separator()
        menu.add_command(label="Tentang Pemindai LJK", command=self.about)
        menu.update_idletasks()
        b = self.help_btn
        menu.tk_popup(b.winfo_rootx(), b.winfo_rooty() - menu.winfo_reqheight())

    def open_releases(self):
        import webbrowser

        webbrowser.open(RELEASES_URL + "/latest")

    def open_guide(self):
        guide = install_dir() / "PANDUAN.pdf"
        if not guide.is_file():
            messagebox.showinfo(APP_TITLE, "PANDUAN.pdf tidak ditemukan di folder program.\n"
                                f"Unduh dari halaman rilis:\n{RELEASES_URL}", parent=self)  # fmt: skip
            return
        open_file(guide, self)

    def about(self):
        choice = ChoiceDialog.ask(
            self, f"Pemindai LJK v{VERSION}",
            "Pemeriksa Lembar Jawaban Komputer (LJK) untuk ujian sekolah, seleksi, dan tes perusahaan.\n"
            "Perangkat lunak bebas dan sumber terbuka, lisensi GNU AGPL-3.0. Hak cipta (c) 2026 Budi Permadi.",
            [("lisensi", "Lisensi (AGPL-3.0)", False), ("pihak", "Pemberitahuan pihak ketiga", False),
             ("tutup", "Tutup", True)],
            detail="Dibangun di atas OMRChecker karya Udayraj Deshmukh dan kontributor (lisensi MIT).\n"
                   f"Kode sumber: {PROJECT_URL}",
        )  # fmt: skip
        if choice == "lisensi":
            show_text(self, "Lisensi", license_text(LICENSE_FILES))
        elif choice == "pihak":
            show_text(self, "Pemberitahuan pihak ketiga", license_text(NOTICE_FILES))

    def advanced(self):
        import gui

        if getattr(sys, "frozen", False):
            cmd = [sys.executable, "--lanjutan"]
        else:
            cmd = [sys.executable, str(Path(gui.__file__).resolve()), "--lanjutan"]
        subprocess.Popen(cmd)

    # closing
    def export_pending(self):
        """True when there are results whose current rekap was never exported."""
        if self.template is None:
            return False
        state = ujian.rekap_state(self.exam)
        return bool(state) and state != self.exam.exported_state

    def ask_export_before_close(self, action="menutup", go_on="Tutup tanpa ekspor"):
        """Offer the export when the rekap is missing or out of date. True = go on closing."""
        if not self.export_pending():
            return True
        rows, errors = ujian.read_results(self.exam.output_dir)
        if self.exam.exported_file:
            heading = "Rekap belum diperbarui"
            text = ("Ada perubahan sejak ekspor terakhir (koreksi, kunci jawaban, atau proses ulang). "
                    f"Ekspor ulang rekap sebelum {action}?")  # fmt: skip
            detail = f"Ekspor terakhir: {self.exam.exported_file}"
        else:
            heading = "Rekap nilai belum diekspor"
            text = f"Hasil pemeriksaan {len(rows) + len(errors)} LJK belum disimpan ke Excel. Ekspor sekarang sebelum {action}?"
            detail = "Hasil tetap tersimpan di folder hasil dan bisa diekspor lain kali."
        choice = ChoiceDialog.ask(self, heading, text, [("batal", "Batal", False), ("tutup", go_on, False),
                                                        ("ekspor", "Ekspor ke Excel...", True)], detail)  # fmt: skip
        if choice == "ekspor":
            return self.steps[5].export(ask_open=False)
        return choice == "tutup"

    def finish(self):
        """'Selesai' on the last step: export first if needed, then a closing screen."""
        if self.export_pending():
            if self.ask_export_before_close():
                self.close()
            return
        path = self.exam.exported_file
        buttons = [("folder", "Buka folder hasil", False), ("baru", "Ujian baru", False), ("tutup", "Tutup aplikasi", True)]
        if path and Path(path).exists():
            kind = "CSV" if Path(path).suffix.lower() == ".csv" else "Excel"
            buttons.insert(0, ("buka", f"Buka rekap {kind}", False))
        name = f" {self.exam.name}" if self.exam.name else ""
        choice = ChoiceDialog.ask(self, "Pemeriksaan selesai", f"Rekap nilai{name} sudah tersimpan.", buttons,
                                  detail=path or self.exam.output_dir)  # fmt: skip
        if choice == "buka":
            open_file(path, self)
        elif choice == "folder":
            open_file(self.exam.output_dir, self)
        elif choice == "baru":
            self.steps[5].new_exam()
        elif choice == "tutup":
            self.close()

    def on_close(self):
        """The window's X button."""
        if self.busy:
            if not messagebox.askyesno(APP_TITLE, "Proses masih berjalan. Hentikan dan keluar?", parent=self):
                return
        elif not self.ask_export_before_close():
            return
        self.close()

    def close(self):
        proc = getattr(self.steps[4], "proc", None)
        if proc is not None and proc.is_alive():
            proc.terminate()
        self.exam.save(self.settings)
        self.destroy()


def run_wizard(mainloop=True, **kw):
    if sys.platform.startswith("win"):
        try:
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    app = Wizard(**kw)
    if mainloop:
        app.mainloop()
    return app
