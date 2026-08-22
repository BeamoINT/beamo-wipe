# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path

from beamo_wipe import copy
from beamo_wipe.gallery import gallery_html

FORBIDDEN = (
    "plug and play",
    "no technical skills",
    "military certified",
    "dod certified",
    "nsa certified",
    "blancco replacement",
    "impossible to recover",
    "we invented",
    "works on any computer",
    "works on any mac",
    "apple silicon",
)

ALLOWED_APPLE_SILICON_CONTEXT = "Not Apple Silicon"

HAPPY_PATH_JARGON = (
    "/dev/",
    "sysfs",
    "sanitize",
    "nwipe --",
    "ata/",
    "sata/nvme",
    "nvme",
)


def _read(rel: str) -> str:
    return (Path(__file__).resolve().parents[1] / rel).read_text(encoding="utf-8").lower()


def _happy_blob() -> str:
    return " ".join(
        [
            copy.SPLASH_TAGLINE,
            copy.WHAT_LEAD,
            " ".join(copy.WHAT_BULLETS),
            copy.OWNER_LEAD,
            copy.OWNER_CHECKBOX,
            copy.DONE_OK,
            copy.DONE_FAIL,
            copy.DONE_OK_PREVIEW,
            copy.DONE_FAIL_PREVIEW,
            copy.PREVIEW_BANNER,
            copy.SAME_SIZE_HINT,
            copy.NOT_LIVE_ERROR,
            copy.EMPTY_DISKS,
            copy.SSD_FOOTER,
            copy.IDENTIFY_ERROR,
            copy.pick_subtitle(),
            copy.CONFIRM_LEAD,
            copy.METHOD_LEAD,
            copy.LAST_LEAD,
            copy.TITLE_WHAT,
            copy.TITLE_OWNER,
            copy.TITLE_PICK,
            copy.TITLE_CONFIRM,
            copy.TITLE_METHOD,
            copy.TITLE_LAST,
            copy.TITLE_WORKING,
            copy.WORKING_PULSE,
            " ".join(card["blurb"] + " " + card["pace"] for card in copy.METHOD_CARDS.values()),
            copy.confirm_type_size("256"),
            copy.confirm_type_four("A111"),
            copy.confirm_type_chars("ABC"),
        ]
    ).lower()


def test_copy_module_has_no_forbidden_claims():
    blob = _happy_blob()
    blob += " " + copy.ENGINE_LINE.lower() + " " + copy.WHAT_MORE.lower()
    for phrase in FORBIDDEN:
        if phrase == "apple silicon":
            continue
        assert phrase not in blob
    assert "not apple silicon" in blob


def test_happy_path_copy_hides_jargon():
    blob = _happy_blob()
    for phrase in HAPPY_PATH_JARGON:
        assert phrase not in blob, phrase


def test_customer_copy_does_not_say_beamo_did_not_write():
    """Jack: drop the credit-deflecting sentence from every customer surface."""
    banned = ("did not write", "beamo did not", "not written by", "erasure engine")
    blob = " ".join(
        [
            _happy_blob(),
            copy.ENGINE_LINE.lower(),
            copy.WHAT_MORE.lower(),
            copy.SECURE_BOOT_HINT.lower(),
            " ".join(copy.WHAT_BULLETS).lower(),
        ]
    )
    for phrase in banned:
        assert phrase not in blob, phrase
    html = _read("helper/index.html") + " " + gallery_html().lower()
    for phrase in banned:
        assert phrase not in html, phrase


def test_what_screen_is_two_plain_bullets():
    assert len(copy.WHAT_BULLETS) == 2
    blob = " ".join(copy.WHAT_BULLETS).lower()
    assert "pick a disk" in blob
    assert "cannot get the files back" in blob
    assert "not apple silicon" in blob
    assert "nwipe" not in blob
    assert "warranty" not in blob
    assert "did not write" not in blob


def test_show_more_may_name_nwipe_but_not_deflect():
    assert "nwipe" in copy.ENGINE_LINE.lower()
    assert "did not write" not in copy.ENGINE_LINE.lower()
    assert "warranty" not in copy.ENGINE_LINE.lower()
    assert copy.SECURE_BOOT_HINT in copy.WHAT_MORE
    assert copy.ENGINE_LINE in copy.WHAT_MORE


def test_confirm_prompts_talk_like_a_person():
    size = copy.confirm_type_size("256")
    four = copy.confirm_type_four("3456")
    chars = copy.confirm_type_chars("sdb")
    for prompt in (size, four, chars):
        assert "so we know it is the right disk" in prompt
        assert "serial number" not in prompt.lower()
        assert "device name" not in prompt.lower()
    assert "4 characters" in four
    assert "256" in size


def test_splash_says_they_already_booted():
    text = copy.SPLASH_TAGLINE.lower()
    assert "already" in text
    assert "usb" in text
    assert "pick" in text


def test_claims_doc_forbids_bad_bullets():
    text = _read("docs/claims.md")
    assert "plug and play" in text  # listed as forbidden, not as a claim
    assert "not for apple silicon" in text or "not apple silicon" in text
    assert "guided" in text
    assert "nwipe" in text
