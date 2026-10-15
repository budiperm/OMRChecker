"""Template builder on the Medion LJK: a filled sheet photographed with
CamScanner (faint print, low contrast), several parts that each restart at 1
(I: 130 x A/B, II: 88 x A-D, III: 8 x A-D, Motivasi: 10 x A/B, TYPE: A-D),
seat code columns with different letters, and big unlettered circles.

Ground truth = what is pencilled on the sheet, read by eye from the scan.

Run: python -m pytest tests_gui
"""

import csv
import json
import subprocess
import sys
from pathlib import Path

import cv2
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(Path(__file__).parent)]

import synth_ljk as synth  # noqa: E402
import template_builder as tb  # noqa: E402
import ujian  # noqa: E402

from testdata import needs  # noqa: E402

pytestmark = [needs("ljk_medion_terisi.pdf")]

SCAN = Path(__file__).parent / "data" / "ljk_medion_terisi.pdf"

# The student's name and birth date stay with the scan, out of the repo
_IDENT = SCAN.with_suffix(".json")
EXPECTED = {
    **(json.loads(_IDENT.read_text()) if _IDENT.exists() else {}),
    "JK": "P",
    "KodeDuduk": "A1",
    "KodeBuku": "X",
}
ANSWERS = {
    "I": "AABABABAAA" "BAABBAABAA",  # 1-20, 21-130 blank
    "II": "ABCCCDCBBAAB",  # 1-12, 13-88 blank
    "III": "ABACDCBB",
    "Motivasi": "AAAAAAAAAA",
    "TYPE": "D",
}
COUNTS = {"I": 130, "II": 88, "III": 8, "Motivasi": 10, "TYPE": 1}


@pytest.fixture(scope="module")
def sheet():
    return tb.prepare_sheet(tb.load_image(SCAN))


@pytest.fixture(scope="module")
def detected(sheet):
    return tb.detect_blocks(sheet)


def test_reads_scanned_pdf_at_native_resolution(sheet):
    assert sheet.uses_markers
    assert sheet.detail is not None and sheet.detail.shape[1] > 2000


def test_auto_detection(detected):
    bubbles, blocks = detected
    by_section = {}
    for b in blocks:
        if b.kind == tb.KIND_MCQ:
            by_section[b.section] = by_section.get(b.section, 0) + b.field_count
    # parts found and separated (II and the small III box share a column)
    assert by_section == {"I": 130, "II": 88, "III": 10, "IV": 1, "V": 8}
    others = sorted((b.kind, b.rows, b.cols, b.group) for b in blocks if b.kind != tb.KIND_MCQ)
    assert others == [
        (tb.KIND_CUSTOM, 26, 20, "Nama"),
        (tb.KIND_DIGITS, 10, 5, ""),  # seat code: split by the user
        (tb.KIND_DIGITS, 10, 6, "TglLahir"),
        (tb.KIND_IGNORE, 1, 2, ""),  # round letters in the heading
        (tb.KIND_IGNORE, 3, 5, ""),  # "how to fill in" example
    ]
    type_block = next(b for b in blocks if b.section == "IV")
    assert not type_block.horizontal and type_block.values == list("ABCD")


def label_like_a_teacher(bubbles, blocks):
    """What the user does in the editor for this sheet."""
    blocks = [tb.Block(**vars(b)) for b in blocks]  # keep the fixture intact
    rename = {"III": "Motivasi", "IV": "TYPE", "V": "III"}
    for b in blocks:
        if b.kind == tb.KIND_MCQ:
            b.section = rename.get(b.section, b.section)
    seat = next(b for b in blocks if (b.kind, b.rows, b.cols) == (tb.KIND_DIGITS, 10, 5))
    parts = tb.split_block(seat, "column", bubbles)
    letters_per_col = ["ABCDEFGHIJ", "KLMNOPQRST", "UVWXYZ", "123456789", "0123456789"]
    for part, values in zip(parts, letters_per_col):
        assert part.rows == len(values)
        tb.set_kind(part, tb.KIND_CUSTOM, list(values), horizontal=False)
        part.group = "KodeDuduk"
    blocks.remove(seat)
    blocks += parts
    # big unlettered circles: drawn by hand around them
    for name, (x, y1, y2), values in (("JK", (766, 283.5, 310.5), "LP"), ("KodeBuku", (630.5, 652.5, 685.5), "XY")):
        b = tb.block_from_rect(x - 9, y1 - 9, x + 9, y2 + 9, 2, 1, 18, 18)
        tb.set_kind(b, tb.KIND_CUSTOM, list(values), horizontal=False)
        b.group = name
        blocks.append(b)
    tb.number_mcq_blocks(blocks)
    return tb.sort_blocks(blocks)


def test_template_with_parts(detected, sheet):
    bubbles, blocks = detected
    blocks = label_like_a_teacher(bubbles, blocks)
    template, problems = tb.build_template(blocks, sheet)
    assert problems == []
    assert tb.sections_of(blocks) == {"I_": "I", "II_": "II", "III_": "III", "Motivasi_": "Motivasi", "TYPE_": "TYPE"}
    assert template["customLabels"]["KodeDuduk"] == [f"KodeDuduk_{i}" for i in range(1, 6)]
    labels = tb.question_labels(blocks)
    assert labels[:2] == ["I_1", "I_2"] and "II_88" in labels and labels[-1] == "TYPE_1"


@pytest.mark.parametrize("distortion", [None, {"angle": 1.5, "dx": 25, "dy": -20, "jpeg": 85}])
def test_reads_what_is_pencilled(tmp_path, detected, sheet, distortion):
    bubbles, blocks = detected
    blocks = label_like_a_teacher(bubbles, blocks)
    template, _ = tb.build_template(blocks, sheet)
    lib = ujian.save_to_library("Medion", sheet, template, blocks, tmp_path / "lib")
    info = ujian.read_library_template(lib)
    assert {n: len(q) for n, q in info.sections.items()} == COUNTS

    scans = tmp_path / "scan"
    scans.mkdir()
    if distortion is None:
        (scans / "siswa.pdf").write_bytes(SCAN.read_bytes())
    else:
        img = synth.distort(tb.load_image(SCAN), seed=1, **distortion)
        cv2.imencode(".jpg", img)[1].tofile(str(scans / "siswa.jpg"))
    out = tmp_path / "hasil"
    proc = subprocess.run(
        [sys.executable, str(ROOT / "gui.py"), "--process", str(scans), str(out), "--template", str(lib)],
        capture_output=True, text=True, timeout=600,
    )
    log = (out / "omrchecker_log.txt").read_text(encoding="utf-8") if out.exists() else ""
    assert proc.returncode == 0, log[-3000:] + proc.stderr[-2000:]
    rows, errors = ujian.read_results(out)
    assert len(rows) == 1 and not errors, log[-3000:]
    row = rows[0]

    wrong = [f"{k}: {row[k]!r} != {v!r}" for k, v in EXPECTED.items() if row[k].strip() != v]
    for part, labels in info.sections.items():
        marked = ANSWERS[part]
        for i, q in enumerate(labels):
            want = marked[i] if i < len(marked) else ""
            if row[q] != want:
                wrong.append(f"{part}-{i + 1}: {row[q]!r} != {want!r}")
    assert not wrong, "\n".join(wrong[:30])

    # scored per part with the pencilled answers as the key: all correct
    exam = ujian.Exam(keys={ujian.ALL_CODES: {p: ANSWERS[p] for p in COUNTS}})
    res = ujian.score_results(rows, errors, exam, info.sections)[0]
    assert {p: v["benar"] for p, v in res.parts.items()} == {p: len(ANSWERS[p]) for p in COUNTS}
    assert res.grade == 100


def test_filled_source_sheet_is_graded_not_skipped(tmp_path, detected):
    """The reported case: template made from medion_terisi.pdf (a filled
    sheet, there is no blank one) and that same file in the scan folder.
    It must be read, also with a template saved before this fix that still
    lists it in excludeFiles."""
    import json

    bubbles, blocks = detected
    sheet = tb.prepare_sheet(tb.load_image(SCAN), source_name="medion_terisi.pdf")
    blocks = label_like_a_teacher(bubbles, blocks)
    template, _ = tb.build_template(blocks, sheet)
    assert not sheet.source_blank
    assert "excludeFiles" not in template["preProcessors"][0]["options"]

    old_style = json.loads(json.dumps(template))
    old_style["preProcessors"][0]["options"]["excludeFiles"] = ["medion_terisi.pdf"]
    for name, t in (("baru", template), ("lama", old_style)):
        lib = ujian.save_to_library(name, sheet, t, blocks, tmp_path / "lib")
        if name == "lama":  # what the previous version saved
            (lib / "template.json").write_text(json.dumps(t), encoding="utf-8")
        scans = tmp_path / f"scan_{name}"
        scans.mkdir()
        (scans / "medion_terisi.pdf").write_bytes(SCAN.read_bytes())
        out = tmp_path / f"hasil_{name}"
        subprocess.run([sys.executable, str(ROOT / "gui.py"), "--process", str(scans), str(out),
                        "--template", str(lib)], capture_output=True, timeout=600)  # fmt: skip
        rows, errors = ujian.read_results(out)
        info = ujian.read_library_template(lib)
        res = ujian.score_results(rows, errors, ujian.Exam(), info.sections, blank_source=info.source)
        assert [r.info["Nama"].strip() for r in res] == [EXPECTED.get("Nama")], name
