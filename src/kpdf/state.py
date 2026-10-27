"""Resume positions: remember where you stopped reading each PDF.

Deliberately tiny. One text file, one line per PDF, three numbers each::

    <12 hex chars of hash(realpath)> <page> <fraction down that page> <"w" | "s" | zoom>

* A line is ~30 bytes whatever the length of the PDF, and the file is capped at ``MAX_ENTRIES``
  lines (least recently used are dropped), so it can never exceed ~15 KB.
* Nothing is kept in memory while reading: the file is read once on open and rewritten on close.
* Paths are hashed, so the file does not list the papers you have read.
* Every I/O problem is swallowed: remembering a position must never get in the way of reading.

Environment:
    KPDF_STATE_DIR=<dir>   store there instead of ``$XDG_STATE_HOME/kpdf`` (default ``~/.local/state/kpdf``).
                           Point it at ``$XDG_RUNTIME_DIR/kpdf`` for positions that are cleared at logout/reboot.
    KPDF_STATE_DIR=off     do not remember anything.
"""

import hashlib
import os
import tempfile
from pathlib import Path
from typing import NamedTuple

MAX_ENTRIES = 500


class Position(NamedTuple):
    page: int  # 0-based page under the middle of the window
    frac: float  # how far down that page the middle of the window is, 0..1
    fit: str  # "w" (fit width), "s" (fit height) or a zoom factor such as "1.350"


def state_file() -> Path | None:
    """Where positions are stored, or None when remembering is switched off."""
    env = os.environ.get("KPDF_STATE_DIR")
    if env is not None:
        if env.strip().lower() in ("", "off", "0", "none"):
            return None
        return Path(env) / "positions"
    base = os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state"
    return Path(base) / "kpdf" / "positions"


def _key(pdf_path: str) -> str:
    return hashlib.blake2b(os.fsencode(os.path.realpath(pdf_path)), digest_size=6).hexdigest()


def _parse(line: str) -> tuple[str, Position] | None:
    try:
        key, page, frac, fit = line.split()
        page, frac = int(page), float(frac)
        if len(key) != 12 or page < 0 or not 0.0 <= frac <= 1.0:
            return None
        if fit not in ("w", "s") and not 0.1 <= float(fit) <= 8.0:
            return None
        return key, Position(page, frac, fit)
    except ValueError:
        return None


def _read(path: Path) -> dict[str, Position]:
    entries: dict[str, Position] = {}
    try:
        with open(path, encoding="ascii", errors="replace") as f:
            for line in f:
                parsed = _parse(line)
                if parsed:
                    entries[parsed[0]] = parsed[1]
    except OSError:
        pass
    return entries


def load(pdf_path: str) -> Position | None:
    path = state_file()
    if path is None:
        return None
    return _read(path).get(_key(pdf_path))


def save(pdf_path: str, pos: Position) -> None:
    path = state_file()
    if path is None:
        return
    try:
        entries = _read(path)
        entries.pop(_key(pdf_path), None)  # re-insert so this PDF becomes the most recent
        entries[_key(pdf_path)] = pos
        newest = list(entries.items())[-MAX_ENTRIES:]
        text = "".join(f"{k} {p.page} {p.frac:.3f} {p.fit}\n" for k, p in newest)

        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # write-then-rename: a crash or a second kpdf closing at the same moment cannot corrupt it
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".positions-")
        try:
            with os.fdopen(fd, "w", encoding="ascii") as f:
                f.write(text)
            os.replace(tmp, path)
        except BaseException:
            os.unlink(tmp)
            raise
    except OSError:
        pass
