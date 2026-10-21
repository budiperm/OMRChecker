"""

 Pemindai LJK, new look (prototype): one screen instead of six steps.

   Ringkasan  four cards (template, keys, LJK, output folder) with their
              status and one "Proses LJK" button. A card's button opens that
              wizard step as an editor ("Simpan" = the wizard's Lanjut).
   Hasil      the wizard's step 5 (table, preview, corrections) and step 6
              (item analysis, export), the settings shown as chips above.

 The wizard's steps, the exam session and ujian.py are reused unchanged, so
 both looks read and write the same files and can be used in turn
 (Bantuan > "Kembali ke tampilan lama").

"""

import time
import tkinter as tk
from copy import deepcopy
from pathlib import Path
from tkinter import messagebox, ttk

import theme
import ujian
import wizard as wz
from wizard import APP_TITLE, scan_files

EDITORS = ["Template LJK", "Kunci jawaban", "LJK peserta", "Folder hasil"]


def documents_dir():
    for name in ("Documents", "Dokumen"):
        if (Path.home() / name).is_dir():
            return Path.home() / name
    return Path.home()


def default_scans_dir(exam_name):
    """Where "Scan dari scanner" saves when no LJK folder was chosen yet."""
    name = ujian.safe_name(exam_name.strip()) if exam_name.strip() else time.strftime("Ujian %Y-%m-%d")
    return documents_dir() / "Pemindai LJK" / name / "Scan"


def results_match_scans(out, scans):
    """True when every sheet already read into `out` is one of the scans in
    `scans` (the same exam, read again); False when `out` holds the results
    of other sheets, i.e. of another exam."""
    names = {}
    for p in scan_files(scans):
        names.setdefault(p.parent.relative_to(scans).as_posix(), []).append(p)
    for rel, file_id in ujian.done_sheets(out):
        files = names.get(rel, [])
        if not any(file_id == p.name or file_id.startswith(p.stem) for p in files):
            return False
    return True


class Card(tk.Frame):
    """One setting: title, status, value, detail and its buttons."""

    STATUS = {"ok": ("✓ Siap", theme.DONE), "warn": ("Belum lengkap", theme.WARN),
              "todo": ("Belum diisi", theme.WARN)}  # fmt: skip

    def __init__(self, master, title, status, value, detail, actions):
        super().__init__(master, bg=theme.SURFACE, highlightthickness=1, highlightbackground=theme.BORDER)
        head = tk.Frame(self, bg=theme.SURFACE)
        head.pack(fill="x", padx=16, pady=(14, 4))
        tk.Label(head, text=title.upper(), bg=theme.SURFACE, fg=theme.MUTED, font="SunValleyCaptionFont").pack(side="left")
        text, colour = self.STATUS[status]
        self.status = tk.Label(head, text=text, bg=theme.SURFACE, fg=colour, font="SunValleyBodyStrongFont")
        self.status.pack(side="right")
        self.value = tk.Label(self, text=value, bg=theme.SURFACE, fg=theme.FG, font="SunValleySubtitleFont",
                              anchor="w", justify="left")  # fmt: skip
        self.value.pack(fill="x", padx=16)
        self.detail = tk.Label(self, text=detail, bg=theme.SURFACE, fg=theme.MUTED, anchor="nw", justify="left")
        self.detail.pack(fill="both", expand=True, padx=16, pady=(4, 8))
        bar = tk.Frame(self, bg=theme.SURFACE)
        bar.pack(fill="x", padx=16, pady=(0, 14))
        self.buttons = []
        for label, command, accent in actions:  # one per row: a card is narrow on a small screen
            b = ttk.Button(bar, text=label, command=command, style="Accent.TButton" if accent else "TButton")
            b.pack(anchor="w", fill="x" if len(actions) > 1 else "none", pady=(0, 6))
            self.buttons.append(b)
        self.bind("<Configure>", lambda e: self.wrap(e.width))

    def wrap(self, width):
        for label in (self.value, self.detail):
            label.configure(wraplength=max(120, width - 36))


class Dashboard(wz.Wizard):
    def build(self):
        self.output_policy = None  # chosen in the output editor; else results_match_scans decides
        self.editing = None  # (step index, exam before editing, template before editing)
        self.view = None

        # header: app name, exam name, exam actions
        head = tk.Frame(self, bg=theme.SURFACE)
        head.pack(fill="x")
        brand = tk.Frame(head, bg=theme.SURFACE)
        brand.pack(side="left", padx=(24, 20), pady=12)
        self.logo = theme.logo(self)
        if self.logo:
            tk.Label(brand, image=self.logo, bg=theme.SURFACE).pack(side="left", padx=(0, 10))
        names = tk.Frame(brand, bg=theme.SURFACE)
        names.pack(side="left")
        tk.Label(names, text="Pemindai LJK", bg=theme.SURFACE, fg=theme.FG, font="SunValleySubtitleFont").pack(anchor="w")
        tk.Label(names, text=f"OMRChecker v{wz.VERSION} • tampilan baru", bg=theme.SURFACE, fg=theme.MUTED,
                 font="SunValleyCaptionFont").pack(anchor="w")  # fmt: skip
        exam = tk.Frame(head, bg=theme.SURFACE)
        exam.pack(side="left", fill="x", expand=True, pady=10)
        tk.Label(exam, text="Nama ujian", bg=theme.SURFACE, fg=theme.MUTED, font="SunValleyCaptionFont").pack(anchor="w")
        self.exam_name = tk.StringVar(value=self.exam.name)
        self.name_entry = ttk.Entry(exam, textvariable=self.exam_name, width=40)
        self.name_entry.pack(anchor="w")
        self.exam_name.trace_add("write", lambda *a: setattr(self.exam, "name", self.exam_name.get().strip()))
        actions = tk.Frame(head, bg=theme.SURFACE)
        actions.pack(side="right", padx=24)
        self.help_btn = ttk.Button(actions, text="Bantuan", command=self.show_help_menu)
        self.help_btn.pack(side="right")
        self.open_btn = ttk.Button(actions, text="Buka ujian lama...", command=self.open_exam)
        self.open_btn.pack(side="right", padx=6)
        self.new_btn = ttk.Button(actions, text="Ujian baru", command=self.new_exam)
        self.new_btn.pack(side="right")
        ttk.Separator(self).pack(fill="x")

        main = ttk.Frame(self)
        main.pack(fill="both", expand=True)
        top = ttk.Frame(main)
        top.pack(fill="x", padx=28, pady=(18, 0))
        self.back_btn = ttk.Button(top, text="←  Ringkasan", command=self.show_home)
        self.heading = tk.StringVar()
        self.hint = tk.StringVar()
        self.titles = titles = ttk.Frame(top)
        titles.pack(side="left", fill="x", expand=True)
        ttk.Label(titles, textvariable=self.heading, style="Title.TLabel").pack(anchor="w")
        ttk.Label(titles, textvariable=self.hint, foreground=theme.MUTED).pack(anchor="w", pady=(2, 0))
        self.tabs = ttk.Frame(top)  # Hasil: participants / analysis & export
        self.tab_btns = []
        for i, label in enumerate(("Peserta & koreksi", "Analisis & ekspor")):
            b = ttk.Button(self.tabs, text=label, command=lambda i=i: self.show_tab(i))
            b.pack(side="left", padx=(0, 4))
            self.tab_btns.append(b)

        # editor footer
        self.foot = ttk.Frame(main, style="Footer.TFrame")
        ttk.Separator(self.foot).pack(fill="x")
        self.save_btn = ttk.Button(self.foot, text="Simpan", command=self.save_editor, style="Accent.TButton")
        self.save_btn.pack(side="right", padx=28, pady=12)
        ttk.Button(self.foot, text="Batal", command=self.cancel_editor).pack(side="right", pady=12)

        self.body = ttk.Frame(main)
        self.body.pack(fill="both", expand=True, padx=28, pady=(14, 14))
        self.home = ttk.Frame(self.body)
        self.chips = ttk.Frame(self.body)  # Hasil: the settings, each opens its editor

        self.steps = [cls(self) for cls in (wz.TemplateStep, wz.KeyStep, wz.ScansStep, wz.OutputStep,
                                            wz.ProcessStep, wz.ExportStep)]  # fmt: skip
        self.current = None
        self.reached = 0
        self.tab = 0
        if self.exam.template:
            try:
                self.template = ujian.read_library_template(self.exam.template)
            except (ValueError, OSError):
                self.template = None
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.show_home()

    # views
    def clear_body(self):
        for w in self.body.winfo_children():
            w.pack_forget()
        self.foot.pack_forget()
        self.back_btn.pack_forget()
        self.tabs.pack_forget()
        self.current = None

    def show_home(self):
        if self.busy:
            return
        self.clear_body()
        self.view = "home"
        self.editing = None
        self.exam_name.set(self.exam.name)
        self.heading.set("Persiapan ujian")
        self.hint.set("Ujian berikutnya dengan pengaturan yang sama: langsung klik Proses LJK. "
                      "Ubah hanya bagian yang berbeda.")  # fmt: skip
        self.home.pack(fill="both", expand=True)
        self.refresh_home()

    def go(self, i):
        """What the wizard's code (open_exam, new_exam) asks for, in this look."""
        if i >= 4:
            self.show_results(tab=i - 4)
        else:
            self.show_home()

    def open_editor(self, i):
        if self.busy:
            return
        if i > 0 and self.template is None:
            messagebox.showinfo(APP_TITLE, "Pilih template LJK dulu.", parent=self)
            i = 0
        if i == 3 and not Path(self.exam.scans_dir or "").is_dir():
            messagebox.showinfo(APP_TITLE, "Pilih folder LJK peserta dulu.", parent=self)
            i = 2
        self.clear_body()
        self.view = "edit"
        self.editing = (i, deepcopy(self.exam), self.template)
        step = self.steps[i]
        self.current = i
        self.heading.set(step.title)
        self.hint.set(step.hint)
        self.foot.pack(side="bottom", fill="x", before=self.body)
        step.pack(fill="both", expand=True)
        step.enter()

    def next(self):
        """The wizard's Lanjut (a double click in the template list): save the editor."""
        if self.view == "edit":
            self.save_editor()

    def save_editor(self):
        i = self.editing[0]
        step = self.steps[i]
        if not step.leave():
            return
        if i == 3:  # an explicit choice for the results already in the folder, used by the next run
            self.output_policy = step.policy.get() if step.has_results() else None
            if self.output_policy == "keep":
                self.output_policy = None
        self.exam.save(self.settings)
        self.show_home()

    def cancel_editor(self):
        _, exam, template = self.editing
        self.set_exam(exam)
        self.template = template
        self.show_home()

    def show_results(self, tab=0, process=False):
        self.clear_body()
        self.view = "results"
        self.heading.set(f"Hasil: {self.exam.name}" if self.exam.name else "Hasil pemeriksaan")
        self.back_btn.pack(side="left", padx=(0, 16), before=self.titles)
        self.tabs.pack(side="right", anchor="s")
        self.build_chips()
        self.chips.pack(fill="x", pady=(0, 10))
        self.show_tab(tab)
        if process:
            self.after_idle(self.steps[4].start)

    def show_tab(self, i):
        if self.busy:
            return
        if i == 1 and not self.compute_results():
            messagebox.showinfo(APP_TITLE, "Belum ada hasil. Klik 'Proses LJK'.", parent=self)
            return
        for step in self.steps[4:]:
            step.pack_forget()
        self.tab = i
        self.current = 4 + i
        for j, b in enumerate(self.tab_btns):
            b.configure(style="Accent.TButton" if j == i else "TButton")
        self.hint.set(self.steps[4 + i].hint)
        self.steps[4 + i].pack(fill="both", expand=True)
        self.steps[4 + i].enter()

    def build_chips(self):
        for w in self.chips.winfo_children():
            w.destroy()
        for i, (title, status, value, _, _) in enumerate(self.cards()):
            mark = "✓" if status == "ok" else "!"
            value = value if len(value) <= 28 else "..." + value[-25:]
            b = ttk.Button(self.chips, text=f"{mark} {EDITORS[i]}: {value}", style="Small.TButton",
                           command=lambda i=i: self.open_editor(i))  # fmt: skip
            b.pack(side="left", padx=(0, 6))

    # the four settings
    def cards(self):
        """(title, status, value, detail, actions) per setting; status ok / warn / todo."""
        e, t = self.exam, self.template
        cards = []
        if t:
            cards.append(("Template LJK", "ok", t.name, t.summary(), [("Ganti...", lambda: self.open_editor(0), False)]))
        else:
            cards.append(("Template LJK", "todo", "Belum dipilih",
                          "Template = peta posisi bulatan di LJK. Buat sekali per desain LJK, lalu pakai terus.",
                          [("Pilih template...", lambda: self.open_editor(0), True)]))  # fmt: skip

        keys_btn = [("Isi kunci..." if t else "Ubah...", lambda: self.open_editor(1), False)]
        if not t:
            cards.append(("Kunci jawaban", "todo", "Belum diisi", "Pilih template dulu.", keys_btn))
        else:
            total = sum(len(q) for q in t.sections.values())
            codes = ujian.active_codes(e)
            filled = {c: sum(len(k) for p, k in (ujian.keys_for(e, c) or {}).items() if p in t.sections) for c in codes}
            scoring = f"Benar {e.correct:g}, salah {e.incorrect:g}, kosong {e.unmarked:g}"
            scoring += ", nilai 0-100" if e.scale_100 else ""
            scoring += f". Nilai batas lulus {e.kkm:g}." if e.kkm else "."
            if not any(filled.values()):
                cards.append(("Kunci jawaban", "todo", f"0 dari {total} soal",
                              "Ketik kunci, atau buka file .kunci yang pernah disimpan.", keys_btn))  # fmt: skip
            else:
                status = "ok" if all(n >= total for n in filled.values()) else "warn"
                if e.code_column:
                    value = f"{len(codes)} kode naskah: {', '.join(sorted(codes, key=ujian.natural_key)[:4])}"
                    if len(codes) > 4:
                        value += ", ..."
                    scoring = f"Kode dibaca dari kolom {e.code_column}. " + scoring
                else:
                    value = f"{filled[ujian.ALL_CODES]} dari {total} soal"
                if any(ujian.in_order_for(e, c) for c in codes):
                    scoring += " Ada bagian yang harus diisi berurutan."
                cards.append(("Kunci jawaban", status, value, scoring, [("Ubah...", lambda: self.open_editor(1), False)]))

        scans = Path(e.scans_dir) if e.scans_dir else None
        scan_btns = [("Scan dari scanner...", self.scan_now, True), ("Pilih folder / daftar peserta...", lambda: self.open_editor(2), False)]
        if scans and scans.is_dir():
            n = ujian.count_sheets(scan_files(scans))
            detail = f"{n} LJK di folder ini." if n else "Folder ini belum berisi LJK (JPG, PNG, PDF)."
            detail += f"\nDaftar peserta: {Path(e.students_file).name}" if e.students_file else "\nTanpa daftar peserta."
            cards.append(("LJK peserta", "ok" if n else "todo", short_path(scans), detail, scan_btns))
        else:
            cards.append(("LJK peserta", "todo", "Belum ada LJK",
                          "Scan langsung (hasilnya disimpan di folder ujian ini), atau pilih folder yang sudah "
                          "berisi scan JPG, PNG, PDF.", scan_btns))  # fmt: skip

        out = Path(e.output_dir) if e.output_dir else None
        out_btn = [("Ubah...", lambda: self.open_editor(3), False)]
        if out is None:
            where = f" di {short_path(self.default_output())}" if scans else " di sebelah folder LJK"
            cards.append(("Folder hasil", "ok", "Otomatis", f"Dibuat saat proses{where}.", out_btn))
        else:
            policy = self.results_policy()
            detail = {None: "Belum berisi hasil.",
                      "replace": "Berisi hasil ujian ini: diganti saat diproses ulang.",
                      "new": "Berisi hasil LJK lain: hasil baru disimpan di subfolder baru, yang lama tidak ditimpa.",
                      "resume": "Pemeriksaan terakhir terhenti: bisa dilanjutkan."}[policy]  # fmt: skip
            cards.append(("Folder hasil", "ok", short_path(out), detail, out_btn))
        return cards

    def default_output(self):
        scans = Path(self.exam.scans_dir)
        return scans.parent / (scans.name + "_hasil")

    def results_policy(self):
        """What the next run does with the results already in the output folder:
        None (none there), "replace", "new" (subfolder) or "resume"."""
        out = Path(self.exam.output_dir or "")
        if not self.exam.output_dir or not out.is_dir() or not any(ujian.current(out, "Results/Results_*.csv")):
            return None
        if self.output_policy:
            return self.output_policy
        scans = Path(self.exam.scans_dir or "")
        if not scans.is_dir() or not results_match_scans(out, scans):
            return "new"
        done = len(ujian.done_sheets(out))
        if 0 < done < ujian.count_sheets(scan_files(scans)) and not self.scans_archived:
            return "resume"
        return "replace"

    def refresh_home(self):
        for w in self.home.winfo_children():
            w.destroy()
        grid = ttk.Frame(self.home)
        grid.pack(fill="x")
        cards = self.cards()
        self.card_widgets = []
        for i, (title, status, value, detail, actions) in enumerate(cards):
            c = Card(grid, title, status, value, detail, actions)
            c.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 12, 0))
            grid.columnconfigure(i, weight=1, uniform="cards")
            self.card_widgets.append(c)
        grid.rowconfigure(0, minsize=220)

        panel = tk.Frame(self.home, bg=theme.SURFACE, highlightthickness=1, highlightbackground=theme.BORDER)
        panel.pack(fill="x", pady=(16, 0))
        texts = tk.Frame(panel, bg=theme.SURFACE)
        texts.pack(side="left", fill="x", expand=True, padx=20, pady=18)
        ready, message, detail = self.readiness(cards)
        self.ready_text = tk.Label(texts, text=message, bg=theme.SURFACE, fg=theme.FG, font="SunValleySubtitleFont", anchor="w")
        self.ready_text.pack(fill="x")
        tk.Label(texts, text=detail, bg=theme.SURFACE, fg=theme.MUTED, anchor="w", justify="left").pack(fill="x", pady=(2, 0))
        self.sensitivity = wz.sensitivity_slider(texts, self, bg=theme.SURFACE, tip_below=True)
        self.sensitivity.pack(fill="x", pady=(8, 0))
        self.process_btn = ttk.Button(panel, text="▶  Proses LJK", command=self.process, style="Accent.TButton",
                                      state="normal" if ready else "disabled")  # fmt: skip
        self.process_btn.pack(side="right", padx=20, ipady=6)
        out = Path(self.exam.output_dir) if self.exam.output_dir else None
        has_results = bool(self.template and out and out.is_dir() and ujian.current(out, "Results/Results_*.csv"))
        self.last_btn = ttk.Button(panel, text="Lihat hasil terakhir", command=self.show_last,
                                   state="normal" if has_results else "disabled")  # fmt: skip
        self.last_btn.pack(side="right", ipady=6)

        if self.exam.exported_file and not self.export_pending():
            tk.Label(self.home, text=f"✓ Rekap terakhir sudah diekspor: {Path(self.exam.exported_file).name}",
                     fg=theme.DONE, bg=theme.BG).pack(anchor="w", pady=(12, 0))  # fmt: skip
        elif self.export_pending():
            tk.Label(self.home, text="Hasil terakhir belum diekspor: buka 'Lihat hasil terakhir' lalu ekspor.",
                     fg=theme.WARN, bg=theme.BG).pack(anchor="w", pady=(12, 0))  # fmt: skip

    def readiness(self, cards):
        statuses = [c[1] for c in cards]
        if statuses[0] != "ok" or statuses[2] != "ok":
            missing = [EDITORS[i] for i in (0, 2) if statuses[i] != "ok"]
            return False, f"Lengkapi {' dan '.join(missing)} dulu.", "Tombol Proses aktif setelah template dipilih dan ada LJK peserta."
        n = ujian.count_sheets(scan_files(self.exam.scans_dir))
        detail = {None: "", "replace": "Hasil lama ujian ini akan diganti.",
                  "new": "Folder hasil berisi LJK lain: hasil disimpan di subfolder baru.",
                  "resume": "Pemeriksaan terakhir terhenti: kamu bisa melanjutkan sisanya."}[self.results_policy()]  # fmt: skip
        if statuses[1] == "todo":
            detail = ("Belum ada kunci jawaban: LJK hanya dibaca, tidak dinilai. " + detail).strip()
        elif statuses[1] == "warn":
            detail = ("Kunci jawaban belum lengkap. " + detail).strip()
        return True, f"Siap memeriksa {n} LJK.", detail

    # actions
    def prepare(self):
        """Apply settings 1-4 the way the wizard's Lanjut does, without showing
        them. On a problem (its message already said why) that editor opens."""
        policy = None
        for i in range(4):
            step = self.steps[i]
            step.enter()
            if i == 3:
                policy = self.results_policy()
                if step.has_results():
                    step.policy.set("replace" if policy in ("replace", "resume") else "new")
            if not step.leave():
                self.open_editor(i)
                return False
            if i == 3 and policy == "resume":
                self.clear_old = False  # ProcessStep.start offers to finish the stopped run
        self.output_policy = None
        self.exam.save(self.settings)
        return True

    def process(self):
        if self.busy or not self.prepare():
            return
        self.show_results(tab=0, process=True)

    def show_last(self):
        self.reprocess = self.clear_old = False
        self.show_results(tab=0)

    def scan_now(self):
        """Scan into the LJK folder (a new one under Documents when none was chosen)."""
        step = self.steps[2]
        step.enter()
        if not self.exam.scans_dir:
            step.folder.set(str(default_scans_dir(self.exam_name.get())))
        step.scan_paper()
        if scan_files(step.folder.get()) and step.leave():
            self.exam.save(self.settings)
        self.refresh_home()

    def new_exam(self):
        if self.busy:
            return
        if self.template is None:
            self.show_home()
            return
        if not self.ask_export_before_close("memulai ujian baru", "Lanjut tanpa ekspor"):
            return
        self.steps[5].new_exam()

    def set_busy(self, busy):
        self.busy = busy
        state = "disabled" if busy else "normal"
        for b in (self.back_btn, self.new_btn, self.open_btn, *self.tab_btns, *self.chips.winfo_children()):
            b.configure(state=state)

    def show_help_menu(self):
        menu = tk.Menu(self, tearoff=False)
        menu.add_command(label="Panduan (PDF)", command=self.open_guide)
        menu.add_command(label="Buka folder data & log", command=lambda: wz.open_file(ujian.app_data_dir(), self))
        menu.add_command(label="Cek versi terbaru (halaman unduhan)", command=self.open_releases)
        menu.add_command(label="Kembali ke tampilan lama (langkah 1-6)", command=self.switch_look)
        menu.add_separator()
        menu.add_command(label="Tentang Pemindai LJK", command=self.about)
        b = self.help_btn
        menu.tk_popup(b.winfo_rootx(), b.winfo_rooty() + b.winfo_height())



def short_path(path, parts=2):
    p = Path(path)
    return str(Path(*p.parts[-parts:])) if len(p.parts) > parts else str(p)
