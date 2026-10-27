"""Everything the help screen says, as plain data.

One table feeds both the in-app overlay (backtick) and ``kpdf --help``, so they cannot drift apart;
``tests/test_helptext.py`` also checks that every key the viewer handles is listed here.
"""

from typing import NamedTuple

LOGO = [
    r"     _/\/\____/\/\__/\/\/\/\/\____/\/\/\/\/\____/\/\/\/\/\/\_",
    r"    _/\/\__/\/\____/\/\____/\/\__/\/\____/\/\__/\/\_________ ",
    r"   _/\/\/\/\______/\/\/\/\/\____/\/\____/\/\__/\/\/\/\/\___  ",
    r"  _/\/\__/\/\____/\/\__________/\/\____/\/\__/\/\_________   ",
    r" _/\/\____/\/\__/\/\__________/\/\/\/\/\____/\/\_________    ",
    r"________________________________________________________     ",
]
TAGLINE = "keyboard-driven PDF viewer"
USER = "@kostaaaaaa"
FOOTER = "` or Esc to close"

# (section, [(keys, what it does)]); keys are space-separated tokens, "/" meaning "or".
SECTIONS = [
    (
        "Navigation",
        [
            ("h j k l", "scroll left / down / up / right"),
            ("J / K", "next / previous page"),
            ("t / b", "top / bottom of the current page"),
            ("T / B", "top of first / bottom of last page"),
            ("<number>", "jump to that page (Enter jumps now)"),
            ("Ctrl-d / Ctrl-u", "half screen down / up"),
            ("Space / PageDown / PageUp", "screen down / up"),
            ("Backspace / Ctrl-o", "go back (after a link, search or jump)"),
        ],
    ),
    (
        "View",
        [
            ("w / s", "fit width / fit height"),
            ("+ / -", "zoom in / out"),
            ("i", "invert colours"),
        ],
    ),
    (
        "Links",
        [
            ("/ ?", "cycle forward / backward through links, with a preview"),
            ("Tab / Shift-Tab", "same as / and ?"),
            ("Enter", "follow the selected link"),
            ("Esc", "close the preview"),
        ],
    ),
    (
        "Search",
        [
            ("f", "open the search box; Enter runs it"),
            ("n / N", "next / previous match"),
            ("Esc", "leave the search"),
        ],
    ),
    (
        "Other",
        [
            ("`", "show / hide this help (Esc also closes it)"),
            ("q", "quit"),
        ],
    ),
]


def key_tokens() -> set[str]:
    """Every individual key named in the table (for the consistency test)."""
    return {tok for _, entries in SECTIONS for keys, _ in entries for tok in keys.split()}


def as_text() -> str:
    """The key list as plain text, for ``kpdf --help``."""
    width = max(len(k) for _, entries in SECTIONS for k, _ in entries)
    out = ["Keys"]
    for title, entries in SECTIONS:
        out.append(f"  {title}")
        out.extend(f"    {k:<{width}}  {d}" for k, d in entries)
    return "\n".join(out)


# ------------------------------------------------------------------ layout in characters
class Seg(NamedTuple):
    line: int
    col: int
    text: str
    role: str  # logo | tagline | title | key | desc | muted | user


def _rows(sections):
    rows = []
    for n, (title, entries) in enumerate(sections):
        if n:
            rows.append(("gap",))
        rows.append(("title", title))
        rows.extend(("entry", k, d) for k, d in entries)
    return rows


def _split():
    """Two columns of sections, as even as possible, keeping the order."""
    best = None
    for k in range(1, len(SECTIONS)):
        left, right = _rows(SECTIONS[:k]), _rows(SECTIONS[k:])
        score = max(len(left), len(right))
        if best is None or score < best[0]:
            best = (score, left, right)
    return best[1], best[2]


def _col_width(rows):
    ks = [len(r[1]) for r in rows if r[0] == "entry"]
    ds = [len(r[2]) for r in rows if r[0] == "entry"]
    return max(ks) + 2 + max(ds), max(ks)


def build() -> tuple[list[Seg], int, int]:
    """Place every piece of text on a character grid -> (segments, columns, lines)."""
    GAP = 4
    logo = [row.rstrip() for row in LOGO]
    logo_w = max(len(row) for row in logo)
    left, right = _split()
    (wl, kl), (wr, kr) = _col_width(left), _col_width(right)
    block_w = wl + GAP + wr
    inner = max(logo_w, block_w, len(FOOTER) + 2 + len(USER))

    segs: list[Seg] = []
    line = 0
    for row in logo:
        segs.append(Seg(line, (inner - logo_w) // 2, row, "logo"))
        line += 1
    line += 1
    segs.append(Seg(line, (inner - len(TAGLINE)) // 2, TAGLINE, "tagline"))
    line += 2

    x0 = (inner - block_w) // 2
    for rows, col0, kw in ((left, x0, kl), (right, x0 + wl + GAP, kr)):
        for i, row in enumerate(rows):
            if row[0] == "title":
                segs.append(Seg(line + i, col0, row[1], "title"))
            elif row[0] == "entry":
                segs.append(Seg(line + i, col0, row[1], "key"))
                segs.append(Seg(line + i, col0 + kw + 2, row[2], "desc"))
    line += max(len(left), len(right)) + 1

    segs.append(Seg(line, 0, FOOTER, "muted"))
    segs.append(Seg(line, inner - len(USER), USER, "user"))
    return segs, inner, line + 1
