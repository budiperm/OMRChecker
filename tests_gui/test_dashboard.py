"""The one-screen look (dashboard.py) on a synthetic LJK: cards fill in, a
repeat exam goes straight to "Proses LJK", the output folder of another
exam is never overwritten, and the look can be switched back and forth.

Needs Tk and a display (skipped otherwise); headless Linux: xvfb-run.
OMR_SCREENSHOT_DIR=<dir> keeps a screenshot of each screen.
"""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(Path(__file__).parent)]

tk = pytest.importorskip("tkinter", exc_type=ImportError)

import ujian  # noqa: E402
from test_wizard_synth import pump, setup  # noqa: E402,F401


def shot(w, name):
    folder = os.environ.get("OMR_SCREENSHOT_DIR")
    if folder:
        w.geometry("1200x780+0+0")
        pump(w, 20)
        subprocess.run(["import", "-window", "root", str(Path(folder, f"dashboard_{name}.png"))], check=False)


def open_dashboard(lib, settings):
    import wizard as wz

    prefs = ujian.load_prefs(settings)
    prefs[ujian.PREF_DASHBOARD] = True
    ujian.save_prefs(prefs, settings)
    w = wz.run_wizard(mainloop=False, library=lib, settings=settings)
    pump(w)
    return w


def wait_done(w):
    step = w.steps[4]
    deadline = time.time() + 300
    while step.proc is None and time.time() < deadline:  # started from after_idle
        w.update()
    while step.proc is not None:
        w.update()
        time.sleep(0.05)
        assert time.time() < deadline, "processing did not finish"
    pump(w, 20)
    return step


def statuses(w):
    return [c[1] for c in w.cards()]


@pytest.fixture
def quiet(monkeypatch):
    import wizard as wz

    errors = []
    monkeypatch.setattr(wz.messagebox, "showerror", lambda *a, **k: errors.append(a))
    monkeypatch.setattr(wz.messagebox, "showinfo", lambda *a, **k: errors.append(a))
    monkeypatch.setattr(wz.messagebox, "askyesno", lambda *a, **k: False)
    monkeypatch.setattr(wz.messagebox, "showwarning", lambda *a, **k: None)
    return errors


def first_exam(w, scans):
    """Template, all-A keys and the LJK folder through the card editors."""
    w.open_editor(0)
    w.save_editor()
    w.open_editor(1)
    step = w.steps[1]
    for part, text in step.texts.items():
        text.insert("1.0", "A" * len(w.template.sections[part]))
        step.on_key_edit(part)
    w.save_editor()
    w.open_editor(2)
    w.steps[2].folder.set(str(scans))
    w.save_editor()
    assert w.view == "home"


def test_dashboard_first_and_repeat_exam(setup, quiet):
    from dashboard import Dashboard

    lib, scans, tmp = setup
    settings = tmp / "sesi.json"
    w = open_dashboard(lib, settings)
    try:
        assert isinstance(w, Dashboard)
        assert statuses(w) == ["todo", "todo", "todo", "ok"]
        assert str(w.process_btn["state"]) == "disabled"
        shot(w, "1_baru")

        first_exam(w, scans)
        assert statuses(w) == ["ok", "ok", "ok", "ok"], quiet
        assert str(w.process_btn["state"]) == "normal"
        assert w.ready_text["text"] == "Siap memeriksa 3 LJK."
        w.exam_name.set("Uji Dashboard")
        shot(w, "2_siap")

        w.process_btn.invoke()
        assert w.view == "results"
        step = wait_done(w)
        assert not quiet, quiet
        assert len(step.results) == 3
        assert Path(w.exam.output_dir) == scans.parent / "scan_hasil"
        assert w.exam.name == "Uji Dashboard"
        shot(w, "3_hasil")
        w.show_tab(1)
        assert w.current == 5
        shot(w, "4_analisis")
        w.show_home()
        w.close()

        # the next start: everything is still set, one click processes again
        w = open_dashboard(lib, settings)
        assert statuses(w) == ["ok", "ok", "ok", "ok"]
        assert w.results_policy() == "replace"
        assert str(w.last_btn["state"]) == "normal"
        shot(w, "5_ulang")
        w.process()
        step = wait_done(w)
        assert not quiet, quiet
        assert len(step.results) == 3
        assert Path(w.exam.output_dir) == scans.parent / "scan_hasil"  # replaced, not a subfolder
    finally:
        try:
            w.destroy()
        except tk.TclError:
            pass


def test_dashboard_keeps_results_of_another_exam(setup, quiet):
    lib, scans, tmp = setup
    settings = tmp / "sesi.json"
    w = open_dashboard(lib, settings)
    try:
        first_exam(w, scans)
        w.process()
        wait_done(w)
        out = Path(w.exam.output_dir)
        # another exam, other sheets, same output folder (remembered)
        other = tmp / "scan2"
        other.mkdir()
        shutil.copy(scans / "siswa_1.jpg", other / "peserta_a.jpg")
        w.show_home()
        w.exam.scans_dir = str(other)
        assert w.results_policy() == "new"
        w.refresh_home()
        assert "subfolder baru" in w.card_widgets[3].detail["text"]
        w.process()
        step = wait_done(w)
        assert not quiet, quiet
        assert Path(w.exam.output_dir).parent == out  # a new subfolder
        assert [r.file_id for r in step.results] == ["peserta_a.jpg"]
        assert len(ujian.read_results(out)[0]) >= 2  # the first exam's results are still there
    finally:
        try:
            w.destroy()
        except tk.TclError:
            pass


def test_editor_cancel_restores_exam(setup, quiet):
    lib, scans, tmp = setup
    w = open_dashboard(lib, tmp / "sesi.json")
    try:
        first_exam(w, scans)
        keys = dict(w.exam.keys)
        w.open_editor(1)
        step = w.steps[1]
        part = next(iter(step.texts))
        step.texts[part].delete("1.0", "end")
        step.on_key_edit(part)
        w.cancel_editor()
        assert w.exam.keys == keys
        assert w.view == "home" and statuses(w)[1] == "ok"
    finally:
        try:
            w.destroy()
        except tk.TclError:
            pass


def test_switch_look_is_remembered(setup, quiet):
    import wizard as wz
    from dashboard import Dashboard

    lib, _, tmp = setup
    settings = tmp / "sesi.json"
    w = open_dashboard(lib, settings)
    w.switch_look()
    assert w.switch and not ujian.load_prefs(settings)[ujian.PREF_DASHBOARD]
    w = wz.run_wizard(mainloop=False, library=lib, settings=settings)
    try:
        assert type(w) is wz.Wizard
        w.switch_look()
        assert ujian.load_prefs(settings)[ujian.PREF_DASHBOARD]
        w = wz.run_wizard(mainloop=False, library=lib, settings=settings)
        assert isinstance(w, Dashboard)
    finally:
        try:
            w.destroy()
        except tk.TclError:
            pass
