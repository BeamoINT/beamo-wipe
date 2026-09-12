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


def test_advanced_docs_name_every_production_method():
    from beamo_wipe.methods import METHODS
    from beamo_wipe.models import MethodId

    text = (Path(__file__).resolve().parents[1] / "docs" / "ADVANCED.md").read_text(
        encoding="utf-8"
    )
    assert METHODS[MethodId.EVERYDAY].nwipe_method in text
    assert METHODS[MethodId.EXTRA].nwipe_method in text
    assert METHODS[MethodId.QUICK_ZERO].nwipe_method in text
    for flag in ("--verify=last", "--verify=off", "--rounds=1", "--noblank"):
        assert flag in text
    for flag in ("--autonuke", "--nogui", "--nowait", "--exclude=", "--logfile=", "--PDFreportpath=noPDF"):
        assert flag in text
