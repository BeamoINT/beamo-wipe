# SPDX-License-Identifier: GPL-3.0-or-later
"""Verified customer support destination. One source for text and QR.

Ownership: designated by the repo owner for backlog #105; no other
support domain exists in the project. The QR payload is this URL
only — never serials, paths, evidence, or session data.
"""

from __future__ import annotations

import functools

SUPPORT_SHORT = "beamosupport.com"
SUPPORT_URL = "https://" + SUPPORT_SHORT

_QR_BORDER = 4


def qr_payload() -> str:
    """Exact QR payload. Constant by construction: no sensitive data."""
    return SUPPORT_URL


def qr_error_correction() -> str:
    """Level H survives printed and screenshotted use."""
    return "H"


@functools.lru_cache(maxsize=4)
def qr_matrix(payload: str = SUPPORT_URL) -> tuple[tuple[bool, ...], ...]:
    """Deterministic dark-module matrix with a quiet-zone border."""
    import qrcode
    from qrcode.constants import ERROR_CORRECT_H

    code = qrcode.QRCode(
        error_correction=ERROR_CORRECT_H,
        border=_QR_BORDER,
    )
    code.add_data(payload)
    code.make(fit=True)
    return tuple(tuple(bool(cell) for cell in row) for row in code.get_matrix())


def qr_svg(payload: str = SUPPORT_URL) -> str:
    """Offline vector QR for gallery and REPORT.html. No scripts, no links."""
    matrix = qr_matrix(payload)
    size = len(matrix)
    rects = []
    for y, row in enumerate(matrix):
        for x, dark in enumerate(row):
            if dark:
                rects.append(f"<rect x=\"{x}\" y=\"{y}\" width=\"1\" height=\"1\"/>")
    # No xmlns: inline <svg> in parsed HTML inherits the SVG namespace, and
    # the namespace URI would trip the offline-token ban on report pages.
    return (
        f"<svg viewBox=\"0 0 {size} {size}\""
        f' role="img" aria-label="{SUPPORT_SHORT}">'
        f"<rect width=\"{size}\" height=\"{size}\" fill=\"#fff\"/>"
        f"<g fill=\"#000\">{''.join(rects)}</g></svg>"
    )
