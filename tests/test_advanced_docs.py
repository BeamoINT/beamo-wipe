# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path


def test_advanced_docs_name_default_method():
    text = (Path(__file__).resolve().parents[1] / "docs" / "ADVANCED.md").read_text(
        encoding="utf-8"
    )
    assert "--method=prng" in text
    assert "v0.42" in text
    assert "--force" in text  # documented as never passed
    assert "never `--force`" in text or "never --force" in text.lower()
