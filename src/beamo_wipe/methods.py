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

    @property
    def overwrite_passes(self) -> int:
        return {"prng": 1, "dodshort": 3, "zero": 1}[
            self.nwipe_method
        ] * self.rounds + (not self.noblank)

    @property
    def verification_passes(self) -> int:
        return {"off": 0, "last": 1, "all": self.overwrite_passes}[self.verify]

    @property
    def title(self) -> str:
        return {
            "prng": "Everyday",
            "dodshort": "Three overwrites",
            "zero": "Quick zero",
        }[self.nwipe_method]

    @property
    def overwrite_description(self) -> str:
        pattern = {
            "prng": "random data",
            "dodshort": "a pattern, its inverse, then random data",
            "zero": "zeros",
        }[self.nwipe_method]
        count = self.overwrite_passes
        return f"{count} overwrite {'pass' if count == 1 else 'passes'}: {pattern}."

    @property
    def verification_description(self) -> str:
        if self.verify == "off":
            return "Verification is not performed. No read-back pass."
        return f"{self.verification_passes} separate read-back verification pass after the final overwrite."

    @property
    def description(self) -> str:
        return f"{self.overwrite_description} {self.verification_description}"

    @property
    def summary(self) -> str:
        return f"{self.title}: {self.description}"

    @property
    def docs_name(self) -> str:
        return self.description



# Everyday default: one PRNG overwrite (nwipe's own default method family)
# plus a last-pass verify. No extra blanking pass. See docs/ADVANCED.md.
METHODS = {
    MethodId.EVERYDAY: NwipeMethodSpec(
        method_id=MethodId.EVERYDAY,
        nwipe_method="prng",
        rounds=1,
        verify="last",
        noblank=True,
    ),
    MethodId.EXTRA: NwipeMethodSpec(
        method_id=MethodId.EXTRA,
        nwipe_method="dodshort",
        rounds=1,
        verify="last",
        noblank=True,
    ),
    MethodId.QUICK_ZERO: NwipeMethodSpec(
        method_id=MethodId.QUICK_ZERO,
        nwipe_method="zero",
        rounds=1,
        verify="off",
        noblank=True,
    ),
}

DEFAULT_METHOD = MethodId.EVERYDAY

ALLOWED_NWIPE_METHODS = frozenset({"prng", "dodshort", "zero"})
ALLOWED_VERIFY = frozenset({"last", "off", "all"})
ALLOWED_ROUNDS = frozenset({1})
