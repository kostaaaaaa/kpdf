import pymupdf

from kpdf.viewer import collect_links


def test_paper_links_in_reading_order(paper_pdf):
    with pymupdf.open(paper_pdf) as doc:
        links = collect_links(doc)
    got = [(lk.page, lk.text, lk.dpage) for lk in links]
    assert got == [
        (0, "[1]", 3),
        (0, "[2]", 3),
        (0, "Fig. 1", 2),
        (1, "[3]", 3),
        (1, "[1]", 3),
    ]


def test_word_lookup_matches_brute_force(dense_pdf):
    """The bisect-based word lookup must agree with the obvious O(links x words) scan."""
    with pymupdf.open(dense_pdf) as doc:
        links = collect_links(doc)
        assert len(links) == 90
        for lk in links:
            expected = []
            for w in doc[lk.page].get_text("words"):
                cx, cy = (w[0] + w[2]) / 2, (w[1] + w[3]) / 2
                if lk.rect.x0 <= cx <= lk.rect.x1 and lk.rect.y0 <= cy <= lk.rect.y1:
                    expected.append(w[4])
            assert lk.text == " ".join(expected)
