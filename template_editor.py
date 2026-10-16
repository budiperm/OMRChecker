"""

 Template editor window (Tkinter) for OMRChecker GUI

 Open a scan of a blank answer sheet, let the bubbles be detected, label each
 block (questions, NIS, exam code, birth date ...), enter the answer key and
 save template.json + config.json + evaluation.json + reference image.

"""

import base64
import csv
import multiprocessing as mp
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

import cv2
import numpy as np

import template_builder as tb

KIND_LABELS = {
    tb.KIND_MCQ: "Soal pilihan ganda",
    tb.KIND_DIGITS: "Angka 0-9 (NIS, kode, tanggal)",
    tb.KIND_CUSTOM: "Pilihan khusus",
    tb.KIND_IGNORE: "Abaikan",
}
KIND_COLORS = {
    tb.KIND_MCQ: "#1f6feb",
    tb.KIND_DIGITS: "#1a7f37",
    tb.KIND_CUSTOM: "#bf8700",
    tb.KIND_IGNORE: "#8c959f",
}
GROUP_PRESETS = ["NIS", "NoPeserta", "KodeSoal", "TglLahir", "Kelas", "Ruang"]
DIRECTION_LABELS = {True: "Kiri ke kanan (satu isian per baris)",
                    False: "Atas ke bawah (satu isian per kolom)"}  # fmt: skip
TITLE = "Buat Template LJK"


class TemplateEditor(tk.Toplevel):
    def __init__(self, master, on_saved=None, run_worker=None, library=None, edit_folder=None):
        """library: template library folder -> save there by name (wizard);
        the answer key is then entered in the wizard, not here.
        edit_folder: library template to reopen for editing."""
        super().__init__(master)
        self.title(TITLE)
        self.geometry("1280x820")
        self.minsize(980, 600)
        self.on_saved = on_saved
        self.run_worker = run_worker
        self.library = library
        self.edit_folder = edit_folder
        self.template_name = ""

        self.source_path = None
        self.sheet = None  # blank sheet prepared by template_builder
        self.page = None  # its image in template page coordinates (BGR)
        self.page_dims = None
        self.bubbles = []
        self.blocks = []
        self.selected = None
        self.zoom = 1.0
        self.photo = None
        self.drag_start = None
        self.drag_rect = None
        self.test_proc = None

        self.kind_var = tk.StringVar()
        self.start_var = tk.StringVar()
        self.group_var = tk.StringVar()
        self.section_var = tk.StringVar()
        self.values_var = tk.StringVar()
        self.dir_var = tk.StringVar()
        self.shape_var = tk.StringVar(value="Pilih sebuah blok.")
        self.status_var = tk.StringVar(
            value="Langkah 1: buka hasil scan LJK yang masih kosong."
        )
        self.correct_var = tk.StringVar(value="1")
        self.incorrect_var = tk.StringVar(value="0")
        self.unmarked_var = tk.StringVar(value="0")

        self.build_ui()
        self.bind("<Delete>", lambda e: self.delete_block())
        if edit_folder:
            self.load_from_library(edit_folder)

    # ---- layout ----------------------------------------------------------
    def build_ui(self):
        top = ttk.Frame(self)
        top.pack(fill="x", padx=8, pady=6)
        ttk.Button(top, text="1. Buka scan LJK kosong...", command=self.open_scan).pack(
            side="left"
        )
        ttk.Button(top, text="Deteksi ulang", command=self.detect).pack(side="left", padx=6)
        ttk.Button(top, text="−", width=2, style="Small.TButton", command=lambda: self.set_zoom(self.zoom / 1.25)).pack(
            side="left", padx=(16, 0)
        )
        ttk.Button(top, text="+", width=2, style="Small.TButton", command=lambda: self.set_zoom(self.zoom * 1.25)).pack(
            side="left"
        )
        ttk.Button(top, text="Pas layar", style="Small.TButton", command=self.fit_zoom).pack(side="left", padx=4)
        ttk.Label(top, textvariable=self.status_var, style="Muted.TLabel").pack(
            side="left", padx=12
        )

        body = ttk.Panedwindow(self, orient="horizontal")
        body.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        # Canvas
        cv_frame = ttk.Frame(body)
        self.canvas = tk.Canvas(cv_frame, background="#e4e8ee", highlightthickness=0)
        vsb = ttk.Scrollbar(cv_frame, orient="vertical", command=self.canvas.yview)
        hsb = ttk.Scrollbar(cv_frame, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        cv_frame.rowconfigure(0, weight=1)
        cv_frame.columnconfigure(0, weight=1)
        body.add(cv_frame, weight=3)

        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<MouseWheel>", self.on_wheel)
        self.canvas.bind("<Button-4>", lambda e: self.canvas.yview_scroll(-3, "units"))
        self.canvas.bind("<Button-5>", lambda e: self.canvas.yview_scroll(3, "units"))

        # Side panel
        side = ttk.Frame(body, width=360)
        body.add(side, weight=1)
        pad = {"padx": 6, "pady": 3}

        lst = ttk.LabelFrame(side, text="2. Blok bulatan")
        lst.pack(fill="both", expand=True, **pad)
        self.tree = ttk.Treeview(lst, columns=("desc",), show="headings", height=6)
        self.tree.heading("desc", text="Blok (klik untuk ubah)")
        self.tree.column("desc", width=300)
        self.tree.pack(fill="both", expand=True, padx=4, pady=4)
        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)
        btns = ttk.Frame(lst)
        btns.pack(fill="x", padx=4, pady=(0, 4))
        ttk.Button(btns, text="Hapus blok", command=self.delete_block).pack(side="left")
        ttk.Button(btns, text="Nomori ulang soal", command=self.renumber).pack(
            side="left", padx=4
        )
        btns2 = ttk.Frame(lst)
        btns2.pack(fill="x", padx=4, pady=(0, 4))
        ttk.Button(btns2, text="Pecah per kolom", command=lambda: self.split_selected("column")).pack(side="left")
        ttk.Button(btns2, text="Pecah per baris", command=lambda: self.split_selected("row")).pack(side="left", padx=4)
        ttk.Button(btns2, text="Ganti nama bagian...", command=self.rename_section).pack(side="left")
        ttk.Label(
            lst,
            text="Tarik kotak di gambar untuk membuat blok baru.",
            style="Muted.TLabel",
        ).pack(anchor="w", padx=4, pady=(0, 4))

        prop = ttk.LabelFrame(side, text="Isi blok terpilih")
        prop.pack(fill="x", **pad)
        prop.columnconfigure(1, weight=1)
        ttk.Label(prop, textvariable=self.shape_var).grid(
            row=0, column=0, columnspan=2, sticky="w", **pad
        )
        ttk.Label(prop, text="Jenis:").grid(row=1, column=0, sticky="w", **pad)
        self.kind_box = ttk.Combobox(
            prop, textvariable=self.kind_var, values=list(KIND_LABELS.values()), state="readonly"
        )
        self.kind_box.grid(row=1, column=1, sticky="ew", **pad)
        self.kind_box.bind("<<ComboboxSelected>>", lambda e: self.on_kind_change())
        ttk.Label(prop, text="No. soal awal:").grid(row=2, column=0, sticky="w", **pad)
        self.start_entry = ttk.Spinbox(prop, from_=1, to=999, textvariable=self.start_var)
        self.start_entry.grid(row=2, column=1, sticky="ew", **pad)
        ttk.Label(prop, text="Bagian soal:").grid(row=3, column=0, sticky="w", **pad)
        self.section_box = ttk.Combobox(prop, textvariable=self.section_var)
        self.section_box.grid(row=3, column=1, sticky="ew", **pad)
        ttk.Label(prop, text="Nama kolom:").grid(row=4, column=0, sticky="w", **pad)
        self.group_box = ttk.Combobox(prop, textvariable=self.group_var, values=GROUP_PRESETS)
        self.group_box.grid(row=4, column=1, sticky="ew", **pad)
        ttk.Label(prop, text="Pilihan:").grid(row=5, column=0, sticky="w", **pad)
        self.values_entry = ttk.Entry(prop, textvariable=self.values_var)
        self.values_entry.grid(row=5, column=1, sticky="ew", **pad)
        ttk.Label(prop, text="Arah pilihan:").grid(row=6, column=0, sticky="w", **pad)
        self.dir_box = ttk.Combobox(
            prop, textvariable=self.dir_var, values=list(DIRECTION_LABELS.values()), state="readonly"
        )
        self.dir_box.grid(row=6, column=1, sticky="ew", **pad)
        ttk.Button(prop, text="Terapkan", command=self.apply_props, style="Accent.TButton").grid(
            row=7, column=1, sticky="e", **pad
        )
        ttk.Label(
            prop,
            text="Blok dengan nama kolom sama digabung berurutan\n"
            "(mis. TGL, BLN, THN → TglLahir). Nomor soal mulai\n"
            "dari 1 lagi di setiap bagian (I, II, Motivasi, ...).",
            style="Muted.TLabel",
        ).grid(row=8, column=0, columnspan=2, sticky="w", **pad)

        key = ttk.LabelFrame(side, text="3. Kunci jawaban (opsional)")
        self.key_text = tk.Text(key, height=3, width=36, wrap="word", font="TkFixedFont")
        self.key_text.pack(fill="x", padx=4, pady=4)
        ttk.Label(key, text="Contoh: ABCDE ABCDE ... atau 1A 2B 3C", style="Muted.TLabel").pack(
            anchor="w", padx=4
        )
        sc = ttk.Frame(key)
        sc.pack(fill="x", padx=4, pady=4)
        for label, var in (("Benar", self.correct_var), ("Salah", self.incorrect_var),
                           ("Kosong", self.unmarked_var)):  # fmt: skip
            ttk.Label(sc, text=label).pack(side="left")
            ttk.Entry(sc, textvariable=var, width=5).pack(side="left", padx=(2, 8))

        act = ttk.LabelFrame(side, text="3. Simpan" if self.library else "4. Simpan")
        save_text = "Simpan ke pustaka template..." if self.library else "Simpan template ke folder ujian..."
        ttk.Button(act, text=save_text, command=self.save, style="Accent.TButton").pack(fill="x", padx=4, pady=4)
        ttk.Button(act, text="Uji dengan LJK terisi...", command=self.test_with_scan).pack(
            fill="x", padx=4, pady=(0, 4)
        )
        # Fixed sections stick to the bottom; the block list takes what is left
        for frame in (lst, prop, key, act):
            frame.pack_forget()
        for frame in (act, prop) if self.library else (act, key, prop):
            frame.pack(side="bottom", fill="x", **pad)
        lst.pack(side="top", fill="both", expand=True, **pad)
        self.set_props_state(False)

    # ---- loading and detection ------------------------------------------
    def open_scan(self):
        path = filedialog.askopenfilename(
            parent=self,
            title="Pilih hasil scan LJK kosong",
            filetypes=[("Gambar / PDF", "*.jpg *.jpeg *.png *.pdf"), ("Semua file", "*.*")],
        )
        if not path:
            return
        try:
            img = tb.load_image(path)
        except Exception as e:
            messagebox.showerror(TITLE, f"Gagal membuka file:\n{e}", parent=self)
            return
        self.source_path = Path(path)
        self.config(cursor="watch")
        self.update_idletasks()
        try:
            self.sheet = tb.prepare_sheet(img, source_name=Path(path).name)
        finally:
            self.config(cursor="")
        self.page = self.sheet.page
        self.page_dims = self.sheet.page_dims
        self.detect()
        self.fit_zoom()

    def detect(self):
        if self.page is None:
            return
        self.config(cursor="watch")
        self.update_idletasks()
        try:
            self.bubbles, self.blocks = tb.detect_blocks(self.page)
        finally:
            self.config(cursor="")
        self.selected = None
        self.refresh()
        n_mcq = sum(b.field_count for b in self.blocks if b.kind == tb.KIND_MCQ)
        n_bubbles = sum(b.rows * b.cols for b in self.blocks if b.kind != tb.KIND_IGNORE)
        align = "4 kotak hitam di sudut" if self.sheet.uses_markers else "gambar referensi"
        self.status_var.set(
            f"Terdeteksi {n_bubbles} bulatan, {len(self.blocks)} blok, {n_mcq} soal. "
            f"Penyelarasan: {align}."
        )
        if not self.blocks:
            messagebox.showwarning(
                TITLE,
                "Tidak ada bulatan yang terdeteksi.\n\nPastikan scan jelas (200-300 DPI, "
                "grayscale/warna), atau buat blok manual dengan menarik kotak di gambar.",
                parent=self,
            )

    # ---- drawing ---------------------------------------------------------
    def fit_zoom(self):
        if self.page is None:
            return
        self.update_idletasks()
        w = max(self.canvas.winfo_width(), 400)
        self.set_zoom(w / self.page_dims[0])

    def set_zoom(self, z):
        if self.page is None:
            return
        self.zoom = min(max(z, 0.2), 4.0)
        self.refresh()

    def refresh(self):
        c = self.canvas
        c.delete("all")
        if self.page is None:
            return
        z = self.zoom
        w, h = int(self.page_dims[0] * z), int(self.page_dims[1] * z)
        disp = cv2.resize(self.page, (w, h), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".png", disp)
        self.photo = tk.PhotoImage(master=c, data=base64.b64encode(buf.tobytes()))
        c.create_image(0, 0, image=self.photo, anchor="nw")
        c.configure(scrollregion=(0, 0, w, h))

        for i, b in enumerate(self.blocks):
            color = KIND_COLORS[b.kind]
            sel = b is self.selected
            c.create_rectangle(
                (b.x0 - 3) * z, (b.y0 - 3) * z, (b.x1 + 3) * z, (b.y1 + 3) * z,
                outline="#cf222e" if sel else color, width=3 if sel else 2, tags=("block", f"b{i}"),
            )
            for r in range(b.rows):  # predicted bubble positions
                for k in range(b.cols):
                    x, y = b.x0 + k * b.gap_x, b.y0 + r * b.gap_y
                    c.create_oval(x * z, y * z, (x + b.bw) * z, (y + b.bh) * z,
                                  outline=color, width=1)  # fmt: skip
            label = c.create_text(
                (b.x0 - 3) * z + 2, (b.y0 - 3) * z - 1, text=b.short_label(), anchor="sw",
                fill="white", font=("Segoe UI", 8, "bold"),
            )
            bg = c.create_rectangle(c.bbox(label), fill="#cf222e" if sel else color, outline="")
            c.tag_lower(bg, label)
        self.refresh_tree()

    def refresh_tree(self):
        self.tree.delete(*self.tree.get_children())
        for i, b in enumerate(self.blocks):
            self.tree.insert("", "end", iid=str(i), values=(f"{i + 1}. {b.describe()}",))
        if self.selected in self.blocks:
            iid = str(self.blocks.index(self.selected))
            self.tree.selection_set(iid)
            self.tree.see(iid)

    # ---- mouse -----------------------------------------------------------
    def canvas_xy(self, event):
        return self.canvas.canvasx(event.x) / self.zoom, self.canvas.canvasy(event.y) / self.zoom

    def on_wheel(self, event):
        if event.state & 0x0004:  # Ctrl: zoom
            self.set_zoom(self.zoom * (1.1 if event.delta > 0 else 1 / 1.1))
        else:
            self.canvas.yview_scroll(int(-event.delta / 40), "units")

    def on_press(self, event):
        if self.page is None:
            return
        x, y = self.canvas_xy(event)
        hit = [b for b in self.blocks if b.contains(x, y)]
        if hit:
            self.select(min(hit, key=lambda b: (b.x1 - b.x0) * (b.y1 - b.y0)))
            self.drag_start = None
            return
        self.drag_start = (x, y)
        self.drag_rect = None

    def on_drag(self, event):
        if not self.drag_start:
            return
        x, y = self.canvas_xy(event)
        x0, y0 = self.drag_start
        z = self.zoom
        if self.drag_rect:
            self.canvas.coords(self.drag_rect, x0 * z, y0 * z, x * z, y * z)
        else:
            self.drag_rect = self.canvas.create_rectangle(
                x0 * z, y0 * z, x * z, y * z, outline="#cf222e", dash=(4, 2), width=2
            )

    def on_release(self, event):
        if not self.drag_start:
            return
        x, y = self.canvas_xy(event)
        x0, y0 = self.drag_start
        self.drag_start = None
        if self.drag_rect:
            self.canvas.delete(self.drag_rect)
            self.drag_rect = None
        x0, x1 = sorted((x0, x))
        y0, y1 = sorted((y0, y))
        if x1 - x0 < 10 or y1 - y0 < 10:
            return
        self.add_block_from_rect(x0, y0, x1, y1)

    def add_block_from_rect(self, x0, y0, x1, y1):
        inside = [b for b in self.bubbles if x0 <= b.cx <= x1 and y0 <= b.cy <= y1]
        if len(inside) >= 2:
            new = tb.block_from_bubbles(inside)
        else:
            rows = simpledialog.askinteger(
                TITLE, "Tidak ada bulatan terdeteksi di kotak ini.\nJumlah baris bulatan:",
                parent=self, minvalue=1, maxvalue=200,
            )
            if not rows:
                return
            cols = simpledialog.askinteger(
                TITLE, "Jumlah kolom bulatan:", parent=self, minvalue=1, maxvalue=50
            )
            if not cols:
                return
            size = self.bubble_size()
            bw = min(size[0], (x1 - x0) / cols)
            bh = min(size[1], (y1 - y0) / rows)
            new = [tb.block_from_rect(x0, y0, x1, y1, rows, cols, bw, bh)]
        # Replace blocks the new one covers
        covered = [
            b for b in self.blocks
            if x0 <= (b.x0 + b.x1) / 2 <= x1 and y0 <= (b.y0 + b.y1) / 2 <= y1
        ]
        self.blocks = [b for b in self.blocks if b not in covered] + new
        tb.number_mcq_blocks(self.blocks)
        self.blocks = tb.sort_blocks(self.blocks)
        self.select(new[0])

    def bubble_size(self):
        if self.bubbles:
            return (float(np.median([b.w for b in self.bubbles])),
                    float(np.median([b.h for b in self.bubbles])))  # fmt: skip
        return (self.page_dims[0] * 0.022,) * 2

    # ---- block properties ------------------------------------------------
    def on_tree_select(self, _event=None):
        sel = self.tree.selection()
        if sel and int(sel[0]) < len(self.blocks):
            block = self.blocks[int(sel[0])]
            if block is not self.selected:
                self.select(block)

    def select(self, block):
        self.selected = block
        self.load_props()
        self.refresh()

    def set_props_state(self, enabled):
        state = "normal" if enabled else "disabled"
        for w in (self.start_entry, self.values_entry):
            w.configure(state=state)
        for w in (self.kind_box, self.dir_box):
            w.configure(state="readonly" if enabled else "disabled")
        self.group_box.configure(state=state)
        self.section_box.configure(state=state)

    def load_props(self):
        b = self.selected
        if b is None:
            self.set_props_state(False)
            self.shape_var.set("Pilih sebuah blok.")
            return
        self.set_props_state(True)
        self.shape_var.set(f"Ukuran: {b.rows} baris x {b.cols} kolom bulatan")
        self.kind_var.set(KIND_LABELS[b.kind])
        self.start_var.set(str(b.start))
        self.section_var.set(b.section)
        self.section_box["values"] = sorted({x.section for x in self.blocks if x.kind == tb.KIND_MCQ and x.section}, key=tb.section_order)
        self.group_var.set(b.group)
        self.values_var.set(", ".join(b.values))
        self.dir_var.set(DIRECTION_LABELS[b.horizontal])
        self.update_prop_visibility()

    def kind_from_label(self):
        return next(k for k, v in KIND_LABELS.items() if v == self.kind_var.get())

    def on_kind_change(self):
        b = self.selected
        if b is None:
            return
        kind = self.kind_from_label()
        probe = tb.Block(b.x0, b.y0, b.rows, b.cols, b.gap_x, b.gap_y, b.bw, b.bh)
        tb.set_kind(probe, kind, horizontal=b.horizontal)
        self.values_var.set(", ".join(probe.values))
        self.dir_var.set(DIRECTION_LABELS[probe.horizontal])
        if kind != tb.KIND_MCQ and not self.group_var.get():
            self.group_var.set("NIS" if b.cols >= 6 else "")
        self.update_prop_visibility()

    def update_prop_visibility(self):
        kind = self.kind_from_label()
        self.start_entry.configure(state="normal" if kind == tb.KIND_MCQ else "disabled")
        self.section_box.configure(state="normal" if kind == tb.KIND_MCQ else "disabled")
        self.group_box.configure(
            state="normal" if kind in (tb.KIND_DIGITS, tb.KIND_CUSTOM) else "disabled"
        )
        self.values_entry.configure(state="normal" if kind != tb.KIND_IGNORE else "disabled")
        self.dir_box.configure(state="readonly" if kind == tb.KIND_CUSTOM else "disabled")

    def apply_props(self):
        b = self.selected
        if b is None:
            return
        kind = self.kind_from_label()
        horizontal = next(k for k, v in DIRECTION_LABELS.items() if v == self.dir_var.get())
        values = [v.strip() for v in self.values_var.get().split(",") if v.strip()]
        if kind == tb.KIND_MCQ:
            horizontal = not (b.cols == 1 and b.rows > 1)
        expected = b.cols if (kind in (tb.KIND_MCQ, tb.KIND_CUSTOM) and horizontal) else b.rows
        if kind != tb.KIND_IGNORE and len(values) != expected:
            messagebox.showerror(
                TITLE,
                f"Jumlah pilihan ({len(values)}) harus sama dengan jumlah bulatan "
                f"per isian ({expected}).",
                parent=self,
            )
            return
        tb.set_kind(b, kind, values if kind != tb.KIND_IGNORE else None, horizontal)
        if kind == tb.KIND_MCQ:
            try:
                b.start = max(1, int(self.start_var.get()))
            except ValueError:
                messagebox.showerror(TITLE, "Nomor soal awal harus angka.", parent=self)
                return
            section = self.section_var.get().strip()
            if section != b.section:
                b.section = section
                tb.number_mcq_blocks(self.blocks)  # numbering restarts per part
        else:
            b.section = ""
        b.group = self.group_var.get().strip() if kind in (tb.KIND_DIGITS, tb.KIND_CUSTOM) else ""
        self.blocks = tb.sort_blocks(self.blocks)
        self.load_props()
        self.refresh()

    def split_selected(self, by):
        b = self.selected
        if b is None or (b.cols if by == "column" else b.rows) < 2:
            return
        parts = tb.split_block(b, by, self.bubbles)
        i = self.blocks.index(b)
        self.blocks[i : i + 1] = parts
        tb.number_mcq_blocks(self.blocks)
        self.blocks = tb.sort_blocks(self.blocks)
        self.select(parts[0])
        self.status_var.set(f"Blok dipecah menjadi {len(parts)}. Atur pilihan tiap {'kolom' if by == 'column' else 'baris'}.")

    def rename_section(self):
        b = self.selected
        if b is None or b.kind != tb.KIND_MCQ:
            messagebox.showinfo(TITLE, "Pilih dulu blok soal dari bagian yang mau diganti namanya.", parent=self)
            return
        new = simpledialog.askstring(
            TITLE, f"Nama baru untuk bagian '{b.section or '(tanpa nama)'}':",
            parent=self, initialvalue=b.section,
        )
        if new is None:
            return
        old = b.section
        for x in self.blocks:
            if x.kind == tb.KIND_MCQ and x.section == old:
                x.section = new.strip()
        self.blocks = tb.sort_blocks(self.blocks)
        self.load_props()
        self.refresh()

    def delete_block(self):
        if self.selected in self.blocks:
            self.blocks.remove(self.selected)
            self.selected = None
            self.load_props()
            self.refresh()

    def renumber(self):
        tb.number_mcq_blocks(self.blocks)
        self.load_props()
        self.refresh()

    # ---- saving ----------------------------------------------------------
    def collect(self):
        """Build template + evaluation; returns None after showing errors."""
        if self.page is None:
            messagebox.showinfo(TITLE, "Buka dulu scan LJK kosong.", parent=self)
            return None
        template, problems = tb.build_template(self.blocks, self.sheet)
        if problems:
            messagebox.showerror(TITLE, "Template belum bisa disimpan:\n\n- " + "\n- ".join(problems), parent=self)
            return None

        evaluation = None
        text = "" if self.library else self.key_text.get("1.0", "end").strip()
        if text:
            questions = tb.question_labels(self.blocks)
            allowed = {v for b in self.blocks if b.kind == tb.KIND_MCQ for v in b.values}
            answers, invalid = tb.parse_answer_key(text, allowed)
            if invalid:
                messagebox.showerror(
                    TITLE, f"Kunci jawaban berisi huruf tidak dikenal: {' '.join(sorted(set(invalid)))}",
                    parent=self,
                )
                return None
            if len(answers) > len(questions):
                messagebox.showerror(
                    TITLE, f"Kunci jawaban ({len(answers)}) lebih banyak dari jumlah soal ({len(questions)}).",
                    parent=self,
                )
                return None
            if len(answers) < len(questions) and not messagebox.askyesno(
                TITLE,
                f"Kunci jawaban hanya {len(answers)} dari {len(questions)} soal.\n"
                "Soal sisanya tidak dinilai. Lanjutkan?",
                parent=self,
            ):
                return None
            try:
                scores = [float(v.get().replace(",", ".")) for v in
                          (self.correct_var, self.incorrect_var, self.unmarked_var)]  # fmt: skip
            except ValueError:
                messagebox.showerror(TITLE, "Skor benar/salah/kosong harus angka.", parent=self)
                return None
            scores = [int(s) if s.is_integer() else s for s in scores]
            evaluation = tb.build_evaluation(questions, answers, *scores)
        return template, evaluation

    def save(self):
        result = self.collect()
        if not result:
            return
        template, evaluation = result
        if self.library:
            self.save_to_library(template)
            return
        folder = filedialog.askdirectory(
            parent=self, title="Pilih folder ujian (tempat menaruh scan LJK siswa)"
        )
        if not folder:
            return
        folder = Path(folder)
        if (folder / "template.json").exists() and not messagebox.askyesno(
            TITLE,
            "Folder ini sudah berisi template.json.\nGanti? (file lama disimpan sebagai .bak)",
            parent=self,
        ):
            return
        tb.backup_existing(folder)
        if evaluation is None and (folder / "evaluation.json").exists():
            (folder / "evaluation.json").replace(folder / "evaluation.json.bak")
        written = tb.save_template_folder(folder, self.sheet, template, evaluation, tb.sections_of(self.blocks))
        messagebox.showinfo(
            TITLE,
            f"Template tersimpan di:\n{folder}\n\nFile: {', '.join(written)}\n\n"
            "Taruh hasil scan LJK siswa di folder ini, lalu klik 'Proses LJK'.",
            parent=self,
        )
        if self.on_saved:
            self.on_saved(folder)

    def save_to_library(self, template):
        import ujian

        default = self.template_name or (self.source_path.stem if self.source_path else "LJK")
        name = simpledialog.askstring(
            TITLE, "Nama template (mis. LJK SMPN 3 - 100 soal):", parent=self, initialvalue=default
        )
        if not name:
            return
        folder = ujian.save_to_library(
            name.strip(), self.sheet, template, self.blocks, self.library, replace=self.edit_folder
        )
        self.edit_folder, self.template_name = folder, name.strip()
        messagebox.showinfo(TITLE, f"Template '{name.strip()}' tersimpan di pustaka.", parent=self)
        if self.on_saved:
            self.on_saved(folder)

    def load_from_library(self, folder):
        """Reopen a library template: its blank sheet and labelled blocks."""
        import ujian

        self.sheet, self.blocks, self.template_name = ujian.load_for_editing(folder)
        self.edit_folder = Path(folder)
        self.page, self.page_dims = self.sheet.page, self.sheet.page_dims
        self.bubbles = tb.detect_bubbles(self.page)  # for drawing new blocks
        self.selected = None
        self.title(f"{TITLE} - {self.template_name}")
        self.status_var.set(f"Mengedit '{self.template_name}'. Ubah blok lalu simpan.")
        self.after(50, self.fit_zoom)
        self.refresh()

    # ---- testing with a filled sheet -------------------------------------
    def test_with_scan(self):
        if self.test_proc and self.test_proc.is_alive():
            return
        result = self.collect()
        if not result:
            return
        template, evaluation = result
        path = filedialog.askopenfilename(
            parent=self,
            title="Pilih satu scan LJK yang sudah diisi",
            filetypes=[("Gambar / PDF", "*.jpg *.jpeg *.png *.pdf"), ("Semua file", "*.*")],
        )
        if not path:
            return
        work = Path(tempfile.mkdtemp(prefix="omr_uji_"))
        exam, out = work / "ujian", work / "hasil"
        tb.save_template_folder(exam, self.sheet, template, evaluation)
        shutil.copy2(path, exam / Path(path).name)

        if self.run_worker is None:
            messagebox.showerror(TITLE, "Pengujian tidak tersedia.", parent=self)
            return
        ctx = mp.get_context("spawn")
        self.test_q = ctx.Queue()
        self.test_log = []
        self.test_proc = ctx.Process(
            target=self.run_worker, args=(self.test_q, str(exam), str(out), {}), daemon=True
        )
        self.test_proc.start()
        self.test_out = out
        self.status_var.set("Menguji template...")
        self.config(cursor="watch")
        self.after(150, self.poll_test)

    def poll_test(self):
        done = None
        try:
            while True:
                msg = self.test_q.get_nowait()
                if msg[0] == "log":
                    self.test_log.append(msg[1])
                else:
                    done = msg
        except (queue.Empty, EOFError, OSError):
            pass
        if not done and self.test_proc.is_alive():
            self.after(150, self.poll_test)
            return
        self.config(cursor="")
        self.status_var.set("Pengujian selesai.")
        if not done or not done[1]:
            reason = done[2] if done else "proses berhenti"
            show_text(self, "Uji template gagal", f"{reason}\n\n" + "".join(self.test_log)[-4000:])
            return
        files = list(self.test_out.rglob("Results_*.csv"))
        rows = []
        if files:
            with open(files[0], newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
        if not rows:
            show_text(
                self, "Uji template",
                "LJK tidak terbaca (mungkin gagal disejajarkan).\n\n" + "".join(self.test_log)[-4000:],
            )
            return
        row = rows[0]
        skip = {"file_id", "input_path", "output_path"}
        lines = [f"{k:>12} : {v if v != '' else '(kosong)'}" for k, v in row.items() if k not in skip]
        marked = Path(row.get("output_path", ""))
        show_text(
            self, "Hasil uji template",
            "Cocokkan dengan isian di LJK:\n\n" + "\n".join(lines),
            image=marked if marked.exists() else None,
        )


def open_file(path):
    if sys.platform.startswith("win"):
        os.startfile(str(path))
    else:
        subprocess.Popen(["xdg-open", str(path)])


def show_text(master, title, text, image=None):
    win = tk.Toplevel(master)
    win.title(title)
    win.geometry("560x600")
    box = tk.Text(win, wrap="none", font="TkFixedFont")
    box.insert("1.0", text)
    box.configure(state="disabled")
    box.pack(fill="both", expand=True, padx=8, pady=8)
    bar = ttk.Frame(win)
    bar.pack(fill="x", padx=8, pady=(0, 8))
    if image:
        ttk.Button(bar, text="Lihat gambar LJK bertanda", command=lambda: open_file(image)).pack(
            side="left"
        )
    ttk.Button(bar, text="Tutup", command=win.destroy).pack(side="right")
