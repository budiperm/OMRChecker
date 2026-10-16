"""Screenshots for PANDUAN.pdf: drives the wizard on synthetic LJK (Linux + Xvfb).
usage: xvfb-run -s "-screen 0 1280x800x24" python docs/panduan/shots.py . <outdir> <workdir>"""
import os
import subprocess
import sys
import time
from pathlib import Path


def main():
    repo, out, work = map(Path, sys.argv[1:4])
    sys.path[:0] = [str(repo), str(repo / "tests_gui")]
    os.environ["APPDATA"] = str(work / "appdata")
    out.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    import random

    import cv2
    import numpy as np

    import synth_ljk as synth
    import template_builder as tb
    import ujian
    from test_template_builder import label_like_user

    img, layout = synth.make_blank()
    blank_path = work / "LJK kosong.jpg"
    cv2.imencode(".jpg", img)[1].tofile(str(blank_path))
    sheet = tb.prepare_sheet(img)
    _, blocks = tb.detect_blocks(sheet.page)
    blocks = label_like_user([*blocks], layout)
    template, _ = tb.build_template(blocks, sheet)
    lib = work / "lib"
    ujian.save_to_library("LJK Ujian Umum", sheet, template, blocks, lib)
    scans = work / "LJK IPA 9A"
    scans.mkdir(parents=True, exist_ok=True)
    for k in range(8):
        r = synth.random_responses(layout, seed=k)
        page = synth.distort(synth.fill(img, layout, r, seed=k), angle=0.4 * k, seed=k, jpeg=90)
        cv2.imencode(".jpg", page)[1].tofile(str(scans / f"scan_{k + 1:04d}.jpg"))
    # a sheet the reader cannot use: shows as a red row
    cv2.imencode(".jpg", np.full((3508, 2480, 3), 235, np.uint8))[1].tofile(str(scans / "scan_0009.jpg"))

    import wizard as wz

    wz.messagebox.askyesno = lambda *a, **k: False
    wz.messagebox.showerror = lambda *a, **k: print("ERR", a)
    w = wz.run_wizard(mainloop=False, library=lib, settings=work / "sesi.json")
    w.geometry("1280x800+0+0")

    def pump(n=30):
        for _ in range(n):
            w.update()
            time.sleep(0.01)

    def shot(name, win=None):
        pump()
        if win is None:
            geo = "1280x800+0+0"
        else:
            win.update()
            geo = f"{win.winfo_width()}x{win.winfo_height()}+{win.winfo_rootx()}+{win.winfo_rooty()}"
        subprocess.run(["import", "-window", "root", "-crop", geo, str(out / f"{name}.png")])

    pump()
    shot("01_template")

    # new template from a blank LJK
    import template_editor

    template_editor.filedialog.askopenfilename = lambda **k: str(blank_path)
    ed = w.steps[0].editor()
    ed.geometry("1280x800+0+0")
    pump(20)
    ed.open_scan()
    pump(40)
    kids = ed.tree.get_children()
    if len(kids) > 5:
        ed.tree.selection_set(kids[5])
        pump(20)
    shot("02_editor")
    ed.destroy()
    pump()

    w.next()
    step = w.steps[1]
    rnd = random.Random(7)
    for part, t in step.texts.items():
        n = len(w.template.sections[part])
        t.delete("1.0", "end")
        t.insert("1.0", " ".join("".join(rnd.choice("ABCDE") for _ in range(5)) for _ in range(n // 5)))
        step.on_key_edit(part)
    step.kkm.set("75")
    shot("03_kunci")
    w.next()

    step = w.steps[2]
    step.folder.set(str(scans))
    shot("04_folder")

    import scan_dialog
    import scanner

    class Fake:
        name = "TWAIN"

        def devices(self):
            return [scanner.Device("TWAIN", "EPSON DS-410", "EPSON DS-410"),
                    scanner.Device("TWAIN", "PS283", "Plustek SmartOffice PS283")]

        def scan(self, device, opts, on_image, cancelled):
            return []

    d = scan_dialog.ScanDialog(step, str(scans), backends=[Fake()])
    d.geometry("+280+120")
    for _ in range(40):
        w.update()
        time.sleep(0.02)
    shot("05_scan_dialog", d)
    d.destroy()
    pump()

    w.next()
    step = w.steps[3]
    step.name.set("PTS IPA Kelas 9A")
    shot("06_hasil")
    w.next()

    step = w.steps[4]
    shot("07_siap")
    step.start()
    deadline = time.time() + 300
    while step.proc is not None and time.time() < deadline:
        w.update()
        time.sleep(0.05)
    pump(40)
    good = next(i for i, r in enumerate(step.results) if not r.flags)
    step.tree.selection_set(str(good))
    shot("08_proses")
    pump(20)
    step.correct()
    pump(30)
    dlg = next(c for c in step.winfo_children() if isinstance(c, wz.CorrectionDialog))
    dlg.geometry("1000x680+140+60")
    shot("09_koreksi", dlg)
    dlg.destroy()
    pump()
    w.next()
    shot("10_rekap")

    # closing without an export: the question shown before the window closes
    def ask(master, heading, text, buttons, detail=""):
        d = wz.ChoiceDialog(master, heading, text, buttons, detail)
        shot("11_tutup")
        d.destroy()
        return "batal"

    wz.ChoiceDialog.ask = staticmethod(ask)
    w.on_close()
    w.destroy()


if __name__ == "__main__":
    main()
