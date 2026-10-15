"""Sample LJK PDFs used by some tests. They are real forms (one filled in by a
student), so they are kept out of the public repo: put them in
tests_gui/data/ to run those tests, otherwise they are skipped."""

from pathlib import Path

import pytest

DATA = Path(__file__).parent / "data"


def needs(name):
    return pytest.mark.skipif(not (DATA / name).exists(), reason=f"tests_gui/data/{name} tidak ada")
