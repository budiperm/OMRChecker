"""

 Look of the Tk windows: the Sun Valley ttk theme (Windows 11 style, sv-ttk),
 refined Fluent/editorial colour tokens, Segoe UI / Inter fonts, reusable
 card/badge/KPI helpers, and matching colours for classic Tk widgets
 (Listbox, Text, Canvas) that ttk themes do not reach.

 apply(root) once per Tk root; widgets then use the style names below.

"""

import sys
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont
from tkinter import ttk

BG = "#f4f6fa"  # window canvas
SURFACE = "#ffffff"  # cards, lists, text boxes, headers
SURFACE_ALT = "#f8fafc"  # secondary subtle surface (table headers, stat tiles)
SIDEBAR = "#ffffff"  # wizard sidebar
BORDER = "#e2e8f0"  # hairline border
BORDER_STRONG = "#cbd5e1"  # hover / active border
FG = "#0f172a"  # primary ink (slate-900)
MUTED = "#64748b"  # secondary ink (slate-500)
ACCENT = "#1d6ce0"  # primary cobalt blue (matches app icon)
ACCENT_HOVER = "#1557bc"
ACCENT_SOFT = "#eaf2fe"  # soft blue tint
WARN = "#b45309"  # amber text
WARN_SOFT = "#fef3c7"  # amber badge fill
DONE = "#15803d"  # emerald text
DONE_SOFT = "#dcfce7"  # emerald badge fill
DANGER = "#b91c1c"  # rose text
DANGER_SOFT = "#fee2e2"  # flagged row fill
INFO_SOFT = "#e0f2fe"  # corrected row fill
CANVAS_BG = "#eef2f6"  # image preview canvas
STRIPE_BG = "#f8fafc"  # alternating treeview row

# family preference: Windows 11, Windows 10, then what Linux test boxes have
TEXT_FAMILIES = ["Segoe UI Variable Text", "Segoe UI", "Inter", "Noto Sans", "DejaVu Sans"]
DISPLAY_FAMILIES = ["Segoe UI Variable Display", "Segoe UI Semibold", "Segoe UI", "Inter", "Noto Sans"]
MONO_FAMILIES = ["Cascadia Mono", "Consolas", "DejaVu Sans Mono"]


def asset(name):
    """Path of a file in assets/, also inside the PyInstaller bundle."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / "assets" / name


def set_icon(root):
    """App icon for the title bar, taskbar and Alt+Tab (all windows of root)."""
    if sys.platform == "win32":
        try:
            import ctypes

            # own taskbar group and icon instead of python.exe's
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("OMRChecker.PemindaiLJK")
        except Exception:
            pass
        try:
            root.iconbitmap(default=str(asset("icon.ico")))
        except tk.TclError:
            pass
    try:
        root._omr_icon = tk.PhotoImage(master=root, file=str(asset("icon.png")))
        root.iconphoto(True, root._omr_icon)
    except tk.TclError:
        pass


def logo(root):
    """40 px logo for the sidebar/header, or None."""
    try:
        return tk.PhotoImage(master=root, file=str(asset("logo.png")))
    except tk.TclError:
        return None


def _family(root, choices):
    available = set(tkfont.families(root))
    return next((f for f in choices if f in available), None)


def fonts(root):
    """Family names actually used: (text, display, mono)."""
    if not hasattr(root, "_omr_fonts"):
        text = _family(root, TEXT_FAMILIES) or tkfont.nametofont("TkDefaultFont", root).actual("family")
        root._omr_fonts = (text, _family(root, DISPLAY_FAMILIES) or text, _family(root, MONO_FAMILIES) or "TkFixedFont")
    return root._omr_fonts


def mono(root, size=11):
    return (fonts(root)[2], size)


def apply(root):
    """Theme a Tk root. Safe to call twice; falls back to the plain theme
    when sv-ttk is missing."""
    if getattr(root, "_omr_themed", False):
        return
    root._omr_themed = True
    set_icon(root)
    text, display, mono_family = fonts(root)
    try:
        import sv_ttk

        sv_ttk.set_theme("light", root)
    except Exception:  # sv-ttk missing: keep the platform theme, still restyle below
        pass

    # Sun Valley names Segoe UI Variable, which Windows 10 lacks: point its fonts at what exists
    for name, family, size, weight in (("SunValleyCaptionFont", text, 9, "normal"),
                                       ("SunValleyCaptionStrongFont", text, 9, "bold"),
                                       ("SunValleyBodyFont", text, 10, "normal"),
                                       ("SunValleyBodyStrongFont", text, 10, "bold"),
                                       ("SunValleyBodyLargeFont", text, 12, "normal"),
                                       ("SunValleySubtitleFont", display, 13, "bold"),
                                       ("SunValleyTitleFont", display, 19, "bold"),
                                       ("SunValleyKpiFont", display, 15, "bold"),
                                       ("TkDefaultFont", text, 10, "normal"),
                                       ("TkTextFont", text, 10, "normal"),
                                       ("TkMenuFont", text, 10, "normal"),
                                       ("TkHeadingFont", text, 10, "bold"),
                                       ("TkCaptionFont", text, 9, "normal"),
                                       ("TkFixedFont", mono_family, 10, "normal")):  # fmt: skip
        try:
            tkfont.nametofont(name, root).configure(family=family, size=size, weight=weight)
        except tk.TclError:
            tkfont.Font(root, name=name, family=family, size=size, weight=weight)

    s = ttk.Style(root)
    s.configure(".", font="TkDefaultFont", foreground=FG)
    s.configure("TFrame", background=BG)
    s.configure("TLabel", background=BG, foreground=FG)
    s.configure("TCheckbutton", background=BG, foreground=FG)
    s.configure("TRadiobutton", background=BG, foreground=FG)
    s.configure("TScale", background=BG)

    # surface-matched ttk styles for widgets placed inside white cards
    s.configure("Surface.TFrame", background=SURFACE)
    s.configure("Surface.TLabel", background=SURFACE, foreground=FG)
    s.configure("SurfaceMuted.TLabel", background=SURFACE, foreground=MUTED)
    s.configure("SurfaceStrong.TLabel", background=SURFACE, foreground=FG, font="SunValleyBodyStrongFont")
    s.configure("SurfaceSubtitle.TLabel", background=SURFACE, foreground=FG, font="SunValleySubtitleFont")
    s.configure("Surface.TCheckbutton", background=SURFACE, foreground=FG)
    s.configure("Surface.TRadiobutton", background=SURFACE, foreground=FG)
    s.configure("Soft.TFrame", background=SURFACE_ALT)
    s.configure("Soft.TLabel", background=SURFACE_ALT, foreground=FG)
    for style_name, bg_color in (("Horizontal.Surface.TScale", SURFACE), ("Horizontal.Soft.TScale", SURFACE_ALT)):
        try:
            s.layout(style_name, s.layout("Horizontal.TScale"))
        except tk.TclError:
            pass
        s.configure(style_name, background=bg_color)

    # label colours (MUTED, WARN, ...) go on the widget itself (foreground=...):
    # sv-ttk can drop foreground set on derived label styles
    s.configure("Strong.TLabel", font="SunValleyBodyStrongFont", background=BG)
    s.configure("Title.TLabel", font="SunValleyTitleFont", foreground=FG, background=BG)
    s.configure("Subtitle.TLabel", font="SunValleySubtitleFont", foreground=FG, background=BG)
    s.configure("Eyebrow.TLabel", font="SunValleyCaptionStrongFont", background=BG)
    s.configure("Big.TLabel", font="SunValleyBodyLargeFont", background=BG)
    s.configure("TButton", padding=(14, 6))
    s.configure("Accent.TButton", padding=(18, 6))
    s.configure("Small.TButton", padding=(10, 3))
    s.configure("Chip.TButton", padding=(10, 4))
    s.configure("TLabelframe.Label", font="SunValleyBodyStrongFont", foreground=FG, background=BG)
    s.configure("TLabelframe", background=BG, padding=(12, 8, 12, 10))
    s.configure("Treeview", rowheight=34, background=SURFACE, fieldbackground=SURFACE, foreground=FG)
    s.configure("Treeview.Heading", font="SunValleyCaptionStrongFont", foreground=MUTED)
    s.configure("Heading", font="SunValleyCaptionStrongFont")
    s.configure("TPanedwindow", background=BG)

    # sidebar stepper & footer
    s.configure("Side.TFrame", background=SIDEBAR)
    s.configure("Footer.TFrame", background=SURFACE)

    root.configure(background=BG)
    # classic Tk widgets: flat, same fonts and selection colour as ttk
    for pattern, value in (("*Listbox.font", "TkDefaultFont"), ("*Listbox.background", SURFACE),
                           ("*Listbox.foreground", FG), ("*Listbox.relief", "flat"),
                           ("*Listbox.borderWidth", 0), ("*Listbox.highlightThickness", 1),
                           ("*Listbox.highlightColor", ACCENT), ("*Listbox.highlightBackground", BORDER),
                           ("*Listbox.selectBackground", ACCENT), ("*Listbox.selectForeground", "#ffffff"),
                           ("*Listbox.activeStyle", "none"),
                           ("*Text.background", SURFACE), ("*Text.foreground", FG), ("*Text.relief", "flat"),
                           ("*Text.borderWidth", 0), ("*Text.highlightThickness", 1),
                           ("*Text.highlightColor", ACCENT), ("*Text.highlightBackground", BORDER),
                           ("*Text.selectBackground", ACCENT_SOFT), ("*Text.insertBackground", FG),
                           ("*Text.padX", 10), ("*Text.padY", 8),
                           ("*Canvas.background", BG), ("*Toplevel.background", BG)):  # fmt: skip
        root.option_add(pattern, value)


def round_rect(canvas, x1, y1, x2, y2, r=10, **kw):
    """Draw a smooth rounded rectangle on a Tk Canvas."""
    r = max(0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    pts = [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]
    return canvas.create_polygon(pts, smooth=True, splinesteps=24, **kw)


def card(master, title=None, subtitle=None, pad=(18, 14), bg=SURFACE):
    """Create a crisp bordered white card; returns (outer_frame, inner_frame)."""
    outer = tk.Frame(master, bg=bg, highlightthickness=1, highlightbackground=BORDER)
    inner = ttk.Frame(outer, style="Surface.TFrame" if bg == SURFACE else "Soft.TFrame")
    inner.pack(fill="both", expand=True, padx=pad[0], pady=pad[1])
    if title:
        head = ttk.Frame(inner, style="Surface.TFrame" if bg == SURFACE else "Soft.TFrame")
        head.pack(fill="x", pady=(0, 8))
        tk.Label(head, text=title, bg=bg, fg=FG, font="SunValleyBodyStrongFont", anchor="w").pack(side="left")
        if subtitle:
            tk.Label(head, text=subtitle, bg=bg, fg=MUTED, font="SunValleyCaptionFont", anchor="w").pack(
                side="left", padx=(8, 0)
            )
    return outer, inner


def badge(master, text, fg=ACCENT, bg=ACCENT_SOFT):
    """Compact pill-style status label."""
    return tk.Label(master, text=text, fg=fg, bg=bg, font="SunValleyCaptionStrongFont", padx=9, pady=2)


class StatStrip(tk.Frame):
    """Horizontal row of clean KPI stat tiles (Peserta, Rata-rata, etc.)."""

    def __init__(self, master, bg=BG):
        super().__init__(master, bg=bg)
        self._bg = bg

    def update_stats(self, items):
        """items: list of (label, value, accent_fg_or_None)."""
        for w in self.winfo_children():
            w.destroy()
        for i, item in enumerate(items):
            label, value = item[0], item[1]
            fg = item[2] if len(item) > 2 and item[2] else FG
            tile = tk.Frame(self, bg=SURFACE, highlightthickness=1, highlightbackground=BORDER)
            tile.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 10, 0))
            self.columnconfigure(i, weight=1, uniform="kpi")
            tk.Label(tile, text=label.upper(), bg=SURFACE, fg=MUTED, font="SunValleyCaptionFont", anchor="w").pack(
                fill="x", padx=14, pady=(9, 1)
            )
            tk.Label(tile, text=str(value), bg=SURFACE, fg=fg, font="SunValleyKpiFont", anchor="w").pack(
                fill="x", padx=14, pady=(0, 9)
            )


class Stepper(tk.Canvas):
    """Vertical list of wizard steps: number badge (or check), title,
    hover state, and active pill highlight. on_click(i) when clicked."""

    ROW = 54

    def __init__(self, master, steps, on_click, width=252):
        super().__init__(master, width=width, height=self.ROW * len(steps) + 12, background=SIDEBAR,
                         highlightthickness=0, borderwidth=0, cursor="hand2")  # fmt: skip
        self.steps, self.on_click = steps, on_click
        self.current, self.reached = 0, 0
        self.hovered = None
        root = self.winfo_toplevel()
        text = fonts(root)[0]
        self.font = tkfont.Font(root, family=text, size=10)
        self.font_bold = tkfont.Font(root, family=text, size=10, weight="bold")
        self.font_badge = tkfont.Font(root, family=text, size=9, weight="bold")
        self.bind("<Button-1>", lambda e: self.click(e.y))
        self.bind("<Motion>", self._on_motion)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Configure>", lambda e: self.draw())

    def _index_at(self, y):
        i = int((y - 6) // self.ROW)
        return i if 0 <= i < len(self.steps) else None

    def _on_motion(self, e):
        idx = self._index_at(e.y)
        if idx != self.hovered:
            self.hovered = idx
            self.draw()

    def _on_leave(self, _e):
        if self.hovered is not None:
            self.hovered = None
            self.draw()

    def click(self, y):
        i = self._index_at(y)
        if i is not None:
            self.on_click(i)

    def set(self, current, reached):
        self.current, self.reached = current, reached
        self.draw()

    def draw(self):
        self.delete("all")
        w = max(self.winfo_width(), int(self["width"]))
        for i, name in enumerate(self.steps):
            y = 6 + i * self.ROW
            cy = y + self.ROW // 2
            current = i == self.current
            done = i < self.reached and not current
            hovered = i == self.hovered and not current
            if current:
                round_rect(self, 12, y + 4, w - 12, y + self.ROW - 4, r=10, fill=ACCENT_SOFT, outline="")
                round_rect(self, 12, y + 14, 16, y + self.ROW - 14, r=2, fill=ACCENT, outline="")
            elif hovered:
                round_rect(self, 12, y + 4, w - 12, y + self.ROW - 4, r=10, fill=SURFACE_ALT, outline="")
            if i < len(self.steps) - 1:  # connector to the next badge
                conn = "#86efac" if i < self.reached else BORDER
                self.create_line(38, cy + 14, 38, cy + self.ROW - 14, fill=conn, width=2)
            if current:
                self.create_oval(25, cy - 13, 51, cy + 13, fill=ACCENT, outline="")
                self.create_text(38, cy, text=str(i + 1), fill="#ffffff", font=self.font_badge)
            elif done:
                self.create_oval(25, cy - 13, 51, cy + 13, fill=DONE_SOFT, outline=DONE, width=1.5)
                self.create_text(38, cy, text="✓", fill=DONE, font=self.font_badge)
            elif i <= self.reached:
                self.create_oval(25, cy - 13, 51, cy + 13, fill=SURFACE, outline=ACCENT, width=1.5)
                self.create_text(38, cy, text=str(i + 1), fill=ACCENT, font=self.font_badge)
            else:
                self.create_oval(25, cy - 13, 51, cy + 13, fill=SURFACE_ALT, outline=BORDER_STRONG, width=1.5)
                self.create_text(38, cy, text=str(i + 1), fill=MUTED, font=self.font_badge)
            fg = ACCENT if current else (FG if i <= self.reached else MUTED)
            self.create_text(64, cy, text=name, anchor="w", fill=fg,
                             font=self.font_bold if current else self.font)  # fmt: skip
