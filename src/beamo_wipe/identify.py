# SPDX-License-Identifier: GPL-3.0-or-later
"""CLI: identify the live boot disk and print it. Fail closed."""

from __future__ import annotations

import sys

from beamo_wipe.discover import discover


def main(argv: list[str] | None = None) -> int:
    del argv
    result = discover()
    if not result.boot_identified or result.boot is None:
        from beamo_wipe.copy import IDENTIFY_ERROR

        print(result.error or IDENTIFY_ERROR, file=sys.stderr)
        return 2
    print(result.boot.path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
