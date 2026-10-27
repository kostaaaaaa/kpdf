# kpdf

A small, keyboard-driven PDF viewer. Press `/` or `?` to cycle through a document's internal links
(citations, figures, tables, equations, sections) and get an instant preview of the destination
without leaving the page you are reading.

Built with [PyMuPDF](https://pymupdf.readthedocs.io/) and [PyQt6](https://www.riverbankcomputing.com/software/pyqt/).

## Install

Install it once as an isolated tool; no virtualenv to activate, and `kpdf` works from any directory:

```sh
# straight from GitHub
uv tool install git+https://github.com/<your-username>/kpdf
# or: pipx install git+https://github.com/<your-username>/kpdf

kpdf paper.pdf
```

On Arch Linux: `sudo pacman -S uv` (or `python-pipx`), then make sure `~/.local/bin` is on your `PATH`
(fish: `fish_add_path ~/.local/bin`).

Requires Python 3.12 or newer.

## Keys

| Key | Action |
| --- | --- |
| `h` `j` `k` `l` | scroll left / down / up / right |
| `w` / `s` | fit width / fit height |
| `t` / `b` | top / bottom of the current page |
| `T` / `B` | top of first page / bottom of last page |
| `<number>` | jump to that page (digits are buffered; `Enter` jumps now) |
| `J` / `K` | next / previous page |
| `Ctrl-d` / `Ctrl-u` | half-screen down / up |
| `Space` / `PageDown` / `PageUp` | screen down / up |
| `+` / `-` | zoom in / out |
| `/` and `?` (or `Tab` / `Shift-Tab`) | cycle forward / backward through internal links and preview the destination |
| `Esc` | close the preview (or cancel a half-typed page number) |
| `Enter` | follow the selected link |
| `Backspace` / `Ctrl-o` | go back to where you were before following a link or jumping |
| `i` | invert colours |
| `q` | quit |

`kpdf --help` prints the same list; `kpdf --version` prints the installed version.

## Development

```sh
git clone https://github.com/<your-username>/kpdf && cd kpdf
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

## Releasing

The version comes from the git tag (setuptools-scm), so there is nothing to edit:

1. Move the `Unreleased` entries in `CHANGELOG.md` under a new `## [x.y.z]` heading and merge to `main`.
2. `git tag vX.Y.Z && git push origin vX.Y.Z`

The `Release` workflow then builds the sdist and wheel, publishes to PyPI with trusted publishing
(no stored token) and creates a GitHub Release with generated notes.

Building from a source tarball that has no git metadata (for example an Arch `PKGBUILD`)? Set
`SETUPTOOLS_SCM_PRETEND_VERSION=<version>` in the build environment.

### One-time repository setup

* **PyPI:** add a [trusted publisher](https://docs.pypi.org/trusted-publishers/) for this repo with
  workflow `release.yml` and environment `pypi`. In GitHub, create an environment named `pypi`
  (optionally requiring your approval before each release).
* **Branch protection** (Settings > Rules) on `main`: require a pull request and the status checks
  `lint`, `test (3.12)`, `test (3.13)`, `build`; block force pushes.
* **Security** (Settings > Code security): enable Dependabot alerts, secret scanning, private
  vulnerability reporting and CodeQL "default setup" for Python.
* Replace `<your-username>` in this README and in `pyproject.toml`.

## License

AGPL-3.0-or-later; see [LICENSE](LICENSE). kpdf depends on PyQt6 (GPL) and PyMuPDF (AGPL), which
is why it is licensed this way. If you want different terms, both libraries offer commercial licenses.
