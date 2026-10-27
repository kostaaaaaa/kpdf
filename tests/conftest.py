"""Shared fixtures. All PDFs are generated on the fly, so no paper is ever committed."""

import os
import random

# Must be set before Qt is imported anywhere: tests run without a display.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pymupdf  # noqa: E402
import pytest  # noqa: E402

WORDS = (
    "quantum error correction stabilizer syndrome decoder logical qubit threshold surface code "
    "noise channel"
).split()


def _filler(page, rng, lines=40, y0=100):
    y = y0
    for _ in range(lines):
        page.insert_text((50, y), " ".join(rng.choice(WORDS) for _ in range(10)), fontsize=9)
        y += 12


def _link(page, needle, dest_page, dest_y):
    """Make the first occurrence of `needle` on `page` a link to (dest_page, y=dest_y)."""
    rect = page.search_for(needle)[0]
    page.insert_link(
        {
            "kind": pymupdf.LINK_GOTO,
            "from": rect,
            "page": dest_page,
            "to": pymupdf.Point(50, dest_y),
        }
    )


@pytest.fixture(scope="session")
def paper_pdf(tmp_path_factory) -> str:
    """A tiny 'paper': citations and a figure reference that link to pages 3 and 2."""
    rng = random.Random(7)
    doc = pymupdf.open()
    for _ in range(4):  # create every page first: adding pages invalidates earlier Page objects
        doc.new_page()

    doc[0].insert_text((50, 60), "Surface codes [1] and decoders [2] reduce noise.", fontsize=10)
    doc[0].insert_text((50, 80), "Fig. 1 shows the QEC cycle.", fontsize=10)
    _filler(doc[0], rng)
    doc[1].insert_text((50, 60), "Threshold results in [3] and again [1] later.", fontsize=10)
    _filler(doc[1], rng)

    doc[2].insert_text((50, 100), "Figure 1: The QEC cycle.", fontsize=10)
    doc[2].draw_rect(pymupdf.Rect(60, 120, 300, 260))

    doc[3].insert_text((50, 60), "References", fontsize=12)
    for i, y in enumerate((100, 115, 130), start=1):
        doc[3].insert_text((50, y), f"[{i}] A. Author, Paper number {i}, 2020.", fontsize=9)

    _link(doc[0], "[1]", 3, 100)
    _link(doc[0], "[2]", 3, 115)
    _link(doc[0], "Fig. 1", 2, 100)
    _link(doc[1], "[3]", 3, 130)
    _link(doc[1], "[1]", 3, 100)

    path = tmp_path_factory.mktemp("pdf") / "paper.pdf"
    doc.save(path)
    return str(path)


@pytest.fixture(scope="session")
def dense_pdf(tmp_path_factory) -> str:
    """Link-dense pages with arbitrary rectangles, for comparing against a brute-force scan."""
    rng = random.Random(1)
    n = 3
    doc = pymupdf.open()
    for _ in range(n):
        _filler(doc.new_page(), rng, lines=55, y0=60)
    for page in doc:
        for _ in range(30):
            x, y = 50 + rng.random() * 400, 60 + rng.random() * 600
            page.insert_link(
                {
                    "kind": pymupdf.LINK_GOTO,
                    "from": pymupdf.Rect(x, y - 9, x + 30, y + 2),
                    "page": rng.randrange(n),
                    "to": pymupdf.Point(50, 100),
                }
            )
    path = tmp_path_factory.mktemp("pdf") / "dense.pdf"
    doc.save(path)
    return str(path)


@pytest.fixture(scope="session")
def qapp():
    from PyQt6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])
