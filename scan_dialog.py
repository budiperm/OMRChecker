"""

 "Scan dari scanner" dialog of wizard step 3: pick a scanner and settings,
 scan every sheet in the ADF (or one from the glass) into the LJK folder.

 Searching for scanners and scanning run in worker threads (scanner.py);
 the dialog polls their queue so the window stays responsive.

"""

import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

import scanner

PAPERS = [("", "Bawaan scanner"), ("A4", "A4"), ("F4", "F4 / Folio")]
NO_DEVICE = ("Tidak ada scanner terdeteksi. Pastikan scanner menyala, kabel USB terpasang, dan driver "
             "dari produsen sudah diinstal, lalu klik Cari ulang. Bisa juga scan dengan program bawaan "
             "scanner ke folder ini.")  # fmt: skip


class ScanDialog(tk.Toplevel):
    def __init__(self, master, folder, on_page=None, backends=scanner.BACKENDS, title="Scan dari scanner"):
        super().__init__(master)
        self.title(title)
        self.transient(master.winfo_toplevel())
        self.resizable(False, False)
        self.folder, self.on_page, self.backends = folder, on_page, backends
        self.opts = scanner.Options.load()
        self.devices = []
        self.events = queue.Queue()
        self.cancel = threading.Event()
        self.worker = None

        f = ttk.Frame(self, padding=12)
        f.pack(fill="both", expand=True)
        f.columnconfigure(0, pad=12)
        f.columnconfigure(1, weight=1)

        ttk.Label(f, text="Scanner").grid(row=0, column=0, sticky="w", pady=3)
        self.device = tk.StringVar()
        self.device_box = ttk.Combobox(f, textvariable=self.device, state="readonly", width=48)
        self.device_box.grid(row=0, column=1, sticky="we", pady=3)
        self.device_box.bind("<<ComboboxSelected>>", lambda e: self.on_device())
        self.refresh_btn = ttk.Button(f, text="Cari ulang", command=self.find)
        self.refresh_btn.grid(row=0, column=2, padx=(6, 0))
        self.device_info = tk.StringVar()
        ttk.Label(f, textvariable=self.device_info, style="Muted.TLabel", wraplength=520, justify="left").grid(
            row=1, column=1, columnspan=2, sticky="w")  # fmt: skip

        ttk.Label(f, text="Sumber").grid(row=2, column=0, sticky="nw", pady=(8, 3))
        src = ttk.Frame(f)
        src.grid(row=2, column=1, columnspan=2, sticky="w", pady=(8, 3))
        self.feeder = tk.BooleanVar(value=self.opts.feeder)
        ttk.Radiobutton(src, text="ADF / pengumpan kertas (semua lembar sekaligus)", variable=self.feeder,
                        value=True, command=self.on_source).pack(anchor="w")  # fmt: skip
        ttk.Radiobutton(src, text="Kaca (flatbed), satu lembar", variable=self.feeder, value=False,
                        command=self.on_source).pack(anchor="w")  # fmt: skip
        self.duplex = tk.BooleanVar(value=self.opts.duplex)
        self.duplex_cb = ttk.Checkbutton(src, text="Dua sisi (hanya bila LJK dicetak bolak-balik)", variable=self.duplex)
        self.duplex_cb.pack(anchor="w", padx=(20, 0))

        ttk.Label(f, text="Resolusi").grid(row=3, column=0, sticky="w", pady=3)
        row = ttk.Frame(f)
        row.grid(row=3, column=1, columnspan=2, sticky="w", pady=3)
        self.dpi = tk.StringVar(value=str(self.opts.dpi))
        ttk.Combobox(row, textvariable=self.dpi, values=["200", "300"], state="readonly", width=6).pack(side="left")
        ttk.Label(row, text="dpi").pack(side="left", padx=(4, 20))
        self.color = tk.BooleanVar(value=self.opts.color)
        ttk.Radiobutton(row, text="Abu-abu", variable=self.color, value=False).pack(side="left")
        ttk.Radiobutton(row, text="Berwarna", variable=self.color, value=True).pack(side="left", padx=(8, 0))

        ttk.Label(f, text="Ukuran kertas").grid(row=4, column=0, sticky="w", pady=3)
        self.paper = tk.StringVar(value=dict(PAPERS).get(self.opts.paper, PAPERS[0][1]))
        ttk.Combobox(f, textvariable=self.paper, values=[label for _, label in PAPERS], state="readonly",
                     width=16).grid(row=4, column=1, sticky="w", pady=3)  # fmt: skip

        self.show_ui = tk.BooleanVar(value=self.opts.show_ui)
        self.show_ui_cb = ttk.Checkbutton(f, variable=self.show_ui,
                                          text="Tampilkan jendela driver scanner (pakai bila scan langsung gagal)")  # fmt: skip
        self.show_ui_cb.grid(row=5, column=1, columnspan=2, sticky="w", pady=(6, 3))

        ttk.Label(f, text="Simpan ke").grid(row=6, column=0, sticky="nw", pady=(8, 3))
        ttk.Label(f, text=f"{folder}\n(nama file scan_0001.jpg, scan_0002.jpg, ...; file lama tidak ditimpa)",
                  style="Muted.TLabel", wraplength=520, justify="left").grid(row=6, column=1, columnspan=2, sticky="w",
                                                                          pady=(8, 3))  # fmt: skip

        ttk.Separator(f).grid(row=7, column=0, columnspan=3, sticky="we", pady=10)
        self.status = tk.StringVar()
        ttk.Label(f, textvariable=self.status, wraplength=560, justify="left").grid(row=8, column=0, columnspan=3,
                                                                                   sticky="w")  # fmt: skip
        bar = ttk.Frame(f)
        bar.grid(row=9, column=0, columnspan=3, sticky="e", pady=(10, 0))
        self.start_btn = ttk.Button(bar, text="Mulai scan", command=self.start, style="Accent.TButton")
        self.start_btn.pack(side="left")
        self.stop_btn = ttk.Button(bar, text="Berhenti", command=self.stop, state="disabled")
        self.stop_btn.pack(side="left", padx=6)
        self.close_btn = ttk.Button(bar, text="Tutup", command=self.close)
        self.close_btn.pack(side="left")

        self.protocol("WM_DELETE_WINDOW", self.close)
        self.on_source()
        self.find()
        self.poll()
        self.grab_set()

    # scanners
    def find(self):
        if self.worker and self.worker.is_alive():
            return
        self.device_box["values"] = []
        self.device.set("")
        self.device_info.set("Mencari scanner...")
        self.set_running(True, searching=True)
        self.worker = threading.Thread(
            target=lambda: self.events.put(("devices", *scanner.list_devices(self.backends))), daemon=True)  # fmt: skip
        self.worker.start()

    def show_devices(self, devices, problems):
        self.devices = devices
        self.device_box["values"] = [d.label for d in devices]
        keep = next((d for d in devices if d.key == self.opts.device), devices[0] if devices else None)
        self.device.set(keep.label if keep else "")
        self.device_info.set("" if devices else "\n".join([NO_DEVICE, *problems]))
        self.on_device()

    def selected(self):
        return next((d for d in self.devices if d.label == self.device.get()), None)

    def on_device(self):
        d = self.selected()
        self.show_ui_cb.configure(state="normal" if d and d.backend == "TWAIN" else "disabled")
        if d:
            self.device_info.set("Lewat driver TWAIN." if d.backend == "TWAIN" else "Lewat WIA (Windows).")

    def on_source(self):
        self.duplex_cb.configure(state="normal" if self.feeder.get() else "disabled")

    # scanning
    def read_options(self):
        d = self.selected()
        return scanner.Options(
            device=d.key if d else self.opts.device, feeder=self.feeder.get(),
            duplex=self.feeder.get() and self.duplex.get(), dpi=int(self.dpi.get() or 300), color=self.color.get(),
            paper=next((k for k, label in PAPERS if label == self.paper.get()), ""),
            show_ui=self.show_ui.get() and bool(d) and d.backend == "TWAIN",
        )  # fmt: skip

    def start(self):
        d = self.selected()
        if d is None:
            messagebox.showerror(self.title(), "Pilih scanner dulu.", parent=self)
            return
        self.opts = self.read_options()
        try:
            self.opts.save()
        except OSError:
            pass
        self.cancel.clear()
        self.set_running(True)
        self.status.set("Menyiapkan scanner..." if not self.opts.show_ui else "Atur dan mulai scan di jendela driver scanner.")
        opts, folder = self.opts, self.folder

        def run():
            try:
                saved, warnings = scanner.scan(d, opts, folder, on_page=lambda p, n: self.events.put(("page", p, n)),
                                               cancelled=self.cancel.is_set, backends=self.backends)  # fmt: skip
                self.events.put(("done", len(saved), warnings))
            except scanner.ScanError as e:
                self.events.put(("error", str(e), len(getattr(e, "saved", []))))

        self.worker = threading.Thread(target=run, daemon=True)
        self.worker.start()

    def stop(self):
        self.cancel.set()
        self.status.set("Menghentikan setelah lembar yang sedang di-scan...")

    def set_running(self, running, searching=False):
        state = "disabled" if running else "normal"
        for w in (self.start_btn, self.refresh_btn, self.device_box):
            w.configure(state=state if w is not self.device_box else ("disabled" if running else "readonly"))
        self.stop_btn.configure(state="normal" if running and not searching else "disabled")

    def poll(self):
        try:
            while True:
                kind, *data = self.events.get_nowait()
                if kind == "devices":
                    self.set_running(False)
                    self.show_devices(*data)
                elif kind == "page":
                    path, count = data
                    self.status.set(f"{count} lembar ter-scan... (terakhir: {path.name})")
                    if self.on_page:
                        self.on_page(path)
                elif kind == "done":
                    count, warnings = data
                    self.set_running(False)
                    text = f"Selesai: {count} lembar tersimpan." if count else "Tidak ada lembar yang ter-scan."
                    if self.cancel.is_set():
                        text = f"Dihentikan: {count} lembar tersimpan."
                    if warnings:
                        text += "\nCatatan: " + "; ".join(warnings) + "."
                    self.status.set(text + "\nMasukkan LJK berikutnya lalu klik Mulai scan, atau Tutup.")
                elif kind == "error":
                    message, count = data
                    self.set_running(False)
                    kept = f"\n{count} lembar sebelumnya sudah tersimpan." if count else ""
                    self.status.set(f"Gagal: {message}{kept}")
                    hint = ""
                    if self.opts.device.startswith("TWAIN:") and not self.opts.show_ui:
                        hint = "\n\nCoba centang 'Tampilkan jendela driver scanner', atau pilih scanner yang sama versi WIA."
                    messagebox.showerror(self.title(), message + kept + hint, parent=self)
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(100, self.poll)

    def close(self):
        if self.worker and self.worker.is_alive() and str(self.stop_btn["state"]) == "normal":
            if not messagebox.askyesno(self.title(), "Scan masih berjalan. Hentikan?", parent=self):
                return
            self.cancel.set()
            self.status.set("Menunggu scanner berhenti...")
            self.after(300, self.close_when_idle)
            return
        self.destroy()

    def close_when_idle(self):
        if self.worker and self.worker.is_alive():
            self.after(300, self.close_when_idle)
            return
        self.poll_once_and_destroy()

    def poll_once_and_destroy(self):
        try:
            while True:
                kind, *data = self.events.get_nowait()
                if kind == "page" and self.on_page:
                    self.on_page(data[0])
        except queue.Empty:
            pass
        self.destroy()
