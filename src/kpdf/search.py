"""Text search over a PDF, built to stay small on long documents.

Case-insensitive (it is PyMuPDF's page search, which also sees through ligatures such as "fi" and
joins words hyphenated across lines). Everything is per page and lazy:

* for the whole document only the *number* of hits per page is kept (one int per page);
* hit rectangles are kept just for the pages being looked at, in a small LRU capped at
  ``MAX_HELD`` rectangles, so even a one-letter search in a 2,000-page book stays a few MB.

Hits are ordered page by page in text-flow order, which for two-column papers is reading order.
Note: PyMuPDF reports a phrase that wraps over a line break as one rectangle per line.
"""

from collections import OrderedDict

MAX_HELD = 20_000

Hit = tuple[int, int, bool]  # (page, index within that page, wrapped around the document?)


class PageSearch:
    def __init__(self, doc, needle: str):
        self.doc = doc
        self.needle = needle
        self.n = doc.page_count
        self.counts: list[int | None] = [None] * self.n
        self.counted = 0  # pages whose hit count is known
        self.total = 0  # hits on those pages
        self._rects: OrderedDict[int, list] = OrderedDict()
        self._held = 0
        self._scan_pos = 0

    @property
    def done(self) -> bool:
        return self.counted == self.n

    def _set_count(self, i: int, c: int) -> None:
        if self.counts[i] is None:
            self.counts[i] = c
            self.counted += 1
            self.total += c

    # ------------------------------------------------------------ per-page data
    def rects(self, i: int) -> list:
        """Hit rectangles on page ``i`` (PDF points), cached for recently used pages."""
        hits = self._rects.get(i)
        if hits is not None:
            self._rects.move_to_end(i)
            return hits
        hits = list(self.doc[i].search_for(self.needle))
        self._set_count(i, len(hits))
        self._rects[i] = hits
        self._held += len(hits)
        while self._held > MAX_HELD and len(self._rects) > 1:
            _, old = self._rects.popitem(last=False)
            self._held -= len(old)
        return hits

    def count(self, i: int) -> int:
        if self.counts[i] is None:
            self.rects(i)
        return self.counts[i]

    def scan_next(self) -> bool:
        """Count the hits of the next page not yet counted, keeping no rectangles.

        Meant to be called from an idle timer. Returns True while pages remain to be counted.
        """
        while self._scan_pos < self.n and self.counts[self._scan_pos] is not None:
            self._scan_pos += 1
        if self._scan_pos >= self.n:
            return False
        i = self._scan_pos
        self._set_count(i, len(self.doc[i].search_for(self.needle)))
        self._scan_pos += 1
        return not self.done

    def ordinal(self, page: int, idx: int) -> int | None:
        """1-based number of a hit in the whole document, or None until earlier pages are counted."""
        before = self.counts[:page]
        if None in before:
            return None
        return sum(before) + idx + 1

    # -------------------------------------------------------------- navigation
    def step(self, page: int, idx: int, forward: bool) -> Hit | None:
        """The hit after (or before) hit ``idx`` of ``page``, wrapping around the document."""
        if forward:
            if idx + 1 < len(self.rects(page)):
                return page, idx + 1, False
            for k in range(1, self.n + 1):
                p = (page + k) % self.n
                if self.count(p):
                    return p, 0, page + k >= self.n
        else:
            if idx > 0:
                return page, idx - 1, False
            for k in range(1, self.n + 1):
                p = (page - k) % self.n
                c = self.count(p)
                if c:
                    return p, c - 1, page - k < 0
        return None

    def locate(self, page: int, y: float, forward: bool = True) -> Hit | None:
        """First hit at or below height ``y`` of ``page`` (forward), or the last hit above it
        (backward); continues through the following / preceding pages and wraps around."""
        hits = self.rects(page)
        if forward:
            for k, r in enumerate(hits):
                if r.y1 >= y:
                    return page, k, False
            return self.step(page, len(hits) - 1, True)
        for k in range(len(hits) - 1, -1, -1):
            if hits[k].y0 < y:
                return page, k, False
        return self.step(page, 0, False)
