"""
kpdf - a small keyboard-driven PDF viewer with keyboard-triggered link previews.

Usage:         kpdf paper.pdf          (also: python -m kpdf paper.pdf)
               kpdf --version

Keys
  h j k l        scroll left / down / up / right
  w / s          fit width / fit height
  t / b          top / bottom of the current page
  T / B          top of first page / bottom of last page
  <number>       jump to that page (digits are buffered; Enter jumps now)
  J / K          next / previous page
  Ctrl-d / u     half-screen down / up      Space / PageDown / PageUp: screen
  + / -          zoom in / out
  /  and  ?      cycle forward / backward through internal links
                 (citations, figures, tables, equations, sections) and
                 show a preview of the destination.  (? is Shift+/ on US keyboards)
  Tab / Shift-Tab  same as / and ?
  Esc            close preview (or cancel a half-typed page number)
  Enter          follow the selected link
  Backspace / Ctrl-o   go back to where you were before following a link / jumping
  i              invert colours
  q              quit
"""

import bisect
import contextlib
import math
import os
import re
import statistics
import sys
from collections import OrderedDict
from dataclasses import dataclass

# PyMuPDF 2.x imports its (unused here) ONNX layout module on `import pymupdf`, which costs ~0.5 s.
sys.modules.setdefault("pymupdf.layout", None)
try:
    import pymupdf as fitz
except ImportError:  # older PyMuPDF versions
    import fitz

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer  # noqa: E402
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap  # noqa: E402
from PyQt6.QtWidgets import QApplication, QWidget  # noqa: E402

# ----------------------------------------------------------------- tunables
GAP = 12  # px between pages
STEP = 70  # px per h/j/k/l press
ZOOM_STEP = 1.1
NUM_TIMEOUT_MS = 450  # wait this long for another digit of a page number
PREVIEW_MIN_SCALE = 1.3  # previews are rendered at least this readable
CACHE_BYTES = 512 * 1024 * 1024
BG = QColor(38, 38, 38)
ACCENT = QColor(255, 190, 0)

EQ_ABOVE, EQ_BELOW = 16, 54  # pt shown above/below an equation anchor
GENERIC_ABOVE, GENERIC_BELOW = 10, 130
FLOAT_MAX_H = 600  # pt, cap on figure/table previews

LABEL_RE = re.compile(r"^\s*(\[\d+[\d,\s\-–]*\]|\(\d+\)|\d{1,3}\.\s)")
CAP_RE = re.compile(r"^\s*(fig(ure)?|table|tab|algorithm|alg|scheme)\b\.?\s*[\dIVXLCS]", re.I)
EQNUM_RE = re.compile(r"\(\s*[A-Z]?\d+(\.\d+)*[a-z]?\s*\)\s*$")
TAG_RE = re.compile(r"^\s*\(\s*[A-Z]?\d+(\.\d+)*[a-z]?\s*\)\s*$")  # a lone "(3)"
TAG_NUM_RE = re.compile(r"\(\s*([A-Z]?\d+(?:\.\d+)*[a-z]?)\s*\)\s*$")  # number inside "(3)"
LINK_NUM_RE = re.compile(r"[A-Z]?\d+(?:\.\d+)*[a-z]?")  # "(4)", "Eq. 4", "2.1."
CITE_NUM_RE = re.compile(r"^[\[\(\s]*(\d{1,3})\b")  # "[12]", "[2,", "3]."
# hyperref names its destinations by type ("cite.key", "equation.2.4", "figure.1", ...).
# When the PDF has such names they are by far the most reliable hint for what a link points at.
NAME_KINDS = (
    ("cite", re.compile(r"^(cite|bib|bibitem|ref|refs)[.:_\-@]", re.I)),
    ("eq", re.compile(r"^(equation|eqn?s?)[.:_\-]", re.I)),
    (
        "float",
        re.compile(
            r"^(figure|fig|table|tab|tbl|algorithm|alg|listing|lstlisting|scheme)[.:_\-]", re.I
        ),
    ),
    (
        "generic",
        re.compile(
            r"^(section|subsection|subsubsection|chapter|appendix|page|item|hfootnote|footnote|"
            r"theorem|lemma|proposition|definition|corollary|remark)([.:_\-]|\d|$)",
            re.I,
        ),
    ),
)
MATH_FONT_RE = re.compile(
    r"(cmmi|cmsy|cmex|cmbsy|msam|msbm|eufm|eusm|eurm|rsfs|stmary|mtmi|mtsy|mtex|"
    r"txmi|txsy|txex|newtxmi|newtxsy|newtxex|math|symbol)",
    re.I,
)
MATH_CHARS = set(
    "\u2211\u222b\u220f\u221a\u2202\u2207\u221e\u2264\u2265\u2248\u2260\u00b1\u00d7"
    "\u2297\u2295\u27e8\u27e9\u2208\u2200\u2203\u2192\u2190\u21d2"
)
REFS_RE = re.compile(
    r"^\s*(\d+\.?|[IVX]+\.?|[A-Z]\.)?\s*(references|reference list|bibliography|"
    r"literature cited|works cited)\s*:?\s*$",
    re.I,
)


# ------------------------------------------------------------------- links
@dataclass
class Link:
    page: int  # page the link lives on
    rect: "fitz.Rect"  # link area on that page (pt, top-left origin)
    dpage: int  # destination page
    dest: "fitz.Point"  # destination point on dpage (pt, TOP-LEFT origin, see _named_point)
    text: str  # text under the link ("[12]", "Fig. 3", ...)
    name: str = ""  # PDF named destination, e.g. "cite.gottesman97" (may be empty)


def _union(a, b):
    """Rect union that (unlike Rect | Rect) does not ignore zero-height rects."""
    return fitz.Rect(min(a.x0, b.x0), min(a.y0, b.y0), max(a.x1, b.x1), max(a.y1, b.y1))


def _finite(*vals):
    return all(isinstance(v, (int, float)) and math.isfinite(v) and abs(v) < 1e7 for v in vals)


def name_kind(name):
    for kind, rx in NAME_KINDS:
        if rx.match(name or ""):
            return kind
    return None


def _named_point(tm, info):
    """Destination point of a Document.resolve_names() entry, in page space.

    This is THE catch: resolve_names() (and the 'to' PyMuPDF attaches to named links) is in raw
    PDF user space - origin bottom-left, y pointing up - whereas a direct GoTo link from
    Page.get_links() is already in MuPDF page space (origin top-left).  hyperref/LaTeX papers use
    named destinations for everything, so treating these y values as top-left mirrored every
    destination vertically (previews showed the wrong text, Enter jumped to the wrong spot).
    `tm` is the destination page's transformation_matrix (flips y, handles CropBox offsets).
    """
    to = info.get("to")
    if to is None:  # e.g. {"dest": "/FitH 700"} or "/Fit"
        toks = (info.get("dest") or "").split()
        vals = []
        for tk in toks[1:]:
            try:
                vals.append(float(tk))
            except ValueError:
                vals.append(None)  # "null"
        kind = toks[0] if toks else ""
        if kind == "/XYZ" and len(vals) >= 2:
            to = (vals[0], vals[1])
        elif kind in ("/FitH", "/FitBH") and vals:
            to = (None, vals[0])
        elif kind == "/FitR" and len(vals) >= 4:
            to = (vals[0], vals[3])
        else:
            return fitz.Point(0, 0)  # /Fit, /FitV, ...: top of the page
    x, y = to[0], to[1]
    if y is None or not _finite(y):
        return fitz.Point(0, 0)
    x = x if (x is not None and _finite(x)) else 0.0
    return fitz.Point(x, y) * tm


def iter_page_links(doc):
    """Yield the internal links of each page in turn (reading order within a page)."""
    names = None
    tms = {}  # page number -> transformation_matrix

    def tm_of(p):
        if p not in tms:
            tms[p] = doc[p].transformation_matrix
        return tms[p]

    for pno in range(doc.page_count):
        page = doc[pno]
        raw = page.get_links()
        if not raw:
            yield []
            continue
        words = page.get_text("words")  # content-stream order == reading order for LaTeX
        # index word centres by y once, so each link only inspects the words on its own lines
        byy = sorted(((w[1] + w[3]) / 2, i, (w[0] + w[2]) / 2) for i, w in enumerate(words))
        ys = [a[0] for a in byy]
        found = []
        for lk in raw:
            dpage, pt, nm = -1, None, ""
            kind = lk.get("kind")
            if kind == fitz.LINK_GOTO:
                # direct destination: PyMuPDF already reports it in page space (top-left origin)
                dpage, to = lk.get("page", -1), lk.get("to")
                if to is not None and _finite(to[0], to[1]):
                    pt = fitz.Point(to)
            elif kind == fitz.LINK_NAMED:
                nm = lk.get("nameddest") or lk.get("name") or ""
                info = None
                try:
                    if names is None:
                        names = doc.resolve_names()
                    info = names.get(nm) if nm else None
                except Exception:
                    names = names if names is not None else {}
                if info:
                    dpage = info.get("page", -1)
                    if dpage is not None and 0 <= dpage < doc.page_count:
                        pt = _named_point(tm_of(dpage), info)
                elif lk.get("page") is not None and lk.get("to") is not None:
                    # newer PyMuPDF resolves the name itself - same raw PDF space as above
                    dpage = lk["page"]
                    if 0 <= dpage < doc.page_count:
                        pt = _named_point(tm_of(dpage), {"to": tuple(lk["to"])})
            if dpage is None or dpage < 0 or dpage >= doc.page_count:
                continue
            r = fitz.Rect(lk["from"])
            if r.width < 1 or r.height < 1:
                continue
            lo, hi = bisect.bisect_left(ys, r.y0), bisect.bisect_right(ys, r.y1)
            idx = sorted(i for _, i, cx in byy[lo:hi] if r.x0 <= cx <= r.x1)
            toks = [words[i][4] for i in idx]
            key = idx[0] if idx else 10**6 + int(r.y0 * 10)
            if pt is None:
                pt = fitz.Point(0, 0)
            found.append((key, r.x0, Link(pno, r, dpage, pt, " ".join(toks), nm)))
        found.sort(key=lambda a: (a[0], a[1]))
        yield [a[2] for a in found]


def collect_links(doc):
    """All internal links, in reading order (page by page, content-stream order)."""
    return [lk for page_links in iter_page_links(doc) for lk in page_links]


# ------------------------------------------------------------------ viewer
class Viewer(QWidget):
    def __init__(self, path):
        super().__init__()
        self.doc = fitz.open(path)
        if self.doc.needs_pass:
            raise SystemExit("Encrypted PDFs are not supported.")
        self.n = self.doc.page_count
        if self.n == 0:
            raise SystemExit("Empty document.")
        self.sizes = [(self.doc[i].rect.width, self.doc[i].rect.height) for i in range(self.n)]

        self.zoom = 1.0
        self.sx = self.sy = 0.0
        self.fit = "w"
        self.invert = False
        self.cache = OrderedDict()
        self._lines = {}
        self._mathflag = {}
        self._cols = {}
        self._refs = None
        self._refs_done = False

        self._links = []
        self._link_iter = iter_page_links(self.doc)
        QTimer.singleShot(0, self._pump_links)
        self.sel = -1
        self.sel_active = False
        self.preview = None  # (QPixmap, logical_w, logical_h)
        self.preview_kind = ""  # what the preview shows: cite / eq / float / generic
        self.history = []
        self.num = ""
        self.num_timer = QTimer(self)
        self.num_timer.setSingleShot(True)
        self.num_timer.timeout.connect(self.commit_number)

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setWindowTitle(os.path.basename(path))
        self.resize(900, 1000)
        self.tops = []
        self.relayout()
        self.apply_fit()

    # ---- links are collected lazily: the window shows first, pages are scanned in idle time
    def _pump_links(self):
        if self._link_iter is None:
            return
        try:
            self._links.extend(next(self._link_iter))
        except StopIteration:
            self._link_iter = None
            return
        QTimer.singleShot(0, self._pump_links)

    @property
    def links(self):
        if self._link_iter is not None:  # link navigation needs the full list now
            for page_links in self._link_iter:
                self._links.extend(page_links)
            self._link_iter = None
        return self._links

    # Tab must reach keyPressEvent instead of moving focus
    def focusNextPrevChild(self, nxt):
        return False

    # ------------------------------------------------------------- layout
    def relayout(self):
        y = float(GAP)
        self.tops = []
        for _, h in self.sizes:
            self.tops.append(y)
            y += h * self.zoom + GAP
        self.total_h = y
        maxw = max(w for w, _ in self.sizes)
        self.content_w = max(maxw * self.zoom + 2 * GAP, self.width())
        self.clamp()

    def clamp(self):
        self.sy = min(max(self.sy, 0.0), max(0.0, self.total_h - self.height()))
        self.sx = min(max(self.sx, 0.0), max(0.0, self.content_w - self.width()))

    def page_at(self, y):
        i = bisect.bisect_right(self.tops, y) - 1
        return min(max(i, 0), self.n - 1)

    def current_page(self):
        return self.page_at(self.sy + self.height() / 2)

    def page_x(self, i):
        return (self.content_w - self.sizes[i][0] * self.zoom) / 2 - self.sx

    def link_view_rect(self, L):
        x = self.page_x(L.page) + L.rect.x0 * self.zoom
        y = self.tops[L.page] + L.rect.y0 * self.zoom - self.sy
        return QRectF(x, y, L.rect.width * self.zoom, L.rect.height * self.zoom)

    def set_zoom(self, z):
        z = min(max(z, 0.1), 8.0)
        cy = self.sy + self.height() / 2
        i = self.page_at(cy)
        frac = (cy - self.tops[i]) / (self.sizes[i][1] * self.zoom)
        fx = (self.sx + self.width() / 2) / self.content_w
        self.zoom = z
        self.relayout()
        self.sy = self.tops[i] + frac * self.sizes[i][1] * z - self.height() / 2
        self.sx = fx * self.content_w - self.width() / 2
        self.clamp()
        self.update()

    def apply_fit(self):
        if self.fit == "w":
            self.set_zoom((self.width() - 2 * GAP) / max(w for w, _ in self.sizes))
        elif self.fit == "s":
            i = self.current_page()
            self.set_zoom((self.height() - 2 * GAP) / self.sizes[i][1])
            self.sy = self.tops[i] - (self.height() - self.sizes[i][1] * self.zoom) / 2
            self.clamp()
            self.update()

    def resizeEvent(self, e):
        self.relayout()
        if self.fit:
            self.apply_fit()
        if self.sel_active:
            self.build_preview(self.links[self.sel])

    # ----------------------------------------------------------- rendering
    def page_image(self, i):
        dpr = self.devicePixelRatioF()
        key = (i, round(self.zoom * dpr, 4))
        img = self.cache.get(key)
        if img is not None:
            self.cache.move_to_end(key)
            return img
        s = self.zoom * dpr
        pix = self.doc[i].get_pixmap(matrix=fitz.Matrix(s, s), alpha=False)
        img = QImage(
            pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888
        ).copy()
        img.setDevicePixelRatio(dpr)
        self.cache[key] = img
        total = sum(v.sizeInBytes() for v in self.cache.values())
        while len(self.cache) > 2 and total > CACHE_BYTES:
            _, old = self.cache.popitem(last=False)
            total -= old.sizeInBytes()
        return img

    def _invert_rect(self, p, r):
        p.save()
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Difference)
        p.fillRect(r, Qt.GlobalColor.white)
        p.restore()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.fillRect(self.rect(), BG)
        vw, vh = self.width(), self.height()

        i = self.page_at(self.sy)
        while i < self.n and self.tops[i] - self.sy < vh:
            pw, ph = self.sizes[i][0] * self.zoom, self.sizes[i][1] * self.zoom
            x, y = self.page_x(i), self.tops[i] - self.sy
            if y + ph > 0 and x + pw > 0 and x < vw:
                r = QRectF(x, y, pw, ph)
                p.drawImage(r, self.page_image(i))
                if self.invert:
                    self._invert_rect(p, r)
            i += 1

        link = self._links[self.sel] if 0 <= self.sel < len(self._links) else None
        if self.sel_active and link is not None:
            r = self.link_view_rect(link)
            p.fillRect(r, QColor(255, 200, 0, 90))
            p.setPen(QPen(ACCENT, 1.5))
            p.drawRect(r)

            if self.preview is not None and self.link_visible(self.sel):
                pix, w, h = self.preview
                x = min(max(r.left() - 16, 8), max(8, vw - w - 8))
                below, above = vh - r.bottom() - 12, r.top() - 12
                if h + 8 <= below:
                    y = r.bottom() + 8
                elif h + 8 <= above:
                    y = r.top() - 8 - h
                else:
                    y = min(r.bottom() + 8, vh - h - 8)
                y = max(y, 8)
                p.fillRect(QRectF(x - 3, y - 3, w + 6, h + 6), ACCENT)
                p.drawPixmap(QPointF(x, y), pix)
                if self.invert:
                    self._invert_rect(p, QRectF(x, y, w, h))

        # status line
        txt = f" {self.current_page() + 1}/{self.n}  {int(self.zoom * 100)}% "
        if self.num:
            txt += f" :{self.num} "
        if self.sel_active and link is not None:
            kind = f" {self.preview_kind}" if self.preview_kind else ""
            txt += f" link {self.sel + 1}/{len(self._links)} -> p.{link.dpage + 1}{kind} "
        p.setFont(QFont("monospace", 10))
        w = p.fontMetrics().horizontalAdvance(txt) + 8
        bar = QRectF(0, vh - 22, w, 22)
        p.fillRect(bar, QColor(0, 0, 0, 180))
        p.setPen(QColor(230, 230, 230))
        p.drawText(bar, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, txt)

    # ---------------------------------------------------------- navigation
    def scroll_by(self, dx, dy):
        self.sx += dx
        self.sy += dy
        self.clamp()
        self.update()

    def push_history(self):
        self.history.append((self.zoom, self.sx, self.sy))
        del self.history[:-100]

    def go_back(self):
        if not self.history:
            return
        z, sx, sy = self.history.pop()
        if abs(z - self.zoom) > 1e-6:
            self.fit = None
            self.zoom = z
            self.relayout()
        self.sx, self.sy = sx, sy
        self.close_preview()
        self.clamp()
        self.update()

    def close_preview(self):
        self.sel_active = False
        self.preview = None
        self.preview_kind = ""

    def goto_page(self, p, push=True):
        p = min(max(p, 0), self.n - 1)
        if push:
            self.push_history()
        self.close_preview()
        self.sy = self.tops[p]
        self.clamp()
        self.update()

    def page_top(self):
        self.sy = self.tops[self.current_page()]
        self.clamp()
        self.update()

    def page_bottom(self):
        i = self.current_page()
        self.sy = self.tops[i] + self.sizes[i][1] * self.zoom - self.height()
        self.clamp()
        self.update()

    def feed_digit(self, d):
        buf = self.num + d
        if int(buf) > self.n:  # can't be a valid page: flush old, start over
            self.commit_number()
            buf = d
        if int(buf) == 0:
            self.num = ""
            self.num_timer.stop()
            self.update()
            return
        self.num = buf
        if int(buf) * 10 > self.n:  # no longer digit could still be valid
            self.commit_number()
        else:
            self.num_timer.start(NUM_TIMEOUT_MS)
        self.update()

    def commit_number(self):
        self.num_timer.stop()
        if self.num:
            n = int(self.num)
            self.num = ""
            self.goto_page(n - 1)
        self.update()

    # --------------------------------------------------------------- links
    def link_visible(self, i):
        r = self.link_view_rect(self.links[i])
        return (
            r.bottom() > 0 and r.top() < self.height() and r.right() > 0 and r.left() < self.width()
        )

    def entry_link(self, d):
        """Pick the link to start cycling from when nothing sensible is selected."""
        lo, hi = self.sy, self.sy + self.height()
        if d > 0:
            for i, L in enumerate(self.links):
                if self.tops[L.page] + L.rect.y1 * self.zoom >= lo:
                    return i
            return 0
        for i in range(len(self.links) - 1, -1, -1):
            L = self.links[i]
            if self.tops[L.page] + L.rect.y0 * self.zoom <= hi:
                return i
        return len(self.links) - 1

    def cycle(self, d):
        if not self.links:
            return
        if self.sel >= 0 and self.link_visible(self.sel):
            i = (self.sel + d) % len(self.links)
        else:
            i = self.entry_link(d)
        self.sel = i
        self.sel_active = True
        L = self.links[i]
        self.build_preview(L)
        self.ensure_visible(L)
        self.update()

    def ensure_visible(self, L):
        vh, vw = self.height(), self.width()
        r = self.link_view_rect(L)
        if r.top() < 0.06 * vh or r.bottom() > 0.94 * vh:
            self.sy += r.top() - 0.3 * vh
            self.clamp()
            r = self.link_view_rect(L)
        if r.left() < 0 or r.right() > vw:
            self.sx += r.center().x() - vw / 2
            self.clamp()
            r = self.link_view_rect(L)
        if self.preview is not None:
            need = self.preview[2] + 14
            if need > vh - r.bottom() and need > r.top():
                self.sy += r.top() - 0.08 * vh
                self.clamp()

    def follow(self, i):
        L = self.links[i]
        self.push_history()
        self.close_preview()
        h = self.sizes[L.dpage][1]
        y = min(max(L.dest.y, 0), h)
        self.sy = self.tops[L.dpage] + y * self.zoom - 0.2 * self.height()
        self.clamp()
        self.update()

    # ------------------------------------------------------ preview content
    def lines_of(self, pno):
        """[(Rect, text)] for every text line on a page (cached)."""
        if pno not in self._lines:
            out, flags = [], []
            for b in self.doc[pno].get_text("dict")["blocks"]:
                if b.get("type") != 0:
                    continue
                for ln in b["lines"]:
                    t = "".join(s["text"] for s in ln["spans"]).strip()
                    if t:
                        out.append((fitz.Rect(ln["bbox"]), t))
                        flags.append(
                            any(MATH_FONT_RE.search(s.get("font", "")) for s in ln["spans"])
                            or any(
                                c in MATH_CHARS
                                or "\u0370" <= c <= "\u03ff"
                                or "\uf000" <= c <= "\uf8ff"
                                for c in t
                            )
                        )
            self._lines[pno] = out
            self._mathflag[pno] = flags
        return self._lines[pno]

    def refs_start(self):
        """(page, y) of the last 'References' heading in the document, or None."""
        if not self._refs_done:
            self._refs_done = True
            for pno in range(self.n - 1, -1, -1):
                hits = [(r.y0, r.x0) for r, t in self.lines_of(pno) if REFS_RE.match(t)]
                if hits:
                    y, x = max(hits)
                    self._refs = (pno, y, x)
                    break
        return self._refs

    def in_refs(self, pno, x, y):
        """True if (x, y) on page pno lies after the 'References' heading (column-aware)."""
        refs = self.refs_start()
        if not refs:
            return False
        if pno != refs[0]:
            return pno > refs[0]
        c, cr = self.column(pno, x), self.column(pno, refs[2])
        if c == cr:
            return y >= refs[1] - 2
        return c[0] > cr[0]  # a later column on the same page

    def _page_layout(self, pno):
        """'two' / 'one' / None (too little text to tell).

        A two-column page has long lines on both sides of the gutter and (almost) none crossing it;
        a one-column page has body lines that all cross the middle.  Counting *short* fragments
        instead (as math-heavy one-column pages are full of them) gives false positives."""
        W = self.doc[pno].rect.width
        long_ = [r for r, _ in self.lines_of(pno) if r.width >= 0.25 * W]
        if len(long_) < 10:
            return None
        left = [r for r in long_ if r.x1 <= 0.55 * W]
        right = [r for r in long_ if r.x0 >= 0.45 * W]
        cross = len(long_) - len(left) - len(right)
        return "two" if len(left) >= 5 and len(right) >= 5 and cross < 0.3 * len(long_) else "one"

    def _doc_two_column(self):
        if not hasattr(self, "_two"):
            votes = [self._page_layout(p) for p in range(0, self.n, max(1, self.n // 12))]
            votes = [v for v in votes if v]
            self._two = votes.count("two") * 2 > len(votes)
        return self._two

    def columns(self, pno):
        """[(x0, x1), ...] text columns of a page (two for two-column papers), cached.

        Edges are percentiles over the *long* lines only, so a centred page number, a title or a
        short heading cannot drag a column edge across the gutter."""
        if pno not in self._cols:
            W = self.doc[pno].rect.width
            rs = [r for r, _ in self.lines_of(pno)]
            cols = [(0.0, W)]

            def edges(grp):
                long_ = [r for r in grp if r.width >= 0.2 * W] or grp
                xs0 = sorted(r.x0 for r in long_)
                xs1 = sorted(r.x1 for r in long_)
                return xs0[int(0.1 * (len(xs0) - 1))], xs1[int(round(0.9 * (len(xs1) - 1)))]

            if rs:
                layout = self._page_layout(pno) or ("two" if self._doc_two_column() else "one")
                cols = [edges(rs)]
                if layout == "two":
                    left = [r for r in rs if r.x1 <= 0.55 * W]
                    right = [r for r in rs if r.x0 >= 0.45 * W]
                    if left and right:
                        lcol, r_ = edges(left), edges(right)
                        if lcol[1] < r_[0]:
                            cols = [lcol, r_]
            self._cols[pno] = cols
        return self._cols[pno]

    def column(self, pno, x):
        """x-range of the text column containing x (handles two-column papers)."""
        cols = self.columns(pno)
        if len(cols) == 1:
            return cols[0]
        return cols[0] if x < (cols[0][1] + cols[1][0]) / 2 else cols[1]

    def near_line(self, pno, d, cx0, cx1):
        """First text line in the column whose centre lies below the anchor."""
        col = [(r, t) for r, t in self.lines_of(pno) if r.x0 >= cx0 - 4 and r.x1 <= cx1 + 4]
        col.sort(key=lambda a: (a[0].y0, a[0].x0))
        for r, t in col:
            if (r.y0 + r.y1) / 2 > d.y + 1:
                return r, t
        return None, ""

    def classify(self, L, cx0, cx1):
        d, t = L.dest, L.text.lower()
        nk = name_kind(L.name)
        if nk:
            return nk
        if self.in_refs(L.dpage, d.x, d.y):
            return "cite"
        near_r, near_t = self.near_line(L.dpage, d, cx0, cx1)
        if near_r is not None and re.match(r"^\s*\[\d+\]", near_t):
            return "cite"
        if re.search(r"fig|table|tab\.|algorithm", t) or self.find_caption(L.dpage, d, 40):
            return "float"
        if re.search(r"\beqs?\b|equation|^\(\s*\d", t):
            return "eq"
        for r, tx in self.lines_of(L.dpage):
            if d.y - 6 <= r.y0 <= d.y + EQ_BELOW and r.x1 >= cx1 - 30 and EQNUM_RE.search(tx):
                return "eq"
        if re.fullmatch(r"\[[\d,\s\-–]+\]", t) or "et al" in t:
            return "cite"
        return "generic"

    def find_caption(self, pno, d, tol):
        best = None
        for r, t in self.lines_of(pno):
            if CAP_RE.match(t) and d.y - tol <= r.y0 <= d.y + max(tol, 520):
                if tol < 520 and abs(r.y0 - d.y) > tol:
                    continue
                if best is None or abs(r.y0 - d.y) < abs(best.y0 - d.y):
                    best = r
        return best

    @staticmethod
    def cite_label(L):
        """'[12]' / '[2,' / '3].' -> '12' / '2' / '3'; None for author-year links."""
        m = CITE_NUM_RE.match(L.text)
        return m.group(1) if m else None

    def cite_span(self, pno, d, cx0, cx1, label=None):
        col = [(r, t) for r, t in self.lines_of(pno) if r.x0 >= cx0 - 4 and r.x1 <= cx1 + 4]
        col.sort(key=lambda a: (a[0].y0, a[0].x0))
        start = next((i for i, (r, _) in enumerate(col) if (r.y0 + r.y1) / 2 > d.y + 1), None)
        if label:
            # The anchor sits a little above its entry, but exactly where depends on the class file.
            # If the entry we landed on does not carry the number we followed, trust the number.
            lab = re.escape(label)
            pat = re.compile(rf"^\s*(?:\[{lab}\]|\({lab}\)|{lab}[.)]\s)")
            if start is None or not pat.match(col[start][1]):
                # never "correct" onto a numbered section heading: only accept entries in the reference list
                cand = [
                    i
                    for i, (r, t) in enumerate(col)
                    if pat.match(t)
                    and abs(r.y0 - d.y) < 160
                    and (self.in_refs(pno, r.x0, r.y0) or t.lstrip().startswith("["))
                ]
                if cand:
                    start = min(cand, key=lambda i: abs(col[i][0].y0 - d.y))
        if start is None:
            return d.y - 4, d.y + 70
        rows = []
        for r, t in col[start:]:
            if rows and abs(r.y0 - rows[-1]["y0"]) < 3:
                rows[-1]["r"] = _union(rows[-1]["r"], r)
                rows[-1]["t"] += " " + t
                rows[-1]["x0"] = min(rows[-1]["x0"], r.x0)
            else:
                rows.append({"y0": r.y0, "r": fitz.Rect(r), "t": t, "x0": r.x0})
            if len(rows) > 12:
                break
        first = rows[0]
        lh = max(first["r"].height, 6.0)
        hanging = len(rows) > 1 and rows[1]["x0"] > first["x0"] + 3
        end = first["r"].y1
        for i, row in enumerate(rows[1:], 1):
            if row["r"].y0 - end > 0.9 * lh:
                break
            if LABEL_RE.match(row["t"]):
                break
            if hanging and row["x0"] <= first["x0"] + 1.5:
                break
            end = row["r"].y1
            if i >= 7:
                break
        return first["r"].y0 - 3, end + 3

    def float_rect(self, pno, d):
        """Rect of the figure/table whose caption is near the anchor, or None."""
        page = self.doc[pno]
        P = page.rect
        cap = self.find_caption(pno, d, 40) or self.find_caption(pno, d, 520)
        if cap is None:
            return None
        lines = self.lines_of(pno)
        lh = max(cap.height, 6.0)
        region = fitz.Rect(cap)
        for r, _ in sorted(lines, key=lambda a: a[0].y0):
            if (
                r.y0 > region.y1 - 0.5
                and r.y0 - region.y1 < 0.6 * lh
                and min(r.x1, region.x1) - max(r.x0, region.x0) > 0.5 * min(r.width, region.width)
                and region.height < 12 * lh
            ):
                region = _union(region, r)
        cap_rect = fitz.Rect(region)

        gr = []
        with contextlib.suppress(Exception):
            gr += [fitz.Rect(im["bbox"]) for im in page.get_image_info()]
        with contextlib.suppress(Exception):
            gr += [fitz.Rect(dr["rect"]) for dr in page.get_drawings()]
        gr = [g for g in gr if not (g.width > 0.95 * P.width and g.height > 0.8 * P.height)]

        def touches(g, reg):
            ox = min(g.x1, reg.x1) - max(g.x0, reg.x0)
            if ox < 0.2 * min(max(g.width, 1.0), reg.width):
                return False
            return max(g.y0 - reg.y1, reg.y0 - g.y1, 0) <= 40

        used, changed = set(), True
        while changed:
            changed = False
            for i, g in enumerate(gr):
                if i not in used and touches(g, region):
                    region = _union(region, g)
                    used.add(i)
                    changed = True

        if not used:  # nothing graphical found: guess by caption type
            first = next((t for r, t in lines if abs(r.y0 - cap.y0) < 0.5), "")
            if re.match(r"^\s*tab", first, re.I):
                region = fitz.Rect(cap_rect.x0, cap_rect.y0 - 6, cap_rect.x1, cap_rect.y1 + 160)
            else:
                region = fitz.Rect(cap_rect.x0, cap_rect.y0 - 260, cap_rect.x1, cap_rect.y1 + 6)

        region = fitz.Rect(region.x0 - 8, region.y0 - 10, region.x1 + 8, region.y1 + 6)
        if region.height > FLOAT_MAX_H:
            region.y0 = (
                region.y1 - FLOAT_MAX_H if cap.y0 > (region.y0 + region.y1) / 2 else region.y0
            )
            region.y1 = min(region.y1, region.y0 + FLOAT_MAX_H)
        region.intersect(P)
        return region

    @staticmethod
    def eq_label(L):
        """'(4)' / 'Eq. 4' / '2.1.' -> '4' / '4' / '2.1' (the number printed next to the equation)."""
        m = LINK_NUM_RE.search(L.text)
        return m.group(0) if m else None

    def eq_clip(self, L, cx0, cx1):
        """Rect of the displayed equation a link points at, or None if it cannot be found.

        Strategy: find the equation number "(N)" at the right margin that belongs to the link
        (matching the number in the link text if there is one, else the closest to the anchor),
        then grow the region up and down over neighbouring math rows until we hit a body-text
        line, a gap that is too large, or another equation's number.
        """
        lines = self.lines_of(L.dpage)
        if not lines:
            return None
        spans = [
            (cx0, cx1),
            (min(r.x0 for r, _ in lines), max(r.x1 for r, _ in lines)),
        ]  # column, then page
        for n, (x0, x1) in enumerate(spans):
            clip = self._eq_in_span(L, x0, x1, strict=bool(n))
            if clip is not None:
                return clip
        return None

    def _eq_in_span(self, L, x0, x1, strict=False):
        d, label = L.dest, self.eq_label(L)
        lines = self.lines_of(L.dpage)
        flags = self._mathflag[L.dpage]
        col = [
            (r, t, flags[i]) for i, (r, t) in enumerate(lines) if r.x0 >= x0 - 4 and r.x1 <= x1 + 4
        ]
        col.sort(key=lambda a: (a[0].y0, a[0].x0))
        if not col:
            return None
        lh = statistics.median(r.height for r, _, _ in col)

        tags = []  # (rect, "3") for every equation number in the span
        for r, t, _ in col:
            ts = t.strip()
            if r.x1 < x1 - 40:  # equation numbers are flush right
                continue
            if TAG_RE.match(ts) or (
                EQNUM_RE.search(ts) and len(re.findall(r"[A-Za-z]{3,}", ts)) < 4
            ):
                m = TAG_NUM_RE.search(ts)
                tags.append((r, m.group(1) if m else ""))

        def dy(r):  # the anchor sits ~one baselineskip above the equation
            return abs((r.y0 + r.y1) / 2 - d.y - 12)

        if strict:  # whole-page pass (display spanning both columns)
            cand = [(r, n) for r, n in tags if label and n == label and dy(r) < 40]
        else:
            near = [(r, n) for r, n in tags if abs((r.y0 + r.y1) / 2 - d.y) < 250]
            cand = [(r, n) for r, n in near if label and n == label] or [
                (r, n) for r, n in near if -30 <= (r.y0 + r.y1) / 2 - d.y <= 150
            ]
        if not cand:
            return None
        tag = min(cand, key=lambda a: dy(a[0]))[0]

        rows = []  # [union rect, has_tag, text, has_math]
        for r, t, m in col:
            if rows and min(rows[-1][0].y1, r.y1) - max(rows[-1][0].y0, r.y0) > 0.3 * min(
                rows[-1][0].height, r.height
            ):
                rows[-1][0] = _union(rows[-1][0], r)
                rows[-1][2] += " " + t
                rows[-1][3] = rows[-1][3] or m
            else:
                rows.append([fitz.Rect(r), False, t, m])
        ti = None
        for i, row in enumerate(rows):
            for r, _ in tags:
                if row[0].y0 - 1 <= (r.y0 + r.y1) / 2 <= row[0].y1 + 1:
                    row[1] = True
            if row[0].y0 - 1 <= (tag.y0 + tag.y1) / 2 <= row[0].y1 + 1:
                ti = i
        if ti is None:
            return None

        def prose(row):
            """Running text rather than math.  TeX sets the line before a display flush with a
            much smaller gap when it is short, so spacing alone cannot be trusted."""
            if len(re.findall(r"[A-Za-z]{3,}", row[2])) >= 5:
                return True
            return not row[3] and row[0].x0 <= x0 + 2  # flush-left and no math font

        thr = 1.0 * lh
        lo = hi = ti
        while (
            lo > 0
            and rows[lo][0].y0 - rows[lo - 1][0].y1 <= thr
            and not rows[lo - 1][1]
            and not prose(rows[lo - 1])
        ):
            lo -= 1
        while (
            hi < len(rows) - 1
            and rows[hi + 1][0].y0 - rows[hi][0].y1 <= thr
            and not rows[hi + 1][1]
            and not prose(rows[hi + 1])
        ):
            hi += 1
        reg = rows[lo][0]
        for row in rows[lo + 1 : hi + 1]:
            reg = _union(reg, row[0])
        y0, y1 = max(reg.y0 - 3, tag.y0 - 150), min(reg.y1 + 3, tag.y1 + 150)
        if lo > 0:  # do not crop into the neighbouring text line
            y0 = max(y0, rows[lo - 1][0].y1 + 0.5)
        if hi < len(rows) - 1:
            y1 = min(y1, rows[hi + 1][0].y0 - 0.5)
        return fitz.Rect(min(x0, reg.x0) - 6, y0, max(x1, reg.x1) + 6, y1)

    def compute_clip(self, L):
        """-> (clip rect on the destination page, kind of destination)."""
        P = self.doc[L.dpage].rect
        d = L.dest
        cx0, cx1 = self.column(L.dpage, d.x)
        kind = self.classify(L, cx0, cx1)
        clip = None
        if kind == "cite":
            y0, y1 = self.cite_span(L.dpage, d, cx0, cx1, self.cite_label(L))
        elif kind == "eq":
            clip = self.eq_clip(L, cx0, cx1)
            y0, y1 = d.y - EQ_ABOVE, d.y + EQ_BELOW
        else:
            y0, y1 = d.y - GENERIC_ABOVE, d.y + GENERIC_BELOW
        if clip is None:
            clip = fitz.Rect(cx0 - 6, y0, cx1 + 6, y1)
        if kind == "float":
            fr = self.float_rect(L.dpage, d)
            if fr is not None and not fr.is_empty:
                clip = fr
        clip.intersect(P)
        if clip.is_empty or clip.height < 12 or clip.width < 12:
            clip = fitz.Rect(P.x0, max(d.y - 20, 0), P.x1, min(d.y + 150, P.y1))
        return clip, kind

    def build_preview(self, L):
        try:
            clip, self.preview_kind = self.compute_clip(L)
            dpr = self.devicePixelRatioF()
            s = max(self.zoom, PREVIEW_MIN_SCALE)
            s = min(s, self.width() * 0.92 / clip.width, self.height() * 0.65 / clip.height)
            s = max(s, 0.4)
            pix = self.doc[L.dpage].get_pixmap(
                matrix=fitz.Matrix(s * dpr, s * dpr), clip=clip, alpha=False
            )
            img = QImage(
                pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888
            ).copy()
            qp = QPixmap.fromImage(img)
            qp.setDevicePixelRatio(dpr)
            self.preview = (qp, pix.width / dpr, pix.height / dpr)
        except Exception as ex:  # never crash the viewer over a preview
            print(f"preview failed: {ex!r}", file=sys.stderr)
            self.preview = None

    # -------------------------------------------------------------- input
    def wheelEvent(self, e):
        d = e.angleDelta()
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.fit = None
            self.set_zoom(self.zoom * (ZOOM_STEP if d.y() > 0 else 1 / ZOOM_STEP))
        else:
            self.scroll_by(-d.x() * 0.6, -d.y() * 0.6)

    def keyPressEvent(self, e):
        k, m, t = e.key(), e.modifiers(), e.text()
        K = Qt.Key
        ctrl = bool(m & Qt.KeyboardModifier.ControlModifier)
        shift = bool(m & Qt.KeyboardModifier.ShiftModifier)
        vh = self.height()

        if ctrl:
            if k == K.Key_D:
                self.scroll_by(0, vh / 2)
            elif k == K.Key_U:
                self.scroll_by(0, -vh / 2)
            elif k == K.Key_O:
                self.go_back()
            elif k == K.Key_Q:
                self.close()
            return

        if len(t) == 1 and t in "0123456789":
            self.feed_digit(t)
            return
        if self.num and k not in (K.Key_Escape, K.Key_Return, K.Key_Enter):
            self.commit_number()

        if k in (K.Key_Return, K.Key_Enter):
            if self.num:
                self.commit_number()
            elif self.sel_active:
                self.follow(self.sel)
        elif k == K.Key_Escape:
            if self.num:
                self.num = ""
                self.num_timer.stop()
            else:
                self.close_preview()
            self.update()
        elif k == K.Key_Backspace:
            self.go_back()
        elif k in (K.Key_Space, K.Key_PageDown):
            self.scroll_by(0, vh * 0.9)
        elif k == K.Key_PageUp:
            self.scroll_by(0, -vh * 0.9)
        elif k == K.Key_Tab:
            self.cycle(1)
        elif k == K.Key_Backtab:
            self.cycle(-1)
        elif t == "?" or k == K.Key_Question:
            self.cycle(-1)
        elif t == "/" or k == K.Key_Slash:
            self.cycle(-1 if shift else 1)
        elif t == "j":
            self.scroll_by(0, STEP)
        elif t == "k":
            self.scroll_by(0, -STEP)
        elif t == "h":
            self.scroll_by(-STEP, 0)
        elif t == "l":
            self.scroll_by(STEP, 0)
        elif t == "w":
            self.fit = "w"
            self.apply_fit()
        elif t == "s":
            self.fit = "s"
            self.apply_fit()
        elif t == "t":
            self.page_top()
        elif t == "b":
            self.page_bottom()
        elif t == "T":
            self.goto_page(0)
        elif t == "B":
            self.goto_page(self.n - 1)
            self.page_bottom()
        elif t == "J":
            self.goto_page(self.current_page() + 1, push=False)
        elif t == "K":
            self.goto_page(self.current_page() - 1, push=False)
        elif t in ("+", "="):
            self.fit = None
            self.set_zoom(self.zoom * ZOOM_STEP)
        elif t == "-":
            self.fit = None
            self.set_zoom(self.zoom / ZOOM_STEP)
        elif t == "i":
            self.invert = not self.invert
            self.update()
        elif t == "q":
            self.close()


def main():
    args = sys.argv[1:]
    if args in (["-V"], ["--version"]):
        from importlib.metadata import PackageNotFoundError, version

        try:
            print(f"kpdf {version('kpdf')}")
        except PackageNotFoundError:
            print("kpdf (not installed)")
        return
    if len(args) != 1 or args[0] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0 if args else 1)
    path = os.path.expanduser(args[0])
    if not os.path.isfile(path):
        sys.exit(f"kpdf: no such file: {args[0]}")
    app = QApplication(sys.argv[:1])
    try:
        v = Viewer(path)
    except Exception as ex:
        sys.exit(f"kpdf: cannot open {args[0]}: {ex}")
    v.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
