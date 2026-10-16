"""The wizard end to end on a synthetic LJK (no private sample sheets needed):
step 5 must wait for the "Proses LJK" click, then read every sheet; an empty
page is flagged without stopping the batch.

Needs Tk and a display (skipped otherwise); headless Linux: xvfb-run.
"""

import sys
import time
from pathlib import Path

import cv2
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(Path(__file__).parent)]

tk = pytest.importorskip("tkinter", exc_type=ImportError)

import synth_ljk as synth  # noqa: E402
import template_builder as tb  # noqa: E402
import ujian  # noqa: E402
from test_template_builder import label_like_user  # noqa: E402


def pump(w, n=10):
    for _ in range(n):
        w.update()


@pytest.fixture
def setup(tmp_path, monkeypatch):
    try:
        tk.Tk().destroy()
    except tk.TclError as e:
        pytest.skip(f"no display: {e}")
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    img, layout = synth.make_blank()
    sheet = tb.prepare_sheet(img)
    _, blocks = tb.detect_blocks(sheet.page)
    blocks = label_like_user([*blocks], layout)
    template, _ = tb.build_template(blocks, sheet)
    lib = tmp_path / "lib"
    ujian.save_to_library("LJK Sintetis", sheet, template, blocks, lib)
    scans = tmp_path / "scan"
    scans.mkdir()
    for k in range(2):
        filled = synth.fill(img, layout, synth.random_responses(layout, seed=k), seed=k)
        cv2.imencode(".jpg", filled)[1].tofile(str(scans / f"siswa_{k + 1}.jpg"))
    # an empty page (e.g. the back of a duplex scan) must not stop the batch
    cv2.imencode(".jpg", np.full((3508, 2480, 3), 235, np.uint8))[1].tofile(str(scans / "kosong.jpg"))
    return lib, scans, tmp_path


def test_process_step_waits_for_click(setup, monkeypatch):
    import wizard as wz

    lib, scans, tmp = setup
    errors = []
    monkeypatch.setattr(wz.messagebox, "showerror", lambda *a, **k: errors.append(a))
    monkeypatch.setattr(wz.messagebox, "askyesno", lambda *a, **k: False)
    w = wz.run_wizard(mainloop=False, library=lib, settings=tmp / "sesi.json")
    try:
        pump(w)
        assert w.stepper.current == 0
        w.next()
        step = w.steps[1]
        for part, text in step.texts.items():
            count = len(w.template.sections[part])
            text.insert("1.0", "A" * count)
            step.on_key_edit(part)
        w.next()
        w.steps[2].folder.set(str(scans))
        w.next()
        w.steps[3].name.set("Uji")
        w.next()
        assert w.current == 4, errors
        assert w.stepper.current == 4 and w.stepper.reached == 4

        step = w.steps[4]
        pump(w, 30)
        time.sleep(0.5)
        pump(w, 10)
        assert step.proc is None and not step.results, "processing must not start by itself"
        assert "Klik" in step.summary.get() and "3 LJK" in step.summary.get()

        step.run_btn.invoke()
        assert step.proc is not None
        deadline = time.time() + 300
        while step.proc is not None:
            w.update()
            time.sleep(0.05)
            assert time.time() < deadline, "processing did not finish"
        pump(w, 20)
        assert not errors, errors
        assert len(step.results) == 3
        bad = [r for r in step.results if r.flags]
        assert [r.file_id for r in bad] == ["kosong.jpg"]
        assert "tidak terbaca" in bad[0].flags[0]
    finally:
        try:
            w.destroy()
        except tk.TclError:
            pass


def alive(w):
    try:
        return bool(w.winfo_exists())
    except tk.TclError:  # the root window itself was destroyed
        return False


def run_to_results(w):
    """Steps 1-5 with all-A keys; returns once step 5 has read every sheet."""
    pump(w)
    w.next()
    step = w.steps[1]
    for part, text in step.texts.items():
        text.insert("1.0", "A" * len(w.template.sections[part]))
        step.on_key_edit(part)
    w.next()
    w.next()
    w.next()
    step = w.steps[4]
    step.run_btn.invoke()
    deadline = time.time() + 300
    while step.proc is not None:
        w.update()
        time.sleep(0.05)
        assert time.time() < deadline
    pump(w, 20)
    return step


def test_close_offers_export_until_rekap_is_current(setup, monkeypatch):
    import wizard as wz

    lib, scans, tmp = setup
    monkeypatch.setattr(wz.messagebox, "showerror", lambda *a, **k: pytest.fail(f"error: {a}"))
    monkeypatch.setattr(wz.messagebox, "askyesno", lambda *a, **k: True)  # confirm "Ujian baru"
    asked = []
    answers = []

    def ask(master, heading, text, buttons, detail=""):
        asked.append((heading, [k for k, *_ in buttons]))
        return answers.pop(0)

    monkeypatch.setattr(wz.ChoiceDialog, "ask", staticmethod(ask))
    out = tmp / "rekap.xlsx"
    monkeypatch.setattr(wz.filedialog, "asksaveasfilename", lambda **k: str(out))
    exam = ujian.Exam(scans_dir=str(scans), output_dir=str(tmp / "hasil"))
    exam.save(tmp / "sesi.json")
    w = wz.run_wizard(mainloop=False, library=lib, settings=tmp / "sesi.json")
    try:
        run_to_results(w)
        assert w.export_pending()

        # X button: nothing exported yet -> asked; "Batal" keeps the window
        answers.append("batal")
        w.on_close()
        assert asked[-1] == ("Rekap nilai belum diekspor", ["batal", "tutup", "ekspor"])
        assert alive(w)

        # step 6, "Selesai": export from the prompt, then the app closes
        w.next()
        assert w.current == 5
        assert w.steps[5].export_info.get() == "Belum diekspor"
        answers.append("ekspor")
        w.next()  # Selesai
        assert out.exists()
        assert not alive(w)
        saved = ujian.Exam.load(tmp / "sesi.json")
        assert saved.exported_file == str(out) and saved.exported_state == ujian.rekap_state(saved)
    finally:
        try:
            w.destroy()
        except tk.TclError:
            pass

    # reopen: rekap is current -> "Selesai" shows the closing screen, no export prompt
    w = wz.run_wizard(mainloop=False, library=lib, settings=tmp / "sesi.json")
    try:
        pump(w)
        for _ in range(5):
            w.next()
        assert w.current == 5 and not w.export_pending()
        assert w.steps[5].export_info.get() == "✓ Sudah diekspor: rekap.xlsx"
        answers.append("folder")
        opened = []
        monkeypatch.setattr(wz, "open_path", opened.append)
        w.next()
        assert asked[-1] == ("Pemeriksaan selesai", ["buka", "folder", "baru", "tutup"])
        assert opened == [w.exam.output_dir] and alive(w)

        # a correction after the export makes the rekap out of date again
        w.exam.corrections = {"siswa_1.jpg": {"q1": "B"}}
        assert w.export_pending()
        answers.append("tutup")
        w.on_close()
        assert asked[-1][0] == "Rekap belum diperbarui"
        assert not alive(w)
    finally:
        try:
            w.destroy()
        except tk.TclError:
            pass


def test_choice_dialog_returns_clicked_key(setup):
    import wizard as wz

    lib, _, tmp = setup
    w = wz.run_wizard(mainloop=False, library=lib, settings=tmp / "sesi.json")
    try:
        pump(w)
        d = wz.ChoiceDialog(w, "Judul", "Teks", [("a", "Satu", False), ("b", "Dua", True)], detail="rincian")
        pump(w)
        assert str(d.buttons["b"]["style"]) == "Accent.TButton"
        d.buttons["b"].invoke()
        assert d.choice == "b" and not d.winfo_exists()
        d = wz.ChoiceDialog(w, "Judul", "Teks", [("a", "Satu", False)])
        d.event_generate("<Escape>")
        pump(w)
        assert d.choice is None
    finally:
        w.destroy()
