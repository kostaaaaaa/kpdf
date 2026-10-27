"""Drive the real widget offscreen with real key events."""

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest

from kpdf.viewer import Viewer


@pytest.fixture
def viewer(qapp, paper_pdf):
    v = Viewer(paper_pdf)
    v.show()
    qapp.processEvents()
    yield v
    v.close()


def test_links_are_collected_lazily(qapp, paper_pdf):
    v = Viewer(paper_pdf)
    assert v._link_iter is not None and v._links == []  # nothing scanned before the first paint
    assert len(v.links) == 5  # first real use finishes the scan
    assert v._link_iter is None
    v.close()


def test_slash_selects_link_and_shows_preview(viewer):
    QTest.keyClick(viewer, "/")
    assert viewer.sel_active and 0 <= viewer.sel < len(viewer.links)
    assert viewer.preview is not None
    QTest.keyClick(viewer, Qt.Key.Key_Escape)
    assert viewer.preview is None


def test_cycle_forward_and_back(viewer):
    QTest.keyClick(viewer, "/")
    first = viewer.sel
    QTest.keyClick(viewer, "/")
    assert viewer.sel == (first + 1) % len(viewer.links)
    QTest.keyClick(viewer, "?")
    assert viewer.sel == first


def test_enter_follows_link_and_backspace_returns(viewer):
    QTest.keyClick(viewer, "/")
    target = viewer.links[viewer.sel].dpage
    sy_before = viewer.sy
    QTest.keyClick(viewer, Qt.Key.Key_Return)
    assert len(viewer.history) == 1
    assert viewer.current_page() == target
    QTest.keyClick(viewer, Qt.Key.Key_Backspace)
    assert viewer.history == []
    assert viewer.sy == pytest.approx(sy_before)  # back restores the exact scroll position


def test_page_jumps(viewer):
    QTest.keyClick(viewer, "B")
    assert viewer.current_page() == viewer.n - 1
    QTest.keyClick(viewer, "T")
    assert viewer.current_page() == 0
    QTest.keyClick(viewer, "J")
    assert viewer.current_page() == 1
    QTest.keyClick(viewer, "K")
    assert viewer.current_page() == 0
