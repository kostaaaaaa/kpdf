# kpdf

A small, keyboard-driven PDF viewer. Press `/` or `?` to cycle through a document's internal links
(citations, figures, tables, equations, sections) and get an instant preview of the destination
without leaving the page you are reading.

Built with [PyMuPDF](https://pymupdf.readthedocs.io/) and [PyQt6](https://www.riverbankcomputing.com/software/pyqt/).

## Install

Install it once as an isolated tool; no virtualenv to activate, and `kpdf` works from any directory:

```sh
# straight from GitHub
uv tool install git+https://github.com/kostaaaaaa/kpdf
# or: pipx install git+https://github.com/kostaaaaaa/kpdf

kpdf paper.pdf
```

On Arch Linux: `sudo pacman -S uv` (or `python-pipx`), then make sure `~/.local/bin` is on your `PATH`
(fish: `fish_add_path ~/.local/bin`).

Requires Python 3.12 or newer.

### Navigation

| Key | Action |
| --- | --- |
| `h` `j` `k` `l` | scroll left / down / up / right |
| `J` / `K` | next / previous page |
| `t` / `b` | top / bottom of the current page |
| `T` / `B` | top of first / bottom of last page |
| `<number>` | jump to that page (`Enter` jumps now) |
| `Ctrl-d` / `Ctrl-u` | half screen down / up |
| `Space` / `PageDown` / `PageUp` | screen down / up |
| `Backspace` / `Ctrl-o` | go back (after a link, search or jump) |

### View

| Key | Action |
| --- | --- |
| `w` / `s` | fit width / fit height |
| `+` / `-` | zoom in / out |
| `i` | invert colours |

### Links

| Key | Action |
| --- | --- |
| `/` `?` | cycle forward / backward through links, with a preview |
| `Tab` / `Shift-Tab` | same as `/` and `?` |
| `Enter` | follow the selected link |
| `Esc` | close the preview |

### Search

| Key | Action |
| --- | --- |
| `f` | open the search box; `Enter` runs it |
| `n` / `N` | next / previous match |
| `Esc` | leave the search |

### Presentation

| Key | Action |
| --- | --- |
| `p` | toggle presentation mode (fullscreen, one slide at a time) |
| `j` `l` `J` `Space` | next slide |
| `k` `h` `K` `PageUp` | previous slide |
| `w` `s` `+` `-` | locked while presenting: the size never changes |

### Files

| Key | Action |
| --- | --- |
| `Ctrl-\` | show / hide the PDF hotbar; `h` `j` `k` `l` select, `Enter` opens |

### Other

| Key | Action |
| --- | --- |
| `` ` `` | show / hide this help (`Esc` also closes it) |
| `q` | quit |
`kpdf --help` prints the same list; `kpdf --version` prints the installed version.

## Development

```sh
git clone https://github.com/kostaaaaaa/kpdf && cd kpdf
uv sync                    # creates .venv with the project (editable) and dev tools
uv run kpdf some.pdf       # run from the working tree
uv run pytest              # tests run headless (QT_QPA_PLATFORM=offscreen is set for you)
uv run ruff check .        # lint
uv run ruff format .       # format
uv run pre-commit install  # run ruff and basic checks on every commit
```

Test PDFs are generated on the fly in `tests/conftest.py`; please do not commit papers.

On Linux CI or a bare machine, Qt needs a few system libraries even when running headless:
`libegl1 libgl1 libopengl0 libxkbcommon0 libdbus-1-3 libfontconfig1`.

### Why PyMuPDF is pinned below 2

PyMuPDF 2.x imports an ONNX-based layout analysis stack whenever `pymupdf` is imported, which adds
roughly half a second to every launch and pulls in numpy and onnxruntime. kpdf does not use it, so
the dependency is `pymupdf>=1.23,<2` and `viewer.py` also blocks that import if 2.x ends up installed.
`tests/test_import_weight.py` guards against this regressing.

## License

AGPL-3.0-or-later; see [LICENSE](LICENSE). kpdf depends on PyQt6 (GPL) and PyMuPDF (AGPL), which
is why it is licensed this way. If you want different terms, both libraries offer commercial licenses.
