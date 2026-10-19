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
        assert step.progress_text.get() == "3 LJK akan diproses"  # the count shows before the click

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

    # reopen with both folders remembered: rekap is current -> "Selesai" shows
    # the closing screen, no export prompt
    ujian.save_prefs({ujian.PREF_SCANS: True, ujian.PREF_OUTPUT: True}, tmp / "sesi.json")
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


def test_old_exam_can_be_reopened_from_its_output_folder(setup, monkeypatch):
    import wizard as wz

    lib, scans, tmp = setup
    monkeypatch.setattr(wz.messagebox, "showerror", lambda *a, **k: pytest.fail(f"error: {a}"))
    monkeypatch.setattr(wz.messagebox, "askyesno", lambda *a, **k: True)  # confirm "Ujian baru"
    monkeypatch.setattr(wz.ChoiceDialog, "ask", staticmethod(lambda *a, **k: "tutup"))  # skip the export
    hasil = tmp / "hasil"
    ujian.Exam(scans_dir=str(scans), output_dir=str(hasil), name="Tes Rekrutmen").save(tmp / "sesi.json")
    w = wz.run_wizard(mainloop=False, library=lib, settings=tmp / "sesi.json")
    try:
        run_to_results(w)
        w.exam.corrections = {"siswa_1.jpg": {"q1": "B"}}
        w.exam.save(w.settings)
        assert (hasil / ujian.EXAM_FILE).is_file()
        w.next()
        w.steps[5].new_exam()  # the session now holds an empty exam
        assert w.exam.corrections == {} and w.exam.output_dir == ""

        monkeypatch.setattr(wz.filedialog, "askdirectory", lambda **k: str(hasil))
        w.open_exam()
        pump(w)
        assert w.current == 5
        assert w.exam.name == "Tes Rekrutmen" and w.exam.corrections == {"siswa_1.jpg": {"q1": "B"}}
        assert all(step.exam is w.exam for step in w.steps)
        assert len(w.steps[5].results) == 3
        assert ujian.Exam.load(tmp / "sesi.json").output_dir == str(hasil)  # it is the current exam again
    finally:
        try:
            w.destroy()
        except tk.TclError:
            pass


def test_open_exam_messages(setup, tmp_path):
    lib, _, _ = setup
    with pytest.raises(ValueError, match="bukan folder hasil"):
        ujian.open_exam(tmp_path, lib)
    folder = tmp_path / "hasil_lain"
    folder.mkdir()
    # made on another computer: template path differs, same name in this library
    exam = ujian.Exam(template=str(tmp_path / "pc-lain" / "LJK Sintetis"), output_dir=str(folder))
    exam.save(tmp_path / "sesi.json")
    opened = ujian.open_exam(folder, lib)
    assert Path(opened.template) == lib / "LJK Sintetis"
    exam.template = str(tmp_path / "Tidak Ada")
    exam.save(tmp_path / "sesi.json")
    with pytest.raises(ValueError, match="Tidak Ada"):
        ujian.open_exam(folder, lib)


def test_about_shows_license(setup, monkeypatch):
    import wizard as wz

    lib, _, tmp = setup
    shown = []
    answers = ["lisensi", "pihak"]
    monkeypatch.setattr(wz.ChoiceDialog, "ask",
                        staticmethod(lambda m, h, t, b, detail="": (shown.append((h, t)), answers.pop(0))[1]))  # fmt: skip
    monkeypatch.setattr(wz, "show_text", lambda parent, title, text: shown.append(text))
    w = wz.run_wizard(mainloop=False, library=lib, settings=tmp / "sesi.json")
    try:
        pump(w)
        w.about()
        heading, text = shown[0]
        assert heading == f"Pemindai LJK v{wz.VERSION}" and "AGPL-3.0" in text
        assert shown[1] == (ROOT / "LICENSE").read_text(encoding="utf-8")
        w.about()
        assert "MIT License" in shown[3] and "Udayraj" in shown[3]  # upstream notice
    finally:
        w.destroy()


def test_stopped_run_resumes_without_rereading(setup, monkeypatch):
    import csv

    import wizard as wz

    lib, scans, tmp = setup
    monkeypatch.setattr(wz.messagebox, "showerror", lambda *a, **k: pytest.fail(f"error: {a}"))
    asked = []
    monkeypatch.setattr(wz.ChoiceDialog, "ask", staticmethod(lambda m, h, t, b, detail="": (asked.append(t), "lanjut")[1]))
    hasil = tmp / "hasil"
    ujian.Exam(scans_dir=str(scans), output_dir=str(hasil)).save(tmp / "sesi.json")
    w = wz.run_wizard(mainloop=False, library=lib, settings=tmp / "sesi.json")
    try:
        step = run_to_results(w)
        assert step.done_count == 3 and step.progress["value"] == 3  # progress from the worker, not the log
        # as if the run had been stopped before siswa_2.jpg was read
        results_csv = next(hasil.rglob("Results/Results_*.csv"))
        with open(results_csv, newline="", encoding="utf-8") as fh:
            rows = list(csv.reader(fh))
        with open(results_csv, "w", newline="", encoding="utf-8") as fh:
            csv.writer(fh, quoting=csv.QUOTE_NONNUMERIC).writerows(r for r in rows if r[0] != "siswa_2.jpg")
        assert len(ujian.done_sheets(hasil)) == 2

        step.run_btn.invoke()
        assert asked == ["2 dari 3 LJK sudah diperiksa sebelumnya."]
        deadline = time.time() + 300
        while step.proc is not None:
            w.update()
            time.sleep(0.05)
            assert time.time() < deadline
        pump(w, 20)
        assert "".join(step.log).count("Opening image") == 1  # only the missing sheet was read
        assert len(step.results) == 3
    finally:
        try:
            w.destroy()
        except tk.TclError:
            pass


def test_rekap_order_and_participant_reports(setup, monkeypatch):
    import wizard as wz

    lib, scans, tmp = setup
    monkeypatch.setattr(wz.messagebox, "showerror", lambda *a, **k: pytest.fail(f"error: {a}"))
    monkeypatch.setattr(wz.messagebox, "askyesno", lambda *a, **k: False)
    ujian.Exam(scans_dir=str(scans), output_dir=str(tmp / "hasil")).save(tmp / "sesi.json")
    w = wz.run_wizard(mainloop=False, library=lib, settings=tmp / "sesi.json")
    try:
        run_to_results(w)
        w.next()
        step = w.steps[5]
        step.order.set(ujian.RANK_ORDERS["nilai"])
        step.on_order()
        assert w.exam.rekap_order == "nilai"
        pdf = tmp / "laporan.pdf"
        monkeypatch.setattr(wz.filedialog, "asksaveasfilename", lambda **k: str(pdf))
        step.export_reports()
        import fitz

        with fitz.open(str(pdf)) as doc:
            assert doc.page_count == 2  # the empty page has no report
    finally:
        try:
            w.destroy()
        except tk.TclError:
            pass


def test_template_export_and_import_buttons(setup, monkeypatch):
    import wizard as wz

    lib, _, tmp = setup
    monkeypatch.setattr(wz.messagebox, "showerror", lambda *a, **k: pytest.fail(f"error: {a}"))
    monkeypatch.setattr(wz.messagebox, "showinfo", lambda *a, **k: None)
    packed = tmp / "LJK Sintetis.ljk"
    monkeypatch.setattr(wz.filedialog, "asksaveasfilename", lambda **k: str(packed))
    monkeypatch.setattr(wz.filedialog, "askopenfilename", lambda **k: str(packed))
    w = wz.run_wizard(mainloop=False, library=lib, settings=tmp / "sesi.json")
    try:
        pump(w)
        step = w.steps[0]
        step.export_file()
        assert packed.is_file()
        step.import_file()
        assert [t.name for t in step.templates] == ["LJK Sintetis", "LJK Sintetis"]
        assert step.selected().path == lib / "LJK Sintetis (2)"
    finally:
        w.destroy()


def test_stop_reports_how_far_it_got(setup, monkeypatch):
    import wizard as wz

    lib, scans, tmp = setup
    monkeypatch.setattr(wz.messagebox, "showerror", lambda *a, **k: pytest.fail(f"error: {a}"))
    monkeypatch.setattr(wz.messagebox, "askyesno", lambda *a, **k: True)  # no answer key: read only
    ujian.Exam(scans_dir=str(scans), output_dir=str(tmp / "hasil")).save(tmp / "sesi.json")
    w = wz.run_wizard(mainloop=False, library=lib, settings=tmp / "sesi.json")
    try:
        pump(w)
        w.next()
        w.next()
        w.next()
        w.next()
        step = w.steps[4]
        step.run_btn.invoke()
        pump(w, 5)
        step.stop_btn.invoke()
        pump(w, 5)
        assert step.proc is None and step.progress_text.get() == "Dihentikan"
        assert step.summary.get().startswith("Dihentikan:") and "dari 3 LJK" in step.summary.get()
    finally:
        w.destroy()


def test_full_rerun_keeps_exam_file(setup, monkeypatch):
    import wizard as wz

    lib, scans, tmp = setup
    monkeypatch.setattr(wz.messagebox, "showerror", lambda *a, **k: pytest.fail(f"error: {a}"))
    monkeypatch.setattr(wz.ChoiceDialog, "ask", staticmethod(lambda *a, **k: "ulang"))
    hasil = tmp / "hasil"
    ujian.Exam(scans_dir=str(scans), output_dir=str(hasil)).save(tmp / "sesi.json")
    w = wz.run_wizard(mainloop=False, library=lib, settings=tmp / "sesi.json")
    try:
        step = run_to_results(w)
        (scans / "baru.jpg").write_bytes((scans / "siswa_1.jpg").read_bytes())  # a 4th scan arrives
        (hasil / "catatan saya.txt").write_text("jangan dihapus")
        w.go(4)
        step.run_btn.invoke()
        deadline = time.time() + 300
        while step.proc is not None:
            w.update()
            time.sleep(0.05)
            assert time.time() < deadline
        pump(w, 20)
        assert "".join(step.log).count("Opening image") == 4  # everything read again
        assert (hasil / ujian.EXAM_FILE).is_file() and (hasil / "catatan saya.txt").is_file()
        assert len(step.results) == 4
    finally:
        try:
            w.destroy()
        except tk.TclError:
            pass


def test_remember_folder_checkboxes(setup, monkeypatch):
    """Steps 3 and 4: 'Ingat folder ini' is off by default; after a finished
    (exported) exam or 'Ujian baru' only the checked folders are kept."""
    import wizard as wz

    lib, scans, tmp = setup
    monkeypatch.setattr(wz.messagebox, "askyesno", lambda *a, **k: True)
    hasil = tmp / "hasil"
    done = ujian.Exam(scans_dir=str(scans), output_dir=str(hasil), exported_file=str(tmp / "rekap.xlsx"),
                      corrections={"siswa_1.jpg": {"q1": "B"}})  # fmt: skip
    done.save(tmp / "sesi.json")

    # default: nothing remembered, the next exam starts with empty folders
    w = wz.run_wizard(mainloop=False, library=lib, settings=tmp / "sesi.json")
    try:
        pump(w)
        assert not w.steps[2].remember.var.get() and not w.steps[3].remember.var.get()
        assert w.exam.scans_dir == "" and w.exam.output_dir == "" and w.exam.corrections == {}
        w.next()
        w.next()
        assert w.current == 2 and w.steps[2].folder.get() == ""
        # check "remember" in step 3: saved right away as a preference
        w.steps[2].remember.invoke()
        assert ujian.load_prefs(tmp / "sesi.json") == {ujian.PREF_SCANS: True, ujian.PREF_OUTPUT: False}
        w.steps[2].folder.set(str(scans))
        w.next()
        assert w.current == 3 and w.steps[3].folder.get().endswith("scan_hasil")

        # "Ujian baru": the remembered scan folder stays, the output folder is cleared
        w.exam.output_dir = str(hasil)
        w.steps[5].new_exam()
        assert w.exam.scans_dir == str(scans) and w.exam.output_dir == ""
    finally:
        w.destroy()

    # both remembered: a finished exam keeps its folders on the next start
    ujian.save_prefs({ujian.PREF_SCANS: True, ujian.PREF_OUTPUT: True}, tmp / "sesi.json")
    done.save(tmp / "sesi.json")
    w = wz.run_wizard(mainloop=False, library=lib, settings=tmp / "sesi.json")
    try:
        pump(w)
        assert w.steps[2].remember.var.get() and w.steps[3].remember.var.get()
        assert w.exam.scans_dir == str(scans) and w.exam.output_dir == str(hasil)
    finally:
        w.destroy()


def test_archive_old_scans(setup, monkeypatch):
    """Step 3 'Arsipkan scan lama': the scans move to _arsip/<date time> (not
    deleted, not read again), corrections are dropped and step 4 then
    replaces the old results, so a re-scan does not double up."""
    import wizard as wz

    lib, scans, tmp = setup
    asked = []
    monkeypatch.setattr(wz.ChoiceDialog, "ask", classmethod(lambda cls, *a, **k: asked.append(a) or "arsip"))
    hasil = tmp / "hasil"
    (hasil / "Results").mkdir(parents=True)
    (hasil / "Results" / "Results_01PM.csv").write_text("file_id\n")
    ujian.Exam(scans_dir=str(scans), output_dir=str(hasil), corrections={"siswa_1.jpg": {"q1": "B"}}).save(tmp / "sesi.json")
    w = wz.run_wizard(mainloop=False, library=lib, settings=tmp / "sesi.json")
    try:
        pump(w)
        w.next()
        for part, text in w.steps[1].texts.items():
            text.insert("1.0", "A" * len(w.template.sections[part]))
            w.steps[1].on_key_edit(part)
        w.next()
        assert w.current == 2
        step = w.steps[2]
        assert step.count.get().startswith("3 file") and str(step.archive_btn["state"]) == "normal"
        step.archive_btn.invoke()
        assert "3 file scan" in asked[0][2]
        archived = list((scans / wz.ARCHIVE_DIR).rglob("*.jpg"))
        assert len(archived) == 3 and not list(scans.glob("*.jpg"))
        assert wz.scan_files(scans) == [] and step.count.get().startswith("0 file")
        assert str(step.archive_btn["state"]) == "disabled" and w.exam.corrections == {}

        # the re-scan lands in the same folder; old results get replaced in step 4
        (scans / "scan_0001.jpg").write_bytes(archived[0].read_bytes())
        step.scan()
        w.steps[3].policy.set("keep")
        w.next()
        assert w.current == 3 and w.steps[3].policy.get() == "replace"

        # only the new scan is read: the archived ones are skipped by the run too
        w.next()
        step = w.steps[4]
        assert w.current == 4 and step.progress_text.get() == "1 LJK akan diproses"
        step.run_btn.invoke()
        deadline = time.time() + 300
        while step.proc is not None:
            w.update()
            time.sleep(0.05)
            assert time.time() < deadline, "processing did not finish"
        pump(w, 20)
        assert [r.file_id for r in step.results] == ["scan_0001.jpg"]
        assert not list(hasil.rglob(wz.ARCHIVE_DIR))
    finally:
        w.destroy()


def test_unfinished_exam_keeps_folders(setup):
    """An exam not exported yet (e.g. processing stopped halfway) is resumed
    with its folders, whatever the checkboxes say."""
    import wizard as wz

    lib, scans, tmp = setup
    ujian.Exam(scans_dir=str(scans), output_dir=str(tmp / "hasil")).save(tmp / "sesi.json")
    w = wz.run_wizard(mainloop=False, library=lib, settings=tmp / "sesi.json")
    try:
        pump(w)
        assert w.exam.scans_dir == str(scans) and w.exam.output_dir == str(tmp / "hasil")
    finally:
        w.destroy()
