"""

 OMRChecker GUI (Windows desktop front-end)

 Tkinter front-end for OMRChecker. Processing runs in a separate process so
 OpenCV image windows, exit() calls and global state of the core stay isolated
 from the GUI.

"""

import csv
import faulthandler
import json
import multiprocessing as mp
import os
import queue
import subprocess
import sys
import time
import traceback
from pathlib import Path

APP_NAME = "OMRChecker"
APP_TITLE = "OMRChecker - Pemindai LJK"


def resource_dir():
    # Folder holding bundled files (PyInstaller) or this script
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def app_dir():
    # Folder holding the .exe (frozen) or this script
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def settings_path():
    base = os.environ.get("APPDATA") or Path.home().joinpath(".config")
    return Path(base, APP_NAME, "gui_settings.json")


def open_path(path):
    path = str(path)
    if sys.platform.startswith("win"):
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


RESULT_ENTRIES = {"Results", "CheckedOMRs", "Manual", "Evaluation", "omrchecker_log.txt", "ujian.json"}


def foreign_files(folder):
    """Files in an output folder that OMRChecker did not create there.

    Output folders mirror the input tree, so any sub-folder must itself
    hold only result entries."""
    stray = []
    for entry in Path(folder).iterdir():
        if entry.name in RESULT_ENTRIES:
            continue
        if entry.is_dir():
            stray.extend(foreign_files(entry))
        else:
            stray.append(entry)
    return stray


# ---------------------------------------------------------------------------
# Worker process
# ---------------------------------------------------------------------------


class QueueStream:
    """File-like object that forwards text to the GUI process."""

    def __init__(self, q):
        self.q = q

    def write(self, text):
        if text:
            self.q.put(("log", text))
        return len(text)

    def flush(self):
        pass

    def isatty(self):
        return False


def register_processors():
    # ProcessorManager discovers processors with pkgutil.walk_packages, which
    # finds nothing inside a PyInstaller bundle, so register them explicitly.
    # Static imports also make PyInstaller bundle these modules.
    import inspect

    from src.processors import (
        AlignOnMarkers,
        CropOnMarkers,
        CropPage,
        FeatureBasedAlignment,
        builtins,
    )
    from src.processors.manager import PROCESSOR_MANAGER, Processor

    if PROCESSOR_MANAGER.processors:
        return
    for module in (builtins, AlignOnMarkers, CropOnMarkers, CropPage, FeatureBasedAlignment):
        for _, cls in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(cls, Processor)
                and cls is not Processor
                and cls.__module__ == module.__name__
            ):
                PROCESSOR_MANAGER.processors[cls.__name__] = cls


def run_worker(q, input_dir, output_dir, options):
    stream = QueueStream(q)
    sys.stdout = stream
    sys.stderr = stream
    os.environ["COLUMNS"] = "110"
    if not options.get("show_images"):
        os.environ["MPLBACKEND"] = "Agg"

    try:
        sys.path.insert(0, str(resource_dir()))

        import logging

        from src.logger import logger  # noqa: F401  (sets up logging)

        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter("%(levelname)-7s %(message)s"))
        root = logging.getLogger()
        root.handlers = [handler]

        import src.entry as entry
        from src.defaults import CONFIG_DEFAULTS

        register_processors()

        # One ("progress", n) message per sheet (PDF page) so the GUI does not
        # have to parse log text; sheets listed in options["skip"] as
        # [folder relative to the scans, file_id] were read in an earlier,
        # stopped run and are not read again.
        skip = {tuple(k) for k in options.get("skip", ())}
        scans_root = Path(input_dir)
        process_one = entry._process_single_image
        seen = [0]

        def process_or_skip(file_path, img_name, *rest):
            seen[0] += 1
            try:
                rel = Path(file_path).parent.relative_to(scans_root).as_posix()
            except ValueError:
                rel = "."
            if (rel, img_name) not in skip:
                process_one(file_path, img_name, *rest)
            q.put(("progress", seen[0]))

        entry._process_single_image = process_or_skip

        def apply_overrides(config):
            if not options.get("show_images"):
                config.outputs.show_image_level = 0
            if options.get("auto_align"):
                config.alignment_params.auto_align = True
            return config

        # CONFIG_DEFAULTS is used as-is when a folder has no config.json
        apply_overrides(CONFIG_DEFAULTS)
        original_open_config = entry.open_config_with_defaults
        entry.open_config_with_defaults = lambda p: apply_overrides(
            original_open_config(p)
        )

        args = {
            "input_paths": [str(input_dir)],
            "debug": True,
            "output_dir": str(output_dir),
            "autoAlign": bool(options.get("auto_align")),
            "setLayout": bool(options.get("set_layout")),
        }
        template_dir = options.get("template_dir")
        if template_dir:
            # Wizard: template from the library, scan folder left untouched
            from src.template import Template

            template_dir = Path(template_dir)
            config_path = template_dir / "config.json"
            config = (
                entry.open_config_with_defaults(config_path)
                if config_path.exists()
                else CONFIG_DEFAULTS
            )
            template = Template(template_dir / "template.json", config)
            scans = Path(input_dir)
            # Ignore template/config/evaluation files left in the scan folders
            # by the advanced mode: the wizard's template and scoring apply
            entry.TEMPLATE_FILENAME = "__wizard_ignores_template__.json"
            entry.CONFIG_FILENAME = "__wizard_ignores_config__.json"
            entry.EVALUATION_FILENAME = "__wizard_ignores_evaluation__.json"
            # No file is skipped by name here: a template may well be made
            # from a filled sheet that is also graded. Blank sheets are hidden
            # when the results are scored (ujian.score_results).
            entry.process_dir(scans, scans, args, template, config)
        else:
            entry.entry_point(Path(input_dir), args)
        q.put(("done", True, ""))
    except SystemExit as e:
        q.put(("done", False, f"Proses berhenti (kode {e.code}). Lihat log di atas."))
    except BaseException as e:  # noqa: BLE001
        traceback.print_exc()
        q.put(("done", False, str(e)))


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------


def run_gui(mainloop=True):
    """Build the main window; tests pass mainloop=False to drive it."""
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    from tkinter.scrolledtext import ScrolledText

    import theme

    if sys.platform.startswith("win"):
        try:
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

    class App(tk.Tk):
        def __init__(self):
            super().__init__()
            theme.apply(self)
            self.title(APP_TITLE)
            self.geometry("1100x720")
            self.minsize(820, 560)

            self.ctx = mp.get_context("spawn")
            self.proc = None
            self.q = None
            self.run_started = 0
            self.result_files = []
            self.current_rows = []
            self.current_header = []

            self.input_var = tk.StringVar()
            self.output_var = tk.StringVar()
            self.auto_align_var = tk.BooleanVar(value=False)
            self.set_layout_var = tk.BooleanVar(value=False)
            self.show_images_var = tk.BooleanVar(value=False)
            self.status_var = tk.StringVar(value="Siap.")
            self.result_choice = tk.StringVar()

            self.load_settings()
            self.build_ui()
            self.protocol("WM_DELETE_WINDOW", self.on_close)
            self.after(200, self.refresh_results)

        # ---- settings ----------------------------------------------------
        def load_settings(self):
            try:
                data = json.loads(settings_path().read_text(encoding="utf-8"))
            except Exception:
                data = {}
            self.input_var.set(data.get("input_dir", ""))
            self.output_var.set(data.get("output_dir", ""))
            self.auto_align_var.set(data.get("auto_align", False))

        def save_settings(self):
            data = {
                "input_dir": self.input_var.get(),
                "output_dir": self.output_var.get(),
                "auto_align": self.auto_align_var.get(),
            }
            try:
                settings_path().parent.mkdir(parents=True, exist_ok=True)
                settings_path().write_text(json.dumps(data, indent=2), encoding="utf-8")
            except Exception:
                pass

        # ---- layout ------------------------------------------------------
        def build_ui(self):
            pad = {"padx": 8, "pady": 4}

            form = ttk.LabelFrame(self, text="Folder")
            form.pack(fill="x", padx=10, pady=(10, 4))
            form.columnconfigure(1, weight=1)

            ttk.Label(form, text="Folder input (gambar scan + template.json):").grid(
                row=0, column=0, sticky="w", **pad
            )
            ttk.Entry(form, textvariable=self.input_var).grid(
                row=0, column=1, sticky="ew", **pad
            )
            ttk.Button(form, text="Pilih...", command=self.pick_input).grid(
                row=0, column=2, **pad
            )

            ttk.Label(form, text="Folder hasil:").grid(row=1, column=0, sticky="w", **pad)
            ttk.Entry(form, textvariable=self.output_var).grid(
                row=1, column=1, sticky="ew", **pad
            )
            ttk.Button(form, text="Pilih...", command=self.pick_output).grid(
                row=1, column=2, **pad
            )

            opts = ttk.LabelFrame(self, text="Opsi")
            opts.pack(fill="x", padx=10, pady=4)
            ttk.Checkbutton(
                opts,
                text="Auto align (untuk scan yang sedikit bergeser)",
                variable=self.auto_align_var,
            ).pack(side="left", **pad)
            ttk.Checkbutton(
                opts,
                text="Mode atur layout template",
                variable=self.set_layout_var,
            ).pack(side="left", **pad)
            ttk.Checkbutton(
                opts,
                text="Tampilkan jendela gambar proses (debug)",
                variable=self.show_images_var,
            ).pack(side="left", **pad)

            actions = ttk.Frame(self)
            actions.pack(fill="x", padx=10, pady=4)
            self.run_btn = ttk.Button(actions, text="▶  Proses LJK", command=self.start)
            self.run_btn.pack(side="left", padx=(0, 6))
            self.stop_btn = ttk.Button(
                actions, text="■  Stop", command=self.stop, state="disabled"
            )
            self.stop_btn.pack(side="left", padx=6)
            ttk.Button(
                actions, text="Buka folder hasil", command=self.open_output
            ).pack(side="left", padx=6)
            ttk.Button(actions, text="Buat template...", command=self.open_editor).pack(
                side="left", padx=6
            )
            ttk.Button(actions, text="Contoh template", command=self.open_samples).pack(
                side="left", padx=6
            )
            self.progress = ttk.Progressbar(actions, mode="determinate", length=180)
            self.progress.pack(side="right")

            self.tabs = ttk.Notebook(self)
            self.tabs.pack(fill="both", expand=True, padx=10, pady=4)

            # Results tab
            res = ttk.Frame(self.tabs)
            self.tabs.add(res, text="Hasil")
            bar = ttk.Frame(res)
            bar.pack(fill="x", pady=4)
            ttk.Label(bar, text="File hasil:").pack(side="left", padx=(4, 4))
            self.result_combo = ttk.Combobox(
                bar, textvariable=self.result_choice, state="readonly", width=70
            )
            self.result_combo.pack(side="left", fill="x", expand=True)
            self.result_combo.bind("<<ComboboxSelected>>", lambda e: self.show_result())
            ttk.Button(bar, text="Muat ulang", command=self.refresh_results).pack(
                side="left", padx=4
            )
            ttk.Button(bar, text="Export Excel", command=self.export_excel).pack(
                side="left", padx=4
            )
            ttk.Button(bar, text="Buka CSV", command=self.open_csv).pack(
                side="left", padx=4
            )
            ttk.Button(bar, text="Hapus hasil", command=self.clear_results).pack(
                side="left", padx=4
            )

            split = ttk.Panedwindow(res, orient="horizontal")
            split.pack(fill="both", expand=True)
            self.split = split
            self.user_moved_sash = False
            split.bind("<Configure>", self.place_sash)
            split.bind("<ButtonRelease-1>", self.sash_moved)
            # Fixed request size: a wide table must not widen the window or
            # squeeze the preview pane out (the sash decides the split)
            table = ttk.Frame(split, width=400, height=200)
            table.grid_propagate(False)
            split.add(table, weight=3)
            self.tree = ttk.Treeview(table, show="headings", selectmode="browse")
            vsb = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
            hsb = ttk.Scrollbar(table, orient="horizontal", command=self.tree.xview)
            self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
            self.tree.grid(row=0, column=0, sticky="nsew")
            vsb.grid(row=0, column=1, sticky="ns")
            hsb.grid(row=1, column=0, sticky="ew")
            table.rowconfigure(0, weight=1)
            table.columnconfigure(0, weight=1)
            self.tree.bind("<<TreeviewSelect>>", lambda e: self.show_preview())
            self.tree.bind("<Double-1>", self.open_selected_image)

            # Preview of the marked sheet for the selected row
            prev = ttk.Frame(split)
            split.add(prev, weight=2)
            pbar = ttk.Frame(prev)
            pbar.pack(fill="x", pady=(0, 2))
            ttk.Button(pbar, text="−", width=3, command=lambda: self.zoom_preview(1 / 1.25)).pack(side="left")
            ttk.Button(pbar, text="+", width=3, command=lambda: self.zoom_preview(1.25)).pack(side="left")
            ttk.Button(pbar, text="Pas lebar", command=lambda: self.zoom_preview(None)).pack(side="left", padx=4)
            ttk.Button(pbar, text="Buka di aplikasi", command=self.open_selected_image).pack(side="left")
            self.preview_name = tk.StringVar(value="Pilih baris untuk melihat LJK-nya.")
            ttk.Label(prev, textvariable=self.preview_name, foreground=theme.MUTED).pack(anchor="w", padx=2)
            pcv = ttk.Frame(prev)
            pcv.pack(fill="both", expand=True)
            self.preview = tk.Canvas(pcv, background="#e4e8ee", highlightthickness=0)
            pvs = ttk.Scrollbar(pcv, orient="vertical", command=self.preview.yview)
            phs = ttk.Scrollbar(pcv, orient="horizontal", command=self.preview.xview)
            self.preview.configure(yscrollcommand=pvs.set, xscrollcommand=phs.set)
            self.preview.grid(row=0, column=0, sticky="nsew")
            pvs.grid(row=0, column=1, sticky="ns")
            phs.grid(row=1, column=0, sticky="ew")
            pcv.rowconfigure(0, weight=1)
            pcv.columnconfigure(0, weight=1)
            self.preview.bind("<Configure>", lambda e: self.render_preview())
            self.preview.bind("<MouseWheel>", lambda e: self.preview.yview_scroll(int(-e.delta / 40), "units"))
            self.preview.bind("<Button-4>", lambda e: self.preview.yview_scroll(-3, "units"))
            self.preview.bind("<Button-5>", lambda e: self.preview.yview_scroll(3, "units"))
            self.preview_img = None
            self.preview_photo = None
            self.preview_zoom = None  # None: fit the pane width
            ttk.Label(
                res,
                text="Pilih baris (klik atau tombol panah) untuk melihat LJK yang sudah ditandai di kanan.",
                foreground=theme.MUTED,
            ).pack(anchor="w", padx=4, pady=2)

            # Log tab
            logf = ttk.Frame(self.tabs)
            self.tabs.add(logf, text="Log")
            self.log = ScrolledText(logf, wrap="none", font="TkFixedFont")
            self.log.pack(fill="both", expand=True)
            self.log.configure(state="disabled")

            ttk.Label(self, textvariable=self.status_var, anchor="w").pack(
                fill="x", padx=10, pady=(0, 8)
            )

        # ---- folder pickers ---------------------------------------------
        def pick_input(self):
            d = filedialog.askdirectory(
                title="Pilih folder berisi gambar scan LJK dan template.json",
                initialdir=self.input_var.get() or str(Path.home()),
            )
            if d:
                self.input_var.set(d)
                if not self.output_var.get():
                    self.output_var.set(str(Path(d).parent / (Path(d).name + "_hasil")))
                self.refresh_results()

        def pick_output(self):
            d = filedialog.askdirectory(
                title="Pilih folder hasil",
                initialdir=self.output_var.get() or self.input_var.get() or str(Path.home()),
            )
            if d:
                self.output_var.set(d)
                self.refresh_results()

        def open_output(self):
            out = self.output_var.get()
            if out and Path(out).exists():
                open_path(out)
            else:
                messagebox.showinfo(APP_NAME, "Folder hasil belum ada.")

        def open_editor(self):
            try:
                from template_editor import TemplateEditor
            except Exception as e:
                messagebox.showerror(APP_NAME, f"Editor template gagal dibuka:\n{e}")
                return
            TemplateEditor(self, on_saved=self.template_saved, run_worker=run_worker)

        def template_saved(self, folder):
            self.input_var.set(str(folder))
            self.output_var.set(str(Path(folder).parent / (Path(folder).name + "_hasil")))
            self.save_settings()
            self.refresh_results()

        def open_samples(self):
            for d in (app_dir() / "samples", resource_dir() / "samples"):
                if d.exists():
                    open_path(d)
                    return
            messagebox.showinfo(APP_NAME, "Folder contoh tidak ditemukan.")

        # ---- run ---------------------------------------------------------
        def validate(self):
            inp = self.input_var.get().strip()
            out = self.output_var.get().strip()
            if not inp or not Path(inp).is_dir():
                messagebox.showerror(APP_NAME, "Folder input tidak valid.")
                return None
            if not out:
                out = str(Path(inp).parent / (Path(inp).name + "_hasil"))
                self.output_var.set(out)
            inp_res, out_res = Path(inp).resolve(), Path(out).resolve()
            if out_res == inp_res or inp_res in out_res.parents:
                messagebox.showerror(
                    APP_NAME,
                    "Folder hasil tidak boleh sama dengan atau berada di dalam folder input,\n"
                    "karena gambar hasil akan ikut terbaca sebagai LJK pada proses berikutnya.\n\n"
                    f"Contoh folder hasil: {inp_res.parent / (inp_res.name + '_hasil')}",
                )
                return None
            has_template = any(Path(inp).rglob("template.json"))
            if not has_template:
                messagebox.showerror(
                    APP_NAME,
                    "template.json tidak ditemukan di folder input.\n\n"
                    "Salin template.json (dan config.json / evaluation.json bila ada) "
                    "ke folder gambar, atau buat lewat tombol 'Buat template...'.",
                )
                return None
            return Path(inp).resolve(), Path(out).resolve()

        def start(self):
            if self.proc and self.proc.is_alive():
                return
            paths = self.validate()
            if not paths:
                return
            inp, out = paths
            self.save_settings()
            self.clear_log()
            self.tabs.select(1)
            options = {
                "auto_align": self.auto_align_var.get(),
                "set_layout": self.set_layout_var.get(),
                "show_images": self.show_images_var.get() or self.set_layout_var.get(),
            }
            self.q = self.ctx.Queue()
            self.proc = self.ctx.Process(
                target=run_worker, args=(self.q, str(inp), str(out), options), daemon=True
            )
            self.run_started = time.time()
            self.proc.start()
            self.run_btn.configure(state="disabled")
            self.stop_btn.configure(state="normal")
            self.progress.configure(mode="indeterminate")
            self.progress.start(12)
            self.status_var.set("Memproses...")
            self.after(100, self.poll)

        def stop(self):
            if self.proc and self.proc.is_alive():
                self.proc.terminate()
                self.append_log("\nDihentikan oleh pengguna.\n")
                self.finish(False, "Dihentikan.")

        def poll(self):
            done = None
            try:
                while True:
                    msg = self.q.get_nowait()
                    if msg[0] == "log":
                        self.append_log(msg[1])
                    elif msg[0] == "done":
                        done = msg
            except queue.Empty:
                pass
            except (EOFError, OSError):
                pass

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
            self.progress.stop()
            self.progress.configure(mode="determinate", value=0)
            self.run_btn.configure(state="normal")
            self.stop_btn.configure(state="disabled")
            elapsed = round(time.time() - self.run_started, 1)
            if ok:
                self.status_var.set(f"Selesai dalam {elapsed} detik.")
                self.refresh_results()
                if self.current_rows:
                    self.tabs.select(0)
                    self.after(50, self.place_sash)
            else:
                self.status_var.set(f"Gagal: {message}")
                messagebox.showerror(APP_NAME, f"Proses gagal:\n{message}")

        def on_close(self):
            if self.proc and self.proc.is_alive():
                if not messagebox.askyesno(APP_NAME, "Proses masih berjalan. Hentikan dan keluar?"):
                    return
                self.proc.terminate()
            self.save_settings()
            self.destroy()

        # ---- log ---------------------------------------------------------
        def clear_log(self):
            self.log.configure(state="normal")
            self.log.delete("1.0", "end")
            self.log.configure(state="disabled")

        def append_log(self, text):
            self.log.configure(state="normal")
            self.log.insert("end", text)
            self.log.see("end")
            self.log.configure(state="disabled")

        # ---- results -----------------------------------------------------
        def refresh_results(self):
            out = self.output_var.get().strip()
            files = []
            if out and Path(out).is_dir():
                files = sorted(
                    Path(out).rglob("Results/Results_*.csv"),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                )
            self.result_files = files
            labels = [str(p.relative_to(out)) for p in files]
            self.result_combo["values"] = labels
            if labels:
                self.result_combo.current(0)
            else:
                self.result_choice.set("")
            self.show_result()

        def selected_result_file(self):
            idx = self.result_combo.current()
            if 0 <= idx < len(self.result_files):
                return self.result_files[idx]
            return None

        def show_result(self):
            self.tree.delete(*self.tree.get_children())
            self.current_rows, self.current_header = [], []
            path = self.selected_result_file()
            if not path:
                self.tree["columns"] = ()
                self.show_preview()
                return
            with open(path, newline="", encoding="utf-8") as f:
                rows = list(csv.reader(f))
            if not rows:
                return
            header, body = rows[0], rows[1:]
            # Re-runs in the same hour append to the same file: keep last per file
            latest = {}
            for r in body:
                if r:
                    latest[r[0]] = r
            body = list(latest.values())
            self.current_header, self.current_rows = header, body

            hidden = {"input_path", "output_path"}
            cols = [c for c in header if c not in hidden]
            self.tree["columns"] = cols
            idx = [header.index(c) for c in cols]
            for c, j in zip(cols, idx):
                longest = max([len(c)] + [len(r[j]) for r in body if j < len(r)])
                width = max(40, min(320, 8 * longest + 18))
                self.tree.heading(c, text=c)
                self.tree.column(c, width=width, anchor="w" if c in ("file_id", "Nama") else "center", stretch=False)
            for i, r in enumerate(body):
                values = [r[j] if j < len(r) else "" for j in idx]
                self.tree.insert("", "end", iid=str(i), values=values)
            self.status_var.set(f"{len(body)} LJK pada {path.name}")
            self.after_idle(self.place_sash)
            if body:
                self.tree.selection_set("0")
            else:
                self.show_preview()

        def place_sash(self, _event=None):
            """Table 55%, preview 45%, until the user drags the divider."""
            width = self.split.winfo_width()
            if not self.user_moved_sash and width > 300:
                self.split.sashpos(0, int(width * 0.55))

        def sash_moved(self, _event=None):
            self.user_moved_sash = True

        def selected_row(self):
            sel = self.tree.selection()
            if not sel or int(sel[0]) >= len(self.current_rows):
                return None
            return self.current_rows[int(sel[0])]

        def row_image(self, row):
            """Marked sheet for a result row, falling back to the scan itself."""
            h = self.current_header

            def cell(key):
                return row[h.index(key)] if key in h and h.index(key) < len(row) else ""

            candidates = [cell("output_path")]
            out = self.output_var.get().strip()
            if out and cell("file_id"):
                candidates += list(Path(out).rglob(f"CheckedOMRs/{cell('file_id')}"))
            candidates.append(cell("input_path"))
            for c in candidates:
                if c and Path(c).is_file():
                    return Path(c)
            return None

        def show_preview(self):
            row = self.selected_row()
            self.preview_img = None
            if row is not None:
                path = self.row_image(row)
                if path is None:
                    self.preview_name.set("Gambar LJK tidak ditemukan.")
                else:
                    try:
                        import cv2
                        import numpy as np

                        self.preview_img = cv2.imdecode(
                            np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR
                        )
                        self.preview_name.set(path.name)
                    except Exception as e:
                        self.preview_name.set(f"Gagal membuka gambar: {e}")
            self.render_preview()

        def zoom_preview(self, factor):
            if factor is None or self.preview_img is None:
                self.preview_zoom = None
            else:
                current = self.preview_zoom or self.fit_zoom()
                self.preview_zoom = min(max(current * factor, 0.1), 4.0)
            self.render_preview()

        def fit_zoom(self):
            width = max(self.preview.winfo_width(), 100)
            return width / self.preview_img.shape[1]

        def render_preview(self):
            c = self.preview
            c.delete("all")
            if self.preview_img is None:
                self.preview_photo = None
                return
            import base64

            import cv2

            z = self.preview_zoom or self.fit_zoom()
            h, w = self.preview_img.shape[:2]
            size = (max(1, int(w * z)), max(1, int(h * z)))
            shown = cv2.resize(self.preview_img, size, interpolation=cv2.INTER_AREA)
            ok, buf = cv2.imencode(".png", shown)
            self.preview_photo = tk.PhotoImage(master=c, data=base64.b64encode(buf.tobytes()))
            c.create_image(0, 0, image=self.preview_photo, anchor="nw")
            c.configure(scrollregion=(0, 0, size[0], size[1]))

        def open_selected_image(self, _event=None):
            row = self.selected_row()
            if row is None:
                return
            path = self.row_image(row)
            if path is None:
                messagebox.showinfo(APP_NAME, "File gambar tidak ditemukan.")
                return
            try:
                open_path(path)
            except OSError as e:
                messagebox.showerror(
                    APP_NAME,
                    f"Windows tidak bisa membuka gambar:\n{path}\n\n{e}\n\n"
                    "Gambar tetap bisa dilihat di panel kanan.",
                )

        def clear_results(self):
            out = self.output_var.get().strip()
            if not out or not Path(out).is_dir():
                messagebox.showinfo(APP_NAME, "Belum ada folder hasil.")
                return
            out = Path(out).resolve()
            inp = self.input_var.get().strip()
            if inp and (out == Path(inp).resolve() or out in Path(inp).resolve().parents):
                messagebox.showerror(APP_NAME, "Folder hasil berisi folder input; tidak dihapus.")
                return
            stray = foreign_files(out)
            if stray:
                messagebox.showerror(
                    APP_NAME,
                    "Folder hasil berisi file yang bukan hasil OMRChecker, jadi tidak dihapus:\n\n"
                    + "\n".join(str(p.relative_to(out)) for p in stray[:5]),
                )
                return
            if not messagebox.askyesno(
                APP_NAME,
                f"Hapus semua hasil di:\n{out}\n\n(nilai, gambar bertanda, log). "
                "Scan LJK di folder input tidak tersentuh.",
            ):
                return
            import shutil

            shutil.rmtree(out)
            self.refresh_results()
            self.status_var.set("Hasil lama dihapus.")

        def open_csv(self):
            path = self.selected_result_file()
            if path:
                open_path(path)

        def export_excel(self):
            path = self.selected_result_file()
            if not path or not self.current_rows:
                messagebox.showinfo(APP_NAME, "Belum ada hasil untuk diekspor.")
                return
            target = filedialog.asksaveasfilename(
                title="Simpan sebagai Excel",
                defaultextension=".xlsx",
                initialfile=path.stem + ".xlsx",
                initialdir=str(path.parent),
                filetypes=[("Excel", "*.xlsx")],
            )
            if not target:
                return
            try:
                import pandas as pd

                df = pd.DataFrame(self.current_rows, columns=self.current_header)
                df["score"] = pd.to_numeric(df["score"], errors="coerce")
                df.to_excel(target, index=False)
                self.status_var.set(f"Tersimpan: {target}")
                if messagebox.askyesno(APP_NAME, "Berhasil diekspor. Buka file sekarang?"):
                    open_path(target)
            except Exception as e:
                messagebox.showerror(APP_NAME, f"Gagal ekspor Excel:\n{e}")

    app = App()
    if mainloop:
        app.mainloop()
    return app


class ListQueue:
    def __init__(self, log_file):
        self.log_file = log_file
        self.result = None

    def put(self, msg):
        if msg[0] == "log":
            self.log_file.write(msg[1])
        elif msg[0] == "done":
            self.result = msg


def run_batch(input_dir, output_dir, template_dir=None):
    """OMRChecker.exe --process <input> <output> [--template <library folder>]:
    process without the GUI. The log is written to <output>/omrchecker_log.txt."""
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    options = {"template_dir": str(Path(template_dir).resolve())} if template_dir else {}
    with open(Path(output_dir, "omrchecker_log.txt"), "w", encoding="utf-8") as f:
        q = ListQueue(f)
        run_worker(q, str(Path(input_dir).resolve()), str(Path(output_dir).resolve()), options)
    return 0 if q.result and q.result[1] else 1


def show_fatal_error(text):
    if sys.platform.startswith("win"):
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, text, APP_TITLE, 0x10)
            return
        except Exception:
            pass
    print(text, file=sys.__stderr__ or sys.stderr)


def main():
    # Windowed builds have no console: record startup progress, Python
    # exceptions and native crashes in crash.log so silent exits can be traced.
    log_path = settings_path().parent / "crash.log"
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log = open(log_path, "w", encoding="utf-8", buffering=1)
        faulthandler.enable(log)
        log.write(f"start {time.ctime()} argv={sys.argv} frozen={getattr(sys, 'frozen', False)}\n")
    except Exception:
        log = None

    try:
        if len(sys.argv) == 4 and sys.argv[1] == "--process":
            return run_batch(sys.argv[2], sys.argv[3])
        if len(sys.argv) == 6 and sys.argv[1] == "--process" and sys.argv[4] == "--template":
            return run_batch(sys.argv[2], sys.argv[3], sys.argv[5])
        if "--cek-scanner" in sys.argv:  # OMRChecker-debug.exe --cek-scanner
            import scanner

            return scanner.main()
        if "--lanjutan" in sys.argv:
            run_gui()  # advanced mode: the original single window
        else:
            from wizard import run_wizard

            run_wizard()
        if log:
            log.write("gui closed normally\n")
        return 0
    except BaseException:
        details = traceback.format_exc()
        if log:
            log.write(details)
        show_fatal_error(f"OMRChecker gagal dijalankan:\n\n{details}\n\nLog: {log_path}")
        return 1


if __name__ == "__main__":
    mp.freeze_support()
    sys.exit(main())
