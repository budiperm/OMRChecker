"""Drives the template editor window without a person: open a blank scan,
label blocks, draw a block, enter an answer key and save.

Needs Tk and a display (skipped otherwise). Headless Linux: run under
xvfb-run. Set OMR_SCREENSHOT=<file.png> to keep a screenshot of the editor.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import cv2
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(Path(__file__).parent)]

from testdata import needs  # noqa: E402

tk = pytest.importorskip("tkinter", exc_type=ImportError)

import synth_ljk as synth  # noqa: E402
import template_builder as tb  # noqa: E402


@pytest.fixture
def root():
    try:
        r = tk.Tk()
    except tk.TclError as e:
        pytest.skip(f"no display: {e}")
    r.withdraw()
    yield r
    r.destroy()


@pytest.fixture
def blank_scan(tmp_path):
    img, layout = synth.make_blank()
    path = tmp_path / "ljk kosong.jpg"  # space in name on purpose
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 92])
    buf.tofile(str(path))
    return path, layout


def pump(widget, n=5):
    for _ in range(n):
        widget.update()


def test_editor_full_flow(root, blank_scan, tmp_path, monkeypatch):
    import template_editor as te

    path, layout = blank_scan
    saved = []
    ed = te.TemplateEditor(root, on_saved=saved.append)
    pump(ed)

    # 1. open the blank scan
    monkeypatch.setattr(te.filedialog, "askopenfilename", lambda **k: str(path))
    ed.open_scan()
    pump(ed)
    assert len(ed.blocks) == 17
    assert "480 bulatan" in ed.status_var.get()

    # 2. label number blocks through the property panel, like a user would
    scale = ed.page_dims[0] / synth.W
    names = {"NIS": "NIS", "KODE": "KodeSoal", "TGL": "TglLahir",
             "BLN": "TglLahir", "THN": "TglLahir"}  # fmt: skip
    for region, group in names.items():
        x0, y0, x1, y1 = layout.regions[region]
        block = next(b for b in ed.blocks if b.contains((x0 + x1) / 2 * scale, (y0 + y1) / 2 * scale))
        ed.select(block)
        ed.kind_var.set(te.KIND_LABELS[tb.KIND_DIGITS])
        ed.on_kind_change()
        ed.group_var.set(group)
        ed.apply_props()
        assert block.group == group and block.kind == tb.KIND_DIGITS
    pump(ed)

    # a drawn rectangle over an existing block replaces it with the same grid
    x0, y0, x1, y1 = layout.regions["NIS"]
    before = len(ed.blocks)
    ed.add_block_from_rect(x0 * scale - 5, y0 * scale - 5, x1 * scale + 5, y1 * scale + 5)
    assert len(ed.blocks) == before
    nis = ed.selected
    assert (nis.rows, nis.cols) == (10, 10)
    ed.kind_var.set(te.KIND_LABELS[tb.KIND_DIGITS])
    ed.on_kind_change()
    ed.group_var.set("NIS")
    ed.apply_props()

    # wrong option count is refused
    errors = []
    monkeypatch.setattr(te.messagebox, "showerror", lambda *a, **k: errors.append(a))
    q1 = next(b for b in ed.blocks if b.kind == tb.KIND_MCQ and b.start == 1)
    ed.select(q1)
    ed.values_var.set("A, B, C")
    ed.apply_props()
    assert errors and q1.values == list("ABCDE")
    errors.clear()

    # 3. answer key
    ed.key_text.insert("1.0", "ABCDE " * 12)
    ed.correct_var.set("2")

    # zoom and redraw paths
    ed.set_zoom(1.5)
    ed.fit_zoom()
    pump(ed)
    shot = os.environ.get("OMR_SCREENSHOT")
    if shot:
        ed.geometry("1280x820+0+0")
        ed.deiconify()
        pump(ed, 20)
        subprocess.run(["import", "-window", "root", shot], check=False)

    # 4. save
    folder = tmp_path / "Ujian IPA"
    monkeypatch.setattr(te.filedialog, "askdirectory", lambda **k: str(folder))
    monkeypatch.setattr(te.messagebox, "showinfo", lambda *a, **k: None)
    ed.save()
    assert not errors, errors
    assert saved == [folder]
    template = json.loads((folder / "template.json").read_text())
    evaluation = json.loads((folder / "evaluation.json").read_text())
    assert template["customLabels"]["NIS"] == ["NIS_1..10"]
    assert len(evaluation["options"]["answers_in_order"]) == 60
    assert evaluation["marking_schemes"]["DEFAULT"]["correct"] == "2"
    assert (folder / tb.REFERENCE_FILENAME).exists()

    # saving again asks before overwriting and keeps a backup
    monkeypatch.setattr(te.messagebox, "askyesno", lambda *a, **k: True)
    ed.save()
    assert (folder / "template.json.bak").exists()
    ed.destroy()


def test_unlabelled_digit_block_blocks_saving(root, blank_scan, monkeypatch):
    import template_editor as te

    path, _ = blank_scan
    ed = te.TemplateEditor(root)
    monkeypatch.setattr(te.filedialog, "askopenfilename", lambda **k: str(path))
    ed.open_scan()
    errors = []
    monkeypatch.setattr(te.messagebox, "showerror", lambda *a, **k: errors.append(a))
    monkeypatch.setattr(te.filedialog, "askdirectory", lambda **k: pytest.fail("must not ask"))
    ed.save()
    assert errors and "nama kolom" in errors[0][1]
    ed.destroy()


def test_main_window_has_template_button(root):
    import gui

    # run_gui builds the App class inside; check the button text is wired
    src = Path(gui.__file__).read_text(encoding="utf-8")
    assert "Buat template..." in src and "TemplateEditor(" in src


def test_try_template_on_filled_sheet(root, blank_scan, tmp_path, monkeypatch):
    """'Uji dengan LJK terisi' runs OMRChecker in a worker and shows what it read."""
    import time

    import gui
    import template_editor as te

    path, layout = blank_scan
    img, _ = synth.make_blank()
    responses = synth.random_responses(layout, seed=5)
    filled = synth.distort(synth.fill(img, layout, responses), angle=0.8, dx=20, jpeg=88)
    filled_path = tmp_path / "siswa 1.jpg"
    ok, buf = cv2.imencode(".jpg", filled)
    buf.tofile(str(filled_path))

    ed = te.TemplateEditor(root, run_worker=gui.run_worker)
    monkeypatch.setattr(te.filedialog, "askopenfilename", lambda **k: str(path))
    ed.open_scan()
    scale = ed.page_dims[0] / synth.W
    for region, group in {"NIS": "NIS", "KODE": "KodeSoal", "TGL": "TglLahir",
                          "BLN": "TglLahir", "THN": "TglLahir"}.items():  # fmt: skip
        x0, y0, x1, y1 = layout.regions[region]
        b = next(b for b in ed.blocks if b.contains((x0 + x1) / 2 * scale, (y0 + y1) / 2 * scale))
        tb.set_kind(b, tb.KIND_DIGITS)
        b.group = group

    shown = []
    monkeypatch.setattr(te, "show_text", lambda master, title, text, image=None: shown.append((title, text, image)))
    monkeypatch.setattr(te.filedialog, "askopenfilename", lambda **k: str(filled_path))
    ed.test_with_scan()
    deadline = time.time() + 300
    while not shown and time.time() < deadline:
        ed.update()
        time.sleep(0.1)
    assert shown, "test run did not finish"
    title, text, image = shown[0]
    expected = synth.expected_row(layout, responses)
    assert title == "Hasil uji template", text
    assert f"NIS : {expected['NIS']}" in text
    assert f"TglLahir : {expected['TglLahir']}" in text
    assert image is not None and Path(image).exists()
    ed.destroy()


@needs("ljk_kosong_smpn3.pdf")
def test_editor_with_real_ljk_needs_no_labelling(root, tmp_path, monkeypatch):
    """The bought LJK (corner squares, name, number, code, birth date, 100
    questions) is ready to save right after opening: names are suggested."""
    import template_editor as te

    pdf = Path(__file__).parent / "data" / "ljk_kosong_smpn3.pdf"
    ed = te.TemplateEditor(root)
    monkeypatch.setattr(te.filedialog, "askopenfilename", lambda **k: str(pdf))
    ed.open_scan()
    pump(ed)
    status = ed.status_var.get()
    assert "1510 bulatan" in status and "100 soal" in status and "4 kotak hitam" in status
    shot = os.environ.get("OMR_SCREENSHOT_REAL")
    if shot:
        ed.geometry("1280x820+0+0")
        ed.deiconify()
        pump(ed, 20)
        subprocess.run(["import", "-window", "root", shot], check=False)

    folder = tmp_path / "Ujian"
    errors = []
    monkeypatch.setattr(te.messagebox, "showerror", lambda *a, **k: errors.append(a))
    monkeypatch.setattr(te.messagebox, "showinfo", lambda *a, **k: None)
    monkeypatch.setattr(te.filedialog, "askdirectory", lambda **k: str(folder))
    ed.save()
    assert not errors, errors
    template = json.loads((folder / "template.json").read_text())
    assert template["preProcessors"][0]["name"] == "AlignOnMarkers"
    assert set(template["customLabels"]) == {"Nama", "NIS", "KodeSoal", "TglLahir"}
    assert not (folder / tb.REFERENCE_FILENAME).exists()
    ed.destroy()


def test_results_preview_follows_selection(root, tmp_path, monkeypatch):
    """Selecting a result row shows its marked sheet in the right-hand pane;
    no double click or external viewer needed."""
    import gui

    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))  # fresh settings
    monkeypatch.setenv("HOME", str(tmp_path))
    img, layout = synth.make_blank()
    sheet = tb.prepare_sheet(img)
    _, blocks = tb.detect_blocks(sheet.page)
    for b in blocks:
        if b.kind == tb.KIND_DIGITS and not b.group:
            b.group = "Kode"
    template, problems = tb.build_template(blocks, sheet)
    assert not problems
    exam, out = tmp_path / "ujian", tmp_path / "hasil"
    tb.save_template_folder(exam, sheet, template)
    for k in range(2):
        filled = synth.fill(img, layout, synth.random_responses(layout, seed=k), seed=k)
        cv2.imencode(".jpg", filled)[1].tofile(str(exam / f"siswa_{k + 1}.jpg"))
    assert gui.run_batch(str(exam), str(out)) == 0
    sys.stdout, sys.stderr = sys.__stdout__, sys.__stderr__  # worker redirected them

    app = gui.run_gui(mainloop=False)
    try:
        app.geometry("1280x800+0+0")
        app.deiconify()
        import time

        time.sleep(0.3)  # let the start-up refresh (after 200 ms) run first
        pump(app, 10)
        app.output_var.set(str(out))
        app.refresh_results()
        pump(app, 10)
        assert app.tree.selection() == ("0",)  # first row picked automatically
        assert app.preview.winfo_width() > 300, "preview pane squeezed out by the table"
        assert app.preview_img is not None and app.preview.find_all()
        first = app.preview_name.get()
        app.tree.selection_set("1")
        pump(app, 10)
        assert app.preview_name.get() != first and app.preview_name.get().endswith(".jpg")
        app.zoom_preview(1.25)
        app.zoom_preview(None)
        nis_width = app.tree.column("NIS", "width")
        assert nis_width >= 8 * 10  # 10 digits fit
    finally:
        app.destroy()


def _exam_with_sheets(tmp_path, n=2):
    img, layout = synth.make_blank()
    sheet = tb.prepare_sheet(img)
    _, blocks = tb.detect_blocks(sheet.page)
    for b in blocks:
        if b.kind == tb.KIND_DIGITS and not b.group:
            b.group = "Kode"
    template, problems = tb.build_template(blocks, sheet)
    assert not problems
    exam = tmp_path / "ujian"
    tb.save_template_folder(exam, sheet, template)
    for k in range(n):
        filled = synth.fill(img, layout, synth.random_responses(layout, seed=k), seed=k)
        cv2.imencode(".jpg", filled)[1].tofile(str(exam / f"siswa_{k + 1}.jpg"))
    return exam


def test_preview_visible_after_processing_in_the_app(root, tmp_path, monkeypatch):
    """The reported case: open the app with no results, click Proses LJK,
    and the preview pane must show without restarting the app."""
    import time

    import gui

    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("HOME", str(tmp_path))
    exam = _exam_with_sheets(tmp_path)
    app = gui.run_gui(mainloop=False)
    try:
        app.geometry("1100x720+0+0")
        app.deiconify()
        pump(app, 10)
        app.input_var.set(str(exam))
        app.output_var.set(str(tmp_path / "hasil"))
        app.start()
        deadline = time.time() + 300
        while app.proc is not None and time.time() < deadline:
            app.update()
            time.sleep(0.05)
        pump(app, 30)
        assert app.status_var.get().startswith("2 LJK") or "Selesai" in app.status_var.get()
        assert len(app.current_rows) == 2
        assert app.tabs.index("current") == 0
        assert app.winfo_width() <= 1110, "window grew past its size"
        assert app.preview.winfo_width() > 300, "preview pane squeezed out"
        assert app.preview_img is not None and app.preview.find_all()
    finally:
        app.destroy()


def test_clear_results(root, tmp_path, monkeypatch):
    import gui

    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("HOME", str(tmp_path))
    exam = _exam_with_sheets(tmp_path, n=1)
    out = tmp_path / "hasil"
    assert gui.run_batch(str(exam), str(out)) == 0
    sys.stdout, sys.stderr = sys.__stdout__, sys.__stderr__
    app = gui.run_gui(mainloop=False)
    try:
        app.input_var.set(str(exam))
        app.output_var.set(str(out))
        app.refresh_results()
        assert app.current_rows
        errors = []
        monkeypatch.setattr(gui_messagebox(), "showerror", lambda *a, **k: errors.append(a))
        monkeypatch.setattr(gui_messagebox(), "askyesno", lambda *a, **k: True)

        # a file that OMRChecker did not write blocks the delete
        (out / "catatan guru.docx").write_text("penting")
        app.clear_results()
        assert errors and out.exists()
        (out / "catatan guru.docx").unlink()
        errors.clear()

        app.clear_results()
        assert not errors and not out.exists()
        assert app.current_rows == [] and app.preview_img is None
        assert exam.joinpath("siswa_1.jpg").exists()  # scans untouched
    finally:
        app.destroy()


def gui_messagebox():
    from tkinter import messagebox

    return messagebox
