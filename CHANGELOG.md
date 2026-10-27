# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project
uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- `kpdf --version`.
- Test suite (link extraction, CLI, import-weight guards, offscreen key-driven smoke tests).
- GitHub Actions CI (lint, format check, tests on Python 3.12 and 3.13, build, dependency audit),
  trusted-publishing release workflow and Dependabot.

### Changed
- Requires Python 3.12 or newer.
- Source moved to a `src/kpdf/` package layout; the `kpdf` command is unchanged.
- Faster startup: the window now appears before internal links are scanned (links are collected
  page by page in idle time, and finished on demand if you navigate sooner), and each link looks up
  its text by vertical position instead of scanning every word on the page.
- `pymupdf` is pinned to `<2`, and the optional PyMuPDF 2.x layout import is blocked, which removes
  roughly 0.5 s of import time.
