# Security policy

## Supported versions

Only the latest release receives fixes.

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting: open the repository's **Security** tab and
choose **Report a vulnerability**. Do not open a public issue for security problems.

## Notes

kpdf renders PDFs with MuPDF through PyMuPDF, so opening an untrusted PDF exposes the same attack
surface as any PDF viewer. Keep dependencies current (`uv lock --upgrade`, or merge Dependabot's
pull requests) and prefer reporting upstream issues in MuPDF/PyMuPDF to their maintainers.
