# SPDX-License-Identifier: GPL-3.0-or-later
"""Map the three user choices to nwipe flags. Never invent a new method."""

from __future__ import annotations

from dataclasses import dataclass

from beamo_wipe.models import MethodId


@dataclass(frozen=True)
class NwipeMethodSpec:
    method_id: MethodId
    nwipe_method: str
    rounds: int
    verify: str
    noblank: bool
    docs_name: str


# Everyday default: one PRNG overwrite (nwipe's own default method family)
# plus a last-pass verify. No extra blanking pass. See docs/ADVANCED.md.
METHODS = {
    MethodId.EVERYDAY: NwipeMethodSpec(
        method_id=MethodId.EVERYDAY,
        nwipe_method="prng",
        rounds=1,
        verify="last",
        noblank=True,
        docs_name="prng / one pass / verify last / no blank",
    ),
    MethodId.EXTRA: NwipeMethodSpec(
        method_id=MethodId.EXTRA,
        nwipe_method="dodshort",
        rounds=1,
        verify="last",
        noblank=True,
        docs_name="dodshort (3-pass) / verify last / no blank",
    ),
    MethodId.QUICK_ZERO: NwipeMethodSpec(
        method_id=MethodId.QUICK_ZERO,
        nwipe_method="zero",
        rounds=1,
        verify="off",
        noblank=True,
        docs_name="zero / verify off / no blank",
    ),
}

DEFAULT_METHOD = MethodId.EVERYDAY

ALLOWED_NWIPE_METHODS = frozenset({"prng", "dodshort", "zero"})
ALLOWED_VERIFY = frozenset({"last", "off", "all"})
ALLOWED_ROUNDS = frozenset({1})
