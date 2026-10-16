"""

 Look of the Tk windows: the Sun Valley ttk theme (Windows 11 style, sv-ttk),
 Segoe UI fonts, and matching colours for the few classic Tk widgets
 (Listbox, Text, Canvas) that ttk themes do not reach.

 apply(root) once per Tk root; widgets then use the style names below.

"""

import sys
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont
from tkinter import ttk

BG = "#fafafa"  # window
SURFACE = "#ffffff"  # cards, lists, text boxes
SIDEBAR = "#f0f3f9"
BORDER = "#e1e4ea"
FG = "#1c1c1c"
MUTED = "#5f6b7a"
ACCENT = "#005fb8"
ACCENT_SOFT = "#dbe9fb"
WARN = "#9a6700"
DONE = "#1a7f37"

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
    """40 px logo for the sidebar, or None."""
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
                                       ("SunValleyBodyFont", text, 10, "normal"),
                                       ("SunValleyBodyStrongFont", text, 10, "bold"),
                                       ("SunValleyBodyLargeFont", text, 13, "normal"),
                                       ("SunValleySubtitleFont", display, 15, "bold"),
                                       ("SunValleyTitleFont", display, 20, "bold"),
                                       ("TkDefaultFont", text, 10, "normal"),
                                       ("TkTextFont", text, 10, "normal"),
                                       ("TkMenuFont", text, 10, "normal"),
                                       ("TkHeadingFont", text, 10, "bold"),
                                       ("TkCaptionFont", text, 10, "normal"),
                                       ("TkFixedFont", mono_family, 10, "normal")):  # fmt: skip
        try:
            tkfont.nametofont(name, root).configure(family=family, size=size, weight=weight)
        except tk.TclError:
            tkfont.Font(root, name=name, family=family, size=size, weight=weight)

    s = ttk.Style(root)
    s.configure(".", font="TkDefaultFont")
    s.configure("TFrame", background=BG)
    s.configure("TLabel", background=BG)
    s.configure("Muted.TLabel", foreground=MUTED)
    s.configure("Warn.TLabel", foreground=WARN)
    s.configure("Strong.TLabel", font="SunValleyBodyStrongFont")
    s.configure("Title.TLabel", font="SunValleyTitleFont", foreground=FG)
    s.configure("Subtitle.TLabel", font="SunValleySubtitleFont", foreground=FG)
    s.configure("Eyebrow.TLabel", font="SunValleyCaptionFont", foreground=ACCENT)
    s.configure("Big.TLabel", font="SunValleyBodyLargeFont")
    s.configure("TButton", padding=(14, 5))
    s.configure("Accent.TButton", padding=(18, 5))
    s.configure("Small.TButton", padding=(8, 2))
    s.configure("TLabelframe.Label", font="SunValleyBodyStrongFont", foreground=FG)
    s.configure("TLabelframe", padding=(8, 4, 8, 8))
    s.configure("Treeview", rowheight=30)
    s.configure("Heading", font="SunValleyCaptionFont")

    # sidebar stepper
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
                           ("*Text.padX", 8), ("*Text.padY", 6),
                           ("*Canvas.background", BG), ("*Toplevel.background", BG)):  # fmt: skip
        root.option_add(pattern, value)


class Stepper(tk.Canvas):
    """Vertical list of wizard steps: number badge (or check), title,
    current one highlighted. on_click(i) when a step is clicked."""

    ROW = 52

    def __init__(self, master, steps, on_click, width=232):
        super().__init__(master, width=width, height=self.ROW * len(steps) + 8, background=SIDEBAR,
                         highlightthickness=0, borderwidth=0, cursor="hand2")  # fmt: skip
        self.steps, self.on_click = steps, on_click
        self.current, self.reached = 0, 0
        root = self.winfo_toplevel()
        text = fonts(root)[0]
        self.font = tkfont.Font(root, family=text, size=10)
        self.font_bold = tkfont.Font(root, family=text, size=10, weight="bold")
        self.font_badge = tkfont.Font(root, family=text, size=9, weight="bold")
        self.bind("<Button-1>", lambda e: self.click(e.y))
        self.bind("<Configure>", lambda e: self.draw())

    def click(self, y):
        i = int((y - 4) // self.ROW)
        if 0 <= i < len(self.steps):
            self.on_click(i)

    def set(self, current, reached):
        self.current, self.reached = current, reached
        self.draw()

    def draw(self):
        self.delete("all")
        w = max(self.winfo_width(), int(self["width"]))
        for i, name in enumerate(self.steps):
            y = 4 + i * self.ROW
            cy = y + self.ROW // 2
            current, done = i == self.current, i < self.reached and i != self.current
            if current:
                self.create_rectangle(10, y + 4, w - 10, y + self.ROW - 4, fill=ACCENT_SOFT, outline="")
                self.create_rectangle(10, y + 14, 13, y + self.ROW - 14, fill=ACCENT, outline="")
            if i < len(self.steps) - 1:  # connector to the next badge
                self.create_line(36, cy + 13, 36, cy + self.ROW - 13, fill=BORDER, width=2)
            if current:
                self.create_oval(23, cy - 13, 49, cy + 13, fill=ACCENT, outline="")
                self.create_text(36, cy, text=str(i + 1), fill="#ffffff", font=self.font_badge)
            elif done or i <= self.reached:
                self.create_oval(23, cy - 13, 49, cy + 13, fill=SURFACE, outline=DONE if done else ACCENT, width=2)
                self.create_text(36, cy, text="✓" if done else str(i + 1), fill=DONE if done else ACCENT,
                                 font=self.font_badge)  # fmt: skip
            else:
                self.create_oval(23, cy - 13, 49, cy + 13, fill=SIDEBAR, outline="#c3c9d4", width=2)
                self.create_text(36, cy, text=str(i + 1), fill=MUTED, font=self.font_badge)
            self.create_text(62, cy, text=name, anchor="w", fill=FG if i <= self.reached else MUTED,
                             font=self.font_bold if current else self.font)  # fmt: skip
