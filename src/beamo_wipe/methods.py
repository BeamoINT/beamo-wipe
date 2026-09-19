# SPDX-License-Identifier: GPL-3.0-or-later
"""Map the three user choices to nwipe flags. Never invent a new method."""

from __future__ import annotations

from dataclasses import dataclass

from beamo_wipe.models import MethodId


TITLE_PRNG = "Everyday"
TITLE_DODSHORT = "Three overwrites"
TITLE_ZERO = "Quick zero"
PATTERN_PRNG = "random data"
PATTERN_DODSHORT = "a pattern, its inverse, then random data"
PATTERN_ZERO = "zeros"
OVERWRITE_ONE = "{count} overwrite pass: {pattern}."
OVERWRITE_MANY = "{count} overwrite passes: {pattern}."
NO_VERIFY = "This method does not check the overwrite."
VERIFY_LAST = "Then we check the last overwrite."
VERIFY_N = "Then we check the overwrite {n} times."
OPERATION_ONE = "One overwrite"
OPERATION_THREE = "Three overwrites"
OPERATION_N = "{count} overwrites"
OPERATION_VERIFIED = "{overwrites}, followed by verification."
OPERATION_UNVERIFIED = "{overwrites}. Verification is not performed."
MARK_NO_CHECK = "No check"
MARK_MORE_OVERWRITES = "More overwrites"
EXTRA_WORK_DOD = (
    "Three times the overwrites of {everyday}. "
    "Extra passes do not reach hidden storage."
)
PLAIN_LEAD_PRNG = "Overwrite the disk, then check the result."
PLAIN_LEAD_DODSHORT = "Overwrite the disk three times, then check the result."
PLAIN_LEAD_ZERO = "Overwrite the disk with zeros. This does not check the result."


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
            "prng": TITLE_PRNG,
            "dodshort": TITLE_DODSHORT,
            "zero": TITLE_ZERO,
        }[self.nwipe_method]

    @property
    def plain_lead(self) -> str:
        """Novice sentence first. Exact overwrite/verify counts follow."""
        return {
            "prng": PLAIN_LEAD_PRNG,
            "dodshort": PLAIN_LEAD_DODSHORT,
            "zero": PLAIN_LEAD_ZERO,
        }[self.nwipe_method]

    @property
    def overwrite_description(self) -> str:
        pattern = {
            "prng": PATTERN_PRNG,
            "dodshort": PATTERN_DODSHORT,
            "zero": PATTERN_ZERO,
        }[self.nwipe_method]
        count = self.overwrite_passes
        template = OVERWRITE_ONE if count == 1 else OVERWRITE_MANY
        return template.format(count=count, pattern=pattern)

    @property
    def verification_description(self) -> str:
        if self.verify == "off":
            return NO_VERIFY
        n = self.verification_passes
        if n == 1:
            return VERIFY_LAST
        return VERIFY_N.format(n=n)

    @property
    def comparison_mark(self) -> str:
        """Short scan label for the method list. Everyday uses Recommended."""
        if self.verify == "off":
            return MARK_NO_CHECK
        if self.overwrite_passes > 1:
            return MARK_MORE_OVERWRITES
        return ""

    @property
    def extra_work(self) -> str:
        if self.overwrite_passes > 1:
            return EXTRA_WORK_DOD.format(everyday=TITLE_PRNG)
        return ""

    @property
    def description(self) -> str:
        return f"{self.overwrite_description} {self.verification_description}"

    @property
    def summary(self) -> str:
        return f"{self.title}: {self.description}"

    @property
    def operation_summary(self) -> str:
        """Last-chance line. Same overwrite/verify counts as argv and reports."""
        count = self.overwrite_passes
        names = {1: OPERATION_ONE, 3: OPERATION_THREE}
        overwrites = names.get(count, OPERATION_N.format(count=count))
        if self.verification_passes:
            return OPERATION_VERIFIED.format(overwrites=overwrites)
        return OPERATION_UNVERIFIED.format(overwrites=overwrites)

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
