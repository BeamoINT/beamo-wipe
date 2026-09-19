# SPDX-License-Identifier: GPL-3.0-or-later
"""Write a browser click-through of the wizard. Preview only — does not wipe."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

from beamo_wipe import copy as C
from beamo_wipe import storage_limits as limits
from beamo_wipe.support_contact import qr_svg as _support_qr_svg
from beamo_wipe.support_code import (
    code_for_export_detail,
    code_for_startup,
    public_build_id,
)
from beamo_wipe import support_export as _export
from beamo_wipe import inventory
from beamo_wipe.outcomes import preview_view
from beamo_wipe.recovery import (
    recovery_for_blocked,
    recovery_for_empty,
    recovery_for_outcome,
    recovery_for_view,
)
from beamo_wipe.demo import discovery_for_scenario
from beamo_wipe import keyboard as _keyboard
from beamo_wipe.keyboard import LAYOUT_ORDER
from beamo_wipe.lang import (
    LANGUAGE_NAMES,
    LANGUAGE_ORDER,
    current as current_language,
    is_supported,
    set_language,
)
from beamo_wipe.methods import METHODS
from beamo_wipe.models import MethodId
from beamo_wipe import progress as _progress
from beamo_wipe.power import PowerStatus
from beamo_wipe import identity as _identity
from beamo_wipe.safety import (
    SafetyError,
    confirm_spec,
    listed_disks,
    same_size_conflict,
)


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


_ASSETS = Path(__file__).resolve().parent / "assets"


def _mark_body() -> str:
    """The brand mark's inner artwork (path elements), whitespace-collapsed."""
    svg = (_ASSETS / "logo-mark.svg").read_text(encoding="utf-8")
    body = re.sub(r"^[\s\S]*?<svg[^>]*>", "", svg)
    body = re.sub(r"</svg>\s*$", "", body)
    return re.sub(r"\s+", " ", body).strip()


def _logo_svg(width: int, height: int) -> str:
    """The real Beamo mark as a one-line inline SVG sized for the template.

    Recolors the B to navy so the mark reads on the white wizard chrome.
    The favicon keeps the dark-surface (white B on a navy tile) treatment.
    """
    body = _mark_body().replace('fill="#FFFFFF"', 'fill="#0A1B34"')
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="128 162 264 221" aria-hidden="true">{body}</svg>'
    )


def _favicon_uri() -> str:
    """The mark on a navy tile, as a self-contained data-URI favicon."""
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
        '<rect width="64" height="64" rx="14" fill="#0A1B34"/>'
        '<g transform="translate(9 12.75) scale(0.1742) translate(-128 -162)">'
        + _mark_body()
        + "</g></svg>"
    )
    return "data:image/svg+xml," + quote(svg, safe="")


def _recovery_payload(sections) -> dict | None:
    if sections is None:
        return None
    return {
        "happened": sections.happened,
        "meaning": sections.meaning,
        "next": sections.next_step,
        "technical": sections.technical,
    }


def _disks_payload(scenario: str = "happy") -> list[dict]:
    result = discovery_for_scenario(scenario)  # type: ignore[arg-type]
    peers = listed_disks(result)
    eligible_paths = {disk.path for disk in result.selectable}
    out = []
    for disk in result.disks:
        spec = None
        if disk.path in eligible_paths:
            try:
                spec = confirm_spec(disk, peers)
            except SafetyError:
                spec = None
        view = _identity.present_disk(disk, peers, compare_serials=True)
        components = [
            {
                "heading": inventory.nested_heading(child),
                "reason": inventory.nested_reason_text(child),
            }
            for child in inventory.nested_under(disk.path, result.excluded)
        ]
        out.append(
            {
                "path": disk.path,
                "name": view.title,
                "size": view.capacity,
                "kind": disk.kind.value,
                "kindLabel": view.kind_chip,
                "storageNotice": limits.notice(disk.kind),
                "bus": view.connection,
                "serial": view.id_value,
                "markedSerial": view.marked_id,
                "comparisonNote": view.comparison_note,
                "idLabel": view.id_label,
                "connection": view.connection,
                "connectionNote": view.connection_note,
                "missingNote": view.missing_note,
                "ambiguousNote": view.ambiguous_note,
                "duplicateNote": view.duplicate_note,
                "announcement": view.announcement,
                "isBoot": disk.is_boot,
                "eligible": disk.path in eligible_paths,
                "token": spec.token if spec else "",
                "prompt": spec.prompt if spec else "",
                "warning": "" if disk.is_boot else C.confirm_warning(disk),
                "prepare": "" if disk.is_boot else C.prepare_selected(disk),
                "components": components,
                "contents": disk.contents,
                "eraseLabel": "" if disk.is_boot else C.erase_now_label(disk, peers),
            }
        )
    return out


def _serialize_progress(view: _progress.ProgressView) -> dict:
    """JSON for one ProgressView. Working preview never paints 100%."""
    from beamo_wipe.wizard import format_progress_percent

    percent = view.percent
    if percent is not None and percent >= 100.0:
        percent = None
        percent_text = ""
    elif percent is None:
        percent_text = ""
    elif view.percent_is_old:
        percent_text = f"{format_progress_percent(percent)} (old)"
    else:
        percent_text = format_progress_percent(percent)
    marked = None if view.mismatch else view.position
    return {
        "percent": percent,
        "percentText": percent_text,
        "percentIsOld": view.percent_is_old,
        "animate": view.animate,
        "timingText": view.timing_text,
        "statusText": view.status_text,
        "stepText": _progress.step_text(
            view.stages,
            view.position,
            view.mismatch,
            view.step_percent,
            view.percent_is_old,
        ),
        "sequence": (
            _progress.sequence_text(view.stages, marked).split("\n")
            if view.stages
            else []
        ),
        "phaseNote": _progress.phase_note(view.phase, view.mismatch),
        "staleBlock": _progress.stale_block(view.stale_for),
    }


def _progress_preview_payload() -> dict:
    """Canned ProgressView snapshots. Gallery must render these, not invent stages."""
    from beamo_wipe.nwipe_runner import _synthetic_observation

    everyday = _progress.plan_stages(
        METHODS[MethodId.EVERYDAY].overwrite_passes,
        bool(METHODS[MethodId.EVERYDAY].verification_passes),
    )
    extra = _progress.plan_stages(
        METHODS[MethodId.EXTRA].overwrite_passes,
        bool(METHODS[MethodId.EXTRA].verification_passes),
    )
    quick = _progress.plan_stages(
        METHODS[MethodId.QUICK_ZERO].overwrite_passes,
        bool(METHODS[MethodId.QUICK_ZERO].verification_passes),
    )

    def view(**kwargs: Any) -> _progress.ProgressView:
        base: dict[str, Any] = dict(
            phase="Writing",
            percent=42.0,
            elapsed=45.0,
            remaining=None,
            stale_for=None,
            percent_is_old=False,
            stages=everyday,
            position=0,
            mismatch=False,
            step_percent=42.0,
            estimate_state=_progress.ESTIMATE_EARLY,
        )
        base.update(kwargs)
        return _progress.ProgressView(
            phase=base["phase"],
            percent=base["percent"],
            elapsed=base["elapsed"],
            remaining=base["remaining"],
            stale_for=base["stale_for"],
            percent_is_old=base["percent_is_old"],
            stages=base["stages"],
            position=base["position"],
            mismatch=base["mismatch"],
            step_percent=base["step_percent"],
            estimate_state=base["estimate_state"],
        )

    writing_obs = _synthetic_observation(MethodId.EVERYDAY, 0.42, 42.0, 100.0)
    w_pos, w_mis = _progress.locate_stage(everyday, writing_obs)
    verifying_obs = _synthetic_observation(MethodId.EVERYDAY, 0.80, 80.0, 100.0)
    v_pos, v_mis = _progress.locate_stage(everyday, verifying_obs)
    extra_obs = _synthetic_observation(MethodId.EXTRA, 0.40, 40.0, 100.0)
    e_pos, e_mis = _progress.locate_stage(extra, extra_obs)
    bad = _progress.Observation(
        record="dry-run:mismatch",
        percent=50.0,
        phase="Verifying",
        counters=(1, 1, 1, 1),
        engine_eta=10,
        quantum=0.1,
    )
    m_pos, m_mis = _progress.locate_stage(quick, bad)

    states = {
        "preparing": _serialize_progress(
            view(
                phase="Preparing",
                percent=None,
                position=None,
                mismatch=False,
                step_percent=None,
                estimate_state=_progress.ESTIMATE_EARLY,
            )
        ),
        "writing": _serialize_progress(
            view(
                phase=writing_obs.phase,
                percent=42.0,
                position=w_pos,
                mismatch=w_mis,
                step_percent=None if w_pos is None or w_mis else writing_obs.percent,
                estimate_state=_progress.ESTIMATE_EARLY,
            )
        ),
        "stale": _serialize_progress(
            view(
                phase="Writing",
                percent=42.0,
                stale_for=12.0,
                percent_is_old=True,
                position=w_pos,
                mismatch=w_mis,
                step_percent=42.0,
                estimate_state=_progress.ESTIMATE_PAUSED,
            )
        ),
        "verifying": _serialize_progress(
            view(
                phase=verifying_obs.phase,
                percent=80.0,
                position=v_pos,
                mismatch=v_mis,
                step_percent=(
                    None if v_pos is None or v_mis else verifying_obs.percent
                ),
                estimate_state="",
            )
        ),
        "mismatch": _serialize_progress(
            view(
                phase="Verifying",
                percent=50.0,
                stages=quick,
                position=m_pos,
                mismatch=m_mis,
                step_percent=None,
                estimate_state="",
            )
        ),
        "stopping": _serialize_progress(
            view(
                phase="Stopping",
                percent=42.0,
                remaining=None,
                stale_for=None,
                percent_is_old=False,
                position=w_pos,
                mismatch=False,
                step_percent=42.0,
                estimate_state="",
            )
        ),
        "unknown": _serialize_progress(
            view(
                phase=_progress.PHASE_UNKNOWN,
                percent=None,
                position=None,
                mismatch=False,
                step_percent=None,
                estimate_state=_progress.ESTIMATE_NO_ETA,
            )
        ),
        "extra_writing": _serialize_progress(
            view(
                phase=extra_obs.phase,
                percent=40.0,
                stages=extra,
                position=e_pos,
                mismatch=e_mis,
                step_percent=None if e_pos is None or e_mis else extra_obs.percent,
                estimate_state=_progress.ESTIMATE_LAST_STEP,
            )
        ),
    }

    demo: dict[str, list] = {}
    for mid in (MethodId.EVERYDAY, MethodId.EXTRA, MethodId.QUICK_ZERO):
        spec = METHODS[mid]
        stages = _progress.plan_stages(
            spec.overwrite_passes, bool(spec.verification_passes)
        )
        frames = [
            {
                "frac": 0.0,
                "state": _serialize_progress(
                    view(
                        phase="Preparing",
                        percent=None,
                        stages=stages,
                        position=None,
                        mismatch=False,
                        step_percent=None,
                        estimate_state=_progress.ESTIMATE_EARLY,
                    )
                ),
            }
        ]
        for i in range(1, 13):
            frac = min(0.96, i * 0.08)
            pct = min(99.9, round(frac * 100.0, 1))
            obs = _synthetic_observation(mid, frac, pct, 100.0)
            pos, mis = _progress.locate_stage(stages, obs)
            frames.append(
                {
                    "frac": frac,
                    "state": _serialize_progress(
                        view(
                            phase=obs.phase,
                            percent=pct,
                            stages=stages,
                            position=pos,
                            mismatch=mis,
                            step_percent=None if pos is None or mis else obs.percent,
                            estimate_state=_progress.ESTIMATE_EARLY,
                        )
                    ),
                }
            )
        demo[mid.value] = frames
    return {"states": states, "demo": demo}


def gallery_html(lang: str = "en") -> str:
    """Render the click-through in one language (preview only)."""
    if not is_supported(lang):
        raise ValueError(f"unsupported language: {lang!r}")
    previous = current_language()
    # Pin the English snapshot before the first translation so a German
    # gallery cannot be stored as the restore table.
    if previous == "en":
        set_language("en")
    set_language(lang)
    try:
        return _gallery_html_for_current_language(lang)
    finally:
        set_language(previous)


def _gallery_html_for_current_language(lang: str) -> str:
    from beamo_wipe import recovery as Rec

    result = discovery_for_scenario("happy")
    payload = {
        "app": C.APP_NAME,
        "reportStatusTitle": C.REPORT_STATUS_TITLE,
        "reportPreview": C.REPORT_PREVIEW,
        "reportStatusNotice": C.REPORT_STATUS_NOTICE,
        "journey": C.JOURNEY_LABELS,
        "selectedDisk": C.SELECTED_DISK,
        "serialLabel": C.SERIAL_LABEL,
        "connectionLabel": _identity.CONNECTION_LABEL,
        "reviewCheck": C.REVIEW_CHECK,
        "splashRoadmap": C.SPLASH_ROADMAP,
        "sevWarning": C.SEVERITY_WARNING,
        "sevError": C.SEVERITY_ERROR,
        "sevSaved": C.SEVERITY_SAVED,
        "sevLimits": C.SEVERITY_LIMITS,
        "previewResults": {
            "ok": preview_view(True).payload(),
            "failed": {
                **preview_view(False).payload(),
                "recovery": _recovery_payload(recovery_for_view(preview_view(False))),
            },
        },
        "recoveryLabels": {
            "happened": Rec.RECOVERY_HAPPENED,
            "meaning": Rec.RECOVERY_MEANING,
            "next": Rec.RECOVERY_NEXT,
            "technical": Rec.RECOVERY_TECHNICAL,
        },
        "blockedRecovery": _recovery_payload(recovery_for_blocked(C.IDENTIFY_ERROR)),
        "emptyRecovery": _recovery_payload(recovery_for_empty()),
        "compareTitle": inventory.COMPARE_TITLE,
        "compareIntro": inventory.COMPARE_INTRO,
        "comparison": inventory.comparison_entries(
            result.selectable, peers=listed_disks(result)
        ),
        "otherTitle": inventory.TITLE,
        "nestedIntro": inventory.NESTED_INTRO,
        "bootDisc": C.BOOT_DISC_BANNER,
        "otherDevices": {
            "happy": inventory.full_text(inventory.other_devices(result)),
            "empty": inventory.full_text(
                inventory.other_devices(discovery_for_scenario("empty"))
            ),
        },
        "diskHelpButton": C.DISK_HELP_BUTTON,
        "diskHelpTitle": C.DISK_HELP_TITLE,
        "diskHelpText": C.DISK_HELP_TEXT,
        "diskHelpStop": C.DISK_HELP_STOP,
        "limitsTitle": limits.TITLE,
        "reportHelpTitle": C.REPORT_HELP_TITLE,
        "reportHelpText": C.REPORT_HELP_TEXT,
        "reportWanted": C.REPORT_WANTED,
        "reportMediaWhat": C.REPORT_MEDIA_WHAT,
        "reportMediaWanted": C.REPORT_MEDIA_WANTED,
        "anotherTitle": C.ANOTHER_TITLE,
        "anotherLoss": C.ANOTHER_LOSS,
        "anotherDiscard": C.ANOTHER_DISCARD,
        "eraseAnother": C.BTN_ERASE_ANOTHER,
        "shutdownTitle": C.SHUTDOWN_TITLE,
        "shutdownLoss": C.SHUTDOWN_LOSS,
        "shutdownKeep": C.SHUTDOWN_KEEP,
        "shutdownDiscard": C.SHUTDOWN_DISCARD,
        "shutdownHint": C.SHUTDOWN_HINT,
        "mediaStepsTitle": C.MEDIA_STEPS_TITLE,
        "mediaSteps": C.media_steps(),
        "mediaStepsAnother": C.media_steps(stay_in_session=True),
        "limitsButton": limits.BUTTON,
        "limitsText": limits.full_text(),
        "previewBanner": C.PREVIEW_BANNER,
        "splash": C.SPLASH_TAGLINE,
        "keyboardLead": C.KEYBOARD_LEAD,
        "keyboardLimits": C.KEYBOARD_LIMITS,
        "keyboardCheck": C.KEYBOARD_CHECK_LABEL,
        "keyboardHint": C.KEYBOARD_CHECK_HINT,
        "textSizeLead": C.TEXT_SIZE_LEAD,
        "textSizeUtility": C.TEXT_SIZE_UTILITY,
        "textSizes": [
            {"id": "standard", "label": C.TEXT_SIZE_STANDARD},
            {"id": "large", "label": C.TEXT_SIZE_LARGE},
            {"id": "extra", "label": C.TEXT_SIZE_EXTRA},
        ],
        "keyboardLayouts": [
            {
                "id": layout_id,
                "title": _keyboard.LAYOUTS[layout_id].title,
                "note": _keyboard.LAYOUTS[layout_id].note,
            }
            for layout_id in LAYOUT_ORDER
        ],
        "titles": {
            "keyboard": C.TITLE_KEYBOARD,
            "what": C.TITLE_WHAT,
            "owner": C.TITLE_OWNER,
            "pick": C.TITLE_PICK,
            "confirm": C.TITLE_CONFIRM,
            "method": C.TITLE_METHOD,
            "advanced": C.TITLE_ADVANCED,
            "last": C.TITLE_LAST,
            "working": C.TITLE_WORKING,
            "doneOk": C.TITLE_DONE_OK,
            "doneFail": C.TITLE_DONE_FAIL,
            "blocked": C.BLOCKED_HEADING_IDENTIFY,
            "empty": C.TITLE_EMPTY,
            "refresh": C.TITLE_REFRESH,
        },
        "refreshLead": C.REFRESH_LEAD,
        "refreshButton": C.BTN_REFRESH,
        "refreshUtility": C.BTN_REFRESH_UTILITY,
        "whatLead": C.WHAT_LEAD,
        "what": list(C.WHAT_BULLETS),
        "powerReminder": C.POWER_REMINDER,
        "powerBlanking": C.POWER_BLANKING,
        "powerKeep": C.POWER_KEEP,
        "powerEvents": C.POWER_EVENTS,
        "powerScenarios": {
            "unknown": PowerStatus().text,
            "ac": PowerStatus(ac=True, batteries=(80,), complete=True).text,
            "battery": PowerStatus(ac=False, batteries=(55,), complete=True).text,
            "low": PowerStatus(ac=False, batteries=(12,), complete=True).text,
            "desktop": PowerStatus(complete=True).text,
        },
        "whatMore": C.WHAT_MORE,
        "engine": C.ENGINE_LINE,
        "secureBoot": C.SECURE_BOOT_HINT,
        "owner": C.OWNER_CHECKBOX,
        "ownerLead": C.OWNER_LEAD,
        "bootUsb": C.BOOT_USB_BANNER,
        "identify": C.IDENTIFY_ERROR,
        "empty": C.EMPTY_DISKS,
        "supportLead": C.support_lead(),
        "supportQr": _support_qr_svg(),
        "supportCodeLabel": C.SUPPORT_CODE_LABEL,
        "supportSaveLabel": C.SUPPORT_SAVE_LABEL,
        "supportBuildLabel": C.SUPPORT_BUILD_LABEL,
        "supportCodeHint": C.SUPPORT_CODE_HINT,
        "sampleBlockedCode": code_for_startup("boot_unidentified"),
        "sampleEmptyCode": code_for_startup("no_eligible_disks"),
        "sampleExportCode": code_for_export_detail(_export.USB_FAT32_ONLY),
        "sampleBuild": public_build_id(),
        "ssd": C.SSD_FOOTER,
        "sameSize": C.SAME_SIZE_HINT,
        "sameSizeConflict": same_size_conflict(listed_disks(result)),
        "working": C.WORKING_PULSE,
        "pathNote": _identity.SYSTEM_PATH_NOTE,
        "progress": _progress_preview_payload(),
        "stageStep": _progress.STAGE_STEP,
        "stageStepPct": _progress.STEP_PCT,
        "stageDone": _progress.STAGE_DONE_MARK,
        "stageNow": _progress.STAGE_NOW_MARK,
        "stageNotReported": _progress.STAGE_NOT_REPORTED,
        "stop": {
            "title": C.STOP_TITLE,
            "lead": C.STOP_LEAD,
            "ask": C.STOP_ASK,
            "keep": C.STOP_KEEP,
            "confirm": C.STOP_CONFIRM,
            "stopping": C.STOPPING_TEXT,
            "stopped": C.VIEWS["cancelled"].payload(),
            "stoppedRecovery": _recovery_payload(recovery_for_outcome("cancelled")),
            "unconfirmed": C.VIEWS["stop_unconfirmed"].payload(),
            "unconfirmedRecovery": _recovery_payload(
                recovery_for_outcome("stop_unconfirmed")
            ),
        },
        "doneOk": C.DONE_OK_PREVIEW,
        "doneFail": C.DONE_FAIL_PREVIEW,
        "sounds": {
            "toggleOff": C.SOUND_TOGGLE_OFF,
            "toggleOn": C.SOUND_TOGGLE_ON,
            "hear": C.SOUND_HEAR,
            "hearAgain": C.SOUND_HEAR_AGAIN,
            "offLive": C.SOUND_OUTCOME_OFF_LIVE,
        },
        "pickSubtitle": C.pick_subtitle(),
        "confirmLead": C.CONFIRM_LEAD,
        "methodLead": C.METHOD_LEAD,
        "lastLead": C.LAST_LEAD,
        "recommended": C.RECOMMENDED_TAG,
        "matchWait": C.CONFIRM_MATCH_WAIT,
        "matchOk": C.CONFIRM_MATCH_OK,
        "countdownCaption": C.COUNTDOWN_CAPTION,
        "countdownReady": C.COUNTDOWN_READY,
        "advancedLead": C.ADVANCED_LEAD,
        "advancedNote": C.ADVANCED_LOG_NOTE,
        "advancedLogLabel": C.ADVANCED_LOG_LABEL,
        "buttons": {
            "understand": C.BTN_UNDERSTAND,
            "shutdown": C.BTN_SHUTDOWN,
            "closePreview": C.BTN_CLOSE_PREVIEW,
            "runAgain": C.BTN_RUN_AGAIN,
            "continue": C.BTN_CONTINUE,
            "back": C.BTN_BACK,
            "erase": C.BTN_ERASE,
            "advanced": C.BTN_ADVANCED,
            "more": C.BTN_MORE,
            "less": C.BTN_LESS,
        },
        "hints": {
            "default": C.HINT_DEFAULT,
            "pick": C.HINT_PICK,
            "owner": C.HINT_OWNER,
            "method": C.HINT_METHOD,
            "confirm": C.HINT_CONFIRM,
            "lastChance": C.HINT_LAST_CHANCE_TK,
            "blocked": C.HINT_BLOCKED,
            "working": C.HINT_WORKING,
            "splash": C.HINT_SPLASH,
            "keyboard": C.HINT_KEYBOARD,
        },
        "helperHref": helper_href_for(lang),
        "methods": {
            mid.value: {
                "title": C.METHOD_CARDS[mid]["title"],
                "blurb": C.METHOD_CARDS[mid]["blurb"],
                "pace": C.METHOD_CARDS[mid]["pace"],
                "mark": C.METHOD_CARDS[mid]["mark"],
                "extra": C.METHOD_CARDS[mid]["extra"],
                "checks": C.METHOD_CARDS[mid]["checks"],
                "key": C.METHOD_CARDS[mid]["key"],
                "docs": METHODS[mid].docs_name,
                "nwipe": METHODS[mid].nwipe_method,
                "summary": METHODS[mid].summary,
                "operation": METHODS[mid].operation_summary,
                "stages": [
                    _progress.stage_label(stage)
                    for stage in _progress.plan_stages(
                        METHODS[mid].overwrite_passes,
                        bool(METHODS[mid].verification_passes),
                    )
                ],
                "result": preview_view(True).message,
            }
            for mid in (MethodId.EVERYDAY, MethodId.EXTRA, MethodId.QUICK_ZERO)
        },
        "disks": _disks_payload("happy"),
        "lang": lang,
        "chrome": {
            "title": C.GALLERY_TITLE,
            "note": C.GALLERY_NOTE.format(helper=helper_href_for(lang)),
            "happy": C.GALLERY_HAPPY,
            "empty": C.GALLERY_EMPTY,
            "blocked": C.GALLERY_BLOCKED,
            "fail": C.GALLERY_FAIL,
            "fakePower": C.GALLERY_FAKE_POWER,
            "powerUnknown": C.GALLERY_POWER_UNKNOWN,
            "powerAc": C.GALLERY_POWER_AC,
            "powerBattery": C.GALLERY_POWER_BATTERY,
            "powerLow": C.GALLERY_POWER_LOW,
            "powerDesktop": C.GALLERY_POWER_DESKTOP,
            "eraseSteps": C.GALLERY_ERASE_STEPS,
            "previewPower": C.GALLERY_PREVIEW_POWER,
            "closeTab": C.GALLERY_CLOSE_TAB,
        },
        "languageTitle": C.TITLE_LANGUAGE,
        "languageLead": C.LANGUAGE_LEAD,
        "languages": [
            {"id": code, "name": LANGUAGE_NAMES[code], "active": code == lang}
            for code in LANGUAGE_ORDER
        ],
        "confirmKeyboard": C.CONFIRM_KEYBOARD_LINE.format(
            layout=_keyboard.LAYOUTS["us"].title, language=LANGUAGE_NAMES[lang]
        ),
        "steps": {str(n): C.STEP_OF.format(n=n, total=8) for n in range(1, 9)},
        "stepPrefix": C.STEP_PREFIX,
        "stepIdentify": C.STEP_IDENTIFY,
        "stepOwnership": C.STEP_OWNERSHIP,
        "stoppingErase": C.BUSY_STOPPING_TITLE,
        "eraseProgress": C.ERASE_PROGRESS_LABEL,
        "noWipeYet": C.NO_WIPE_YET,
        "refreshHint": C.HINT_REFRESH,
    }
    # JSON is embedded in a script element. Escaping HTML-significant code
    # points prevents a future fixture/copy string containing </script> from
    # terminating the element and injecting markup into the local preview.
    data = (
        json.dumps(payload)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )
    chrome = payload["chrome"]
    assert isinstance(chrome, dict)
    return (
        _TEMPLATE.replace("__PAYLOAD__", data)
        .replace("__LOGO_HEADER__", _logo_svg(36, 30))
        .replace("__LOGO_SPLASH__", _logo_svg(70, 58))
        .replace("__FAVICON__", _favicon_uri())
        .replace("__GALLERY_LANG__", lang)
        .replace("__GALLERY_TITLE__", chrome["title"])
        .replace("__GALLERY_NOTE__", chrome["note"])
        .replace("__GALLERY_HAPPY__", chrome["happy"])
        .replace("__GALLERY_EMPTY__", chrome["empty"])
        .replace("__GALLERY_BLOCKED__", chrome["blocked"])
        .replace("__GALLERY_FAIL__", chrome["fail"])
        .replace("__GALLERY_FAKE_POWER__", chrome["fakePower"])
        .replace("__GALLERY_POWER_UNKNOWN__", chrome["powerUnknown"])
        .replace("__GALLERY_POWER_AC__", chrome["powerAc"])
        .replace("__GALLERY_POWER_BATTERY__", chrome["powerBattery"])
        .replace("__GALLERY_POWER_LOW__", chrome["powerLow"])
        .replace("__GALLERY_POWER_DESKTOP__", chrome["powerDesktop"])
        .replace("__GALLERY_ERASE_STEPS__", chrome["eraseSteps"])
    )


def helper_href_for(lang: str) -> str:
    if lang == "en":
        return "../helper/index.html"
    return f"../helper/{lang}.html"


def write_gallery(dest: Path | None = None, lang: str = "en") -> Path:
    if dest is None:
        root = project_root()
        if (root / "helper" / "index.html").is_file():
            dest = root / "web-preview" / "index.html"
        else:
            dest = Path.cwd() / "web-preview" / "index.html"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(gallery_html(lang), encoding="utf-8")
    return dest


def open_gallery(dest: Path | None = None, lang: str = "en") -> Path:
    import webbrowser

    path = write_gallery(dest, lang)
    webbrowser.open(path.resolve().as_uri())
    return path


# The template mirrors the Tk design system in ui/tk_wizard.py: same tokens,
# same components (cards, panels, buttons, key-caps, countdown ring), same
# screen layouts. Keep the two in sync when the design changes.
_TEMPLATE = r"""<!DOCTYPE html>
<html lang="__GALLERY_LANG__">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" href="__FAVICON__">
<title>__GALLERY_TITLE__</title>
<style>
  :root {
    /* Shared palette, pinned against ui/tk_wizard.py by tests/test_ui_system.py. */
    --bg: #FFFFFF; --surface: #FFFFFF; --surface-alt: #F4F6F8;
    --ink: #12202E; --muted: #4A5A6A;
    --border: #E3E8EE; --border-strong: #6E7C8A;
    --navy: #0A1B34; --navy-soft: #16315C; --navy-muted: #C9D6E8;
    --primary: #1C4A73; --primary-dark: #163A5C; --primary-press: #102A44; --primary-tint: #F0F5FA;
    --danger: #B3261E; --danger-dark: #8E1D16; --danger-press: #6E1510; --danger-tint: #FBEBE9; --danger-border: #E6A79E;
    --ok: #17703F; --ok-tint: #E7F2EB; --ok-border: #9CC3AB;
    --warn: #7A5200; --warn-bg: #FBF1D5; --warn-border: #E3CE96;
    --usb-bg: #F7F1E6; --usb-border: #D9CEB5;
    --focus: #2563EB; --accent: #E6A817;
    --disabled-bg: #E8ECF1; --disabled-fg: #6E7989; --track: #E4E9EF;
    --shadow: 0 1px 2px rgba(18,32,46,.05), 0 10px 28px rgba(18,32,46,.06);
    --halo: 0 0 0 4px rgba(28,74,115,.12);
    --radius: 12px;
    --radius-lg: 16px;
    --pill: 999px;
  }
  * { box-sizing: border-box; }
  body { margin: 0; font-family: "Segoe UI", "Helvetica Neue", Helvetica, Arial, sans-serif; background: var(--surface-alt); color: var(--ink); -webkit-font-smoothing: antialiased; }
  .page { max-width: 1120px; margin: 0 auto; padding: 28px 20px 72px; }
  .note { background: var(--surface); border: 1px solid var(--border); color: var(--navy); font-weight: 400; padding: 14px 18px; margin-bottom: 18px; font-size: 14px; border-radius: var(--radius); box-shadow: var(--shadow); }
  .note code { background: #fff7d6; padding: 2px 7px; border-radius: 8px; }
  .note a { color: var(--navy); }
  .scenarios { margin: 0 0 22px; }
  .scenarios button { font-size: 14px; font-weight: 600; margin: 0 8px 8px 0; padding: 8px 16px; background: var(--surface); color: var(--ink); border: 1px solid var(--border); border-radius: var(--pill); cursor: pointer; }
  .scenarios button:hover { background: var(--primary-tint); border-color: var(--primary); }
  .scenarios button:focus-visible { outline: 3px solid var(--focus); outline-offset: 2px; }
  .shell { --type: 1; background: var(--bg); min-height: 740px; border: 1px solid var(--border); border-radius: var(--radius-lg); overflow: hidden; display: flex; flex-direction: column; box-shadow: var(--shadow); }
  .shell[data-text="large"] { --type: 1.2; }
  .shell[data-text="extra"] { --type: 1.35; }
  .shell h1 { font-size: calc(32px * var(--type)); }
  .shell .subtitle, .shell .lead, .shell .panel { font-size: calc(16px * var(--type)); }
  .shell .card .title { font-size: calc(16px * var(--type)); }
  .shell .small, .shell .card .meta { font-size: calc(14px * var(--type)); }
  .shell button.btn { font-size: calc(15px * var(--type)); }
  .textsizes { display: flex; flex-wrap: wrap; gap: 8px; margin: 0 0 12px; }
  .preview-stripe { background: var(--accent); color: var(--navy); padding: 8px 28px; font-size: 13px; font-weight: 700; letter-spacing: .01em; overflow-wrap: break-word; }
  /* Quiet white chrome: the navy-on-transparent mark sits on the field,
     a hairline separates header from body — mirroring _draw_header. */
  .hdr { background: var(--bg); border-bottom: 1px solid var(--border); color: var(--ink); height: 56px; padding: 0 24px; display: flex; justify-content: space-between; align-items: center; }
  .brandrow { display: flex; align-items: center; gap: 12px; font-size: 16px; font-weight: 700; }
  .brandchip { display: flex; align-items: center; justify-content: center; flex: none; }
  .brandchip svg { display: block; }
  /* Current-step text lives in .steptext. The list is a screen-reader
     name only — never a numbered map of the whole journey. */
  .journey { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
  .review-grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(140px, 200px); gap: 24px; margin-top: 8px; align-items: start; }
  .shell[data-text="large"] .review-grid,
  .shell[data-text="extra"] .review-grid { grid-template-columns: minmax(0, 1fr); }
  .review-grid .countcap { max-width: 260px; text-align: center; }
  .review-warning { color: var(--danger); font-weight: 700; overflow-wrap: anywhere; }
  .card.identity { background: var(--primary-tint); border-color: var(--primary); padding: 16px 22px; }
  .identity-label { color: var(--primary); font-size: 12px; font-weight: 700; margin-bottom: 6px; }
  .serialpair { display: flex; align-items: baseline; gap: 8px; min-width: 0; }
  .serialpair .ser { min-width: 0; }
  .serial-label { flex-shrink: 0; font-size: 12px; color: var(--muted); }
  .splash-roadmap { font-size: 14px; color: var(--muted); margin-top: 14px; line-height: 1.6; }
  .pick-tools { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin: 4px 0 8px; }
  .pick-tools .morelink { margin-top: 0; }
  .steptext { font-size: 12px; font-weight: 500; color: var(--muted); letter-spacing: 0; text-transform: none; white-space: nowrap; }
  .strip { height: 2px; background: var(--track); }
  .strip .sfill { height: 100%; background: var(--accent); width: 0; transition: width .25s ease; border-radius: 0 1.5px 1.5px 0; }
  .body { flex: 1; padding: 4px 32px 16px; background: var(--bg); display: flex; }
  .col { max-width: 940px; margin: 0 auto; width: 100%; display: flex; flex-direction: column; }
  /* The one screen-header pattern, mirroring _title_block: bold title,
     optional muted subtitle. compact is for the tightest screens. */
  h1 { font-size: 32px; margin: 16px 0 10px; color: var(--ink); letter-spacing: -.03em; font-weight: 700; overflow-wrap: break-word; }
  h1.sub { margin-bottom: 4px; }
  h1.compact { margin: 12px 0 6px; }
  .subtitle { font-size: 16px; color: var(--muted); margin: 0 0 10px; line-height: 1.45; }
  /* Content stays at the top of the remaining band, matching _center_zone. */
  .cz { flex: 1; display: flex; flex-direction: column; }
  .czc { margin: 0; padding: 4px 0; }
  .lead { font-size: 18px; line-height: 1.45; margin: 0 0 12px; }
  .muted { color: var(--muted); }
  .small { font-size: 14px; }
  .mono { font-family: "SF Mono", Menlo, Consolas, "DejaVu Sans Mono", monospace; }
  .kbd { display: inline-block; background: var(--surface-alt); border: 1px solid var(--border-strong); border-radius: 8px; padding: 2px 8px; font-size: 12px; font-weight: 600; color: var(--ink); line-height: 1.35; }
  .card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 14px 18px; margin: 0 0 8px; }
  .card.hero { box-shadow: var(--shadow); margin-left: 0; margin-right: 0; padding: 18px 22px; }
  .card.pickable { cursor: pointer; transition: border-color .12s ease, background .12s ease, box-shadow .12s ease; }
  .card.pickable:hover { background: var(--surface-alt); }
  .card.pickable:focus-visible { outline: 3px solid var(--focus); outline-offset: 2px; }
  .card.sel { border: 2px solid var(--primary); background: var(--primary-tint); padding: 13px 17px; box-shadow: var(--halo); }
  .card.sel:hover { background: var(--primary-tint); }
  .card.boot { background: var(--usb-bg); border-color: var(--usb-border); cursor: not-allowed; }
  .card .row { display: flex; align-items: flex-start; gap: 14px; }
  .card .grow { flex: 1; min-width: 0; }
  .card .row > .kbd { flex: none; margin-top: 1px; }
  .card .title { font-size: 16px; font-weight: 700; }
  .card .title .chip { margin-left: 10px; }
  .card .size { font-size: 20px; font-weight: 700; white-space: nowrap; }
  .card .meta { margin-top: 4px; font-size: 14px; color: var(--muted); display: flex; flex-wrap: wrap; gap: 4px 0; align-items: center; }
  .card .meta .mono { color: var(--ink); font-size: 14px; }
  .card .meta .mono.ser { font-weight: 700; }
  .card .meta .mono.dev { color: var(--muted); font-size: 13px; }
  .card .meta .dot { color: var(--border-strong); margin: 0 6px; }
  .radio { flex: none; width: 22px; height: 22px; margin-top: 1px; border: 2px solid var(--border-strong); border-radius: 50%; position: relative; background: var(--surface); }
  .sel .radio { border-color: var(--primary); }
  .sel .radio::after { content: ""; position: absolute; inset: 30%; border-radius: 50%; background: var(--primary); }
  .chip { display: inline-block; font-size: 12px; font-weight: 700; padding: 2px 10px; background: var(--surface-alt); color: var(--muted); border-radius: 999px; vertical-align: 2px; }
  .chip.ok { color: var(--ok); background: var(--ok-tint); }
  .chip.warn { color: var(--warn); background: var(--warn-bg); }
  .methodextra { font-size: 14px; color: var(--muted); margin: 4px 0 0; line-height: 1.4; }
  .bootbanner { margin-bottom: 6px; color: var(--ink); font-weight: 700; font-size: 14px; overflow-wrap: anywhere; }
  .panel { display: flex; gap: 12px; align-items: flex-start; border: 1px solid; border-radius: var(--radius); padding: 14px 18px; font-size: 16px; line-height: 1.45; }
  .panel svg { flex: none; margin-top: 1px; }
  .panel.warn { background: var(--warn-bg); border-color: var(--warn-border); }
  .panel.danger { background: var(--danger-tint); border-color: var(--danger-border); }
  .panel.info { background: var(--surface-alt); border-color: var(--border); }
  .panel.ok { background: var(--ok-tint); border-color: var(--ok-border); }
  .panel.limits { background: var(--surface-alt); border-color: var(--border); }
  .panel .sev { font-size: 14px; font-weight: 700; margin-bottom: 2px; }
  .panel.warn .sev { color: var(--warn); }
  .panel.danger .sev { color: var(--danger); }
  .panel.ok .sev { color: var(--ok); }
  .panel.limits .sev { color: var(--primary); }
  .panel .extra { font-size: 14px; color: var(--muted); margin-top: 4px; }
  /* One-row footer, mirroring _footer_shell: secondary actions left, key
     hints centered, the primary action right, hairline on top. */
  .foot { padding: 0 32px; }
  .footrow { max-width: 940px; margin: 0 auto; padding: 16px 0 20px; border-top: 1px solid var(--border); display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
  .card, .panel, .foot, .compare-pre, .help-reader { overflow-wrap: anywhere; }
  .fleft, .fright { display: flex; gap: 12px; flex: none; }
  .fhint { flex: 1; text-align: center; color: var(--muted); font-size: 13px; line-height: 1.9; }
  .fhint .kbd { margin: 0 1px; }
  button.btn { font-size: 15px; font-weight: 600; padding: 11px 22px; border: 1px solid transparent; border-radius: var(--pill); cursor: pointer; min-width: 112px; letter-spacing: -.01em; }
  button.btn:focus-visible { outline: 3px solid var(--focus); outline-offset: 2px; }
  .primary { background: var(--primary); color: #fff; min-width: 160px; }
  .primary:hover:not(:disabled) { background: var(--primary-dark); }
  .primary:active:not(:disabled) { background: var(--primary-press); }
  button.btn.danger { background: var(--danger); color: #fff; min-width: 160px; }
  button.btn.danger:hover:not(:disabled) { background: var(--danger-dark); }
  button.btn.danger:active:not(:disabled) { background: var(--danger-press); }
  button.btn.secondary { background: var(--surface); color: var(--ink); border: 1px solid var(--border-strong); }
  .secondary:hover:not(:disabled) { background: var(--surface-alt); }
  .secondary:active:not(:disabled) { background: #E2E8EE; }
  button.btn:disabled { background: var(--disabled-bg); color: var(--disabled-fg); border-color: transparent; box-shadow: none; cursor: not-allowed; }
  .linkbtn { background: none; border: 0; color: var(--primary); font-size: 14px; font-weight: 600; cursor: pointer; padding: 6px 10px; text-align: left; border-radius: var(--pill); margin-left: -10px; }
  .linkbtn:hover { background: var(--primary-tint); }
  .linkbtn:focus-visible { outline: 3px solid var(--focus); }
  .morelink { display: inline-block; margin: 8px 0 0; }
  .entryshell { background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius); padding: 12px 18px; box-shadow: var(--shadow); }
  .entryshell:focus-within { outline: 3px solid var(--focus); outline-offset: 2px; border-color: var(--focus); }
  input.token { font-family: "SF Mono", Menlo, Consolas, "DejaVu Sans Mono", monospace; font-size: 26px; font-weight: 700; width: 100%; padding: 4px 0; border: 0; outline: none; background: transparent; color: var(--ink); letter-spacing: .02em; }
  .match { display: inline-flex; align-items: center; gap: 8px; font-size: 14px; font-weight: 600; margin: 12px 0 0; color: var(--muted); background: var(--surface-alt); border: 1px solid var(--border); border-radius: var(--pill); padding: 6px 12px; }
  .match.ok { color: var(--ok); background: var(--ok-tint); border-color: var(--ok); }
  .progress-card { padding: 20px 22px; border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface-alt); }
  .progress-label { font-size: 13px; font-weight: 600; color: var(--muted); margin-bottom: 8px; letter-spacing: .02em; }
  .progress-timing { white-space: pre-wrap; font-size: 16px; margin-top: 14px; color: var(--muted); }
  .bigstat { font-size: 56px; font-weight: 700; line-height: 1.05; letter-spacing: -.03em; min-height: 62px; }
  .bar { height: 8px; background: var(--track); border-radius: var(--pill); overflow: hidden; }
  .fill { height: 100%; background: var(--primary); width: 2%; border-radius: var(--pill); transition: width .2s ease; }
  .fill.indet { width: 30%; animation: slide 1.7s ease-in-out infinite alternate; }
  @keyframes slide { from { margin-left: 0; } to { margin-left: 70%; } }
  .status { width: 72px; height: 72px; border-radius: 50%; display: flex; align-items: center; justify-content: center; margin: 0 auto; }
  .status.ok { background: var(--ok-tint); }
  .status.bad { background: var(--danger-tint); }
  .status .core { width: 56px; height: 56px; border-radius: 50%; color: #fff; font-size: 32px; font-weight: 700; display: flex; align-items: center; justify-content: center; }
  .status.ok .core { background: var(--ok); }
  .status.bad .core { background: var(--danger); }
  .badgehalo { width: 88px; height: 88px; border-radius: 50%; display: flex; align-items: center; justify-content: center; margin: 0 auto; }
  .badgehalo.warn { background: var(--warn-bg); }
  .badgehalo.danger { background: var(--danger-tint); }
  .badgehalo.info { background: var(--surface-alt); }
  .ok { color: var(--ok); } .bad { color: var(--danger); }
  ul.bullets { list-style: none; margin: 0; padding: 14px 22px; background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); box-shadow: var(--shadow); }
  ul.bullets li { font-size: 17px; line-height: 1.5; padding: 2px 0; display: flex; }
  ul.bullets li + li { margin-top: 8px; }
  ul.bullets li::before { content: ""; width: 7px; height: 7px; border-radius: 50%; background: var(--accent); margin: 10px 14px 0 1px; flex: none; }
  .ownercard { display: flex; gap: 16px; align-items: flex-start; background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius); padding: 14px 18px; cursor: pointer; font-size: 18px; line-height: 1.45; }
  .ownercard:hover { background: var(--surface-alt); }
  .ownercard:focus-visible { outline: 3px solid var(--focus); outline-offset: 2px; }
  .ownercard.checked { border: 2px solid var(--primary); background: var(--primary-tint); padding: 13px 17px; box-shadow: var(--halo); }
  .ownercard.checked:hover { background: var(--primary-tint); }
  .cbox { flex: none; width: 28px; height: 28px; margin-top: 1px; border: 2px solid var(--border-strong); border-radius: 10px; background: var(--surface); color: #fff; font-size: 18px; font-weight: 700; line-height: 24px; text-align: center; }
  .ownercard.checked .cbox { background: var(--primary); border-color: var(--primary); }
  .checkrow { display: flex; gap: 12px; align-items: flex-start; margin-top: 10px; cursor: pointer; font-size: 14px; line-height: 1.45; padding: 8px 10px; border-radius: var(--radius); }
  .checkrow:hover { background: var(--surface-alt); }
  .checkrow:focus-visible { outline: 3px solid var(--focus); outline-offset: 2px; }
  .checkrow .cbox { width: 22px; height: 22px; font-size: 14px; line-height: 18px; }
  .checkrow.checked { background: var(--primary-tint); }
  .checkrow.checked .cbox { background: var(--primary); border-color: var(--primary); }
  .ringwrap { display: flex; flex-direction: column; align-items: center; }
  .ringnum { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; font-size: 16px; font-weight: 700; }
  .countcap { font-size: 16px; color: var(--muted); margin-top: 12px; }
  .countcap.ready { color: var(--ink); font-weight: 600; }
  .advrow { font-size: 13px; margin: 0; padding: 7px 0; }
  .advrow + .advrow { border-top: 1px solid var(--border); }
  .methodblurb { font-size: 14px; color: var(--muted); margin: 4px 0 0; }
  .methodpace { font-size: 14px; color: var(--muted); margin: 4px 0 0; display: flex; gap: 7px; align-items: flex-start; }
  .methodpace svg { flex: none; margin-top: 1px; }
  .centerstage { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; }
  .centerstage h1 { margin: 22px 0 8px; }
  .result { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: flex-start; text-align: center; padding-top: 12px; }
  .result h1 { margin: 12px 0 4px; }
  .result h2 { font-size: 16px; margin: 16px 0 6px; }
  .statustext { font-size: 16px; color: var(--muted); max-width: 700px; margin: 0 auto; line-height: 1.45; }
  .recovery { max-width: 700px; margin: 12px auto 0; text-align: left; }
  .recovery h2 { font-size: 14px; font-weight: 700; margin: 12px 0 4px; }
  .recovery p { margin: 0; font-size: 16px; line-height: 1.45; }
  .recovery-tech { margin-top: 12px; }
  .recovery-tech summary { cursor: pointer; font-weight: 600; }
  .support { display: flex; gap: 12px; align-items: center; max-width: 700px; margin: 16px auto 0; text-align: left; }
  .support svg { width: 132px; height: auto; flex: none; border: 1px solid var(--muted); background: #fff; }
  .support p { margin: 0; min-width: 0; }
  .support p:focus-visible { outline: 3px solid var(--focus); outline-offset: 2px; border-radius: 4px; }
  .support-code { max-width: 700px; margin: 16px auto 0; text-align: left; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
  .support-code .row { display: flex; gap: 12px; margin: 0; }
  .support-code .k { color: var(--muted); min-width: 7em; }
  .support-code .v { font-weight: 700; letter-spacing: 0.04em; }
  .support-code .hint { margin: 6px 0 0; color: var(--muted); font-family: inherit; font-weight: 400; letter-spacing: 0; }
  /* Splash: a plain white field, the navy-on-transparent brand mark,
     huge simple type, and one primary action — mirroring TkWizard._splash. */
  .splashwrap { min-height: 640px; display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; position: relative; }
  .marktile { display: flex; }
  .marktile svg { display: block; }
  .wordmark { font-size: 56px; font-weight: 700; color: var(--ink); letter-spacing: -.04em; margin-top: 16px; line-height: 1.02; }
  .splashlead { font-size: 18px; line-height: 1.5; color: var(--muted); max-width: 620px; margin: 8px 0 0; }
  .splashwrap .btn.primary { min-width: 240px; padding: 14px 34px; margin-top: 24px; }
  .anykeycap { margin-top: 14px; font-size: 12px; color: var(--muted); }
  .disklist { flex: 1; min-height: 160px; overflow-y: auto; scrollbar-width: thin; scrollbar-color: var(--border-strong) transparent; }
  .disklist::-webkit-scrollbar { width: 10px; }
  .disklist::-webkit-scrollbar-thumb { background: var(--border-strong); border-radius: 999px; border: 2px solid var(--bg); }
  .disklist::-webkit-scrollbar-track { background: transparent; }
  .utilities { max-width: 940px; margin: auto; display: flex; flex-wrap: wrap; gap: 4px; padding-top: 4px; }
  button.btn.ghost { background: transparent; color: var(--primary); border-color: transparent; min-width: 0; padding: 8px 16px; font-size: 14px; font-weight: 500; }
  button.btn.ghost:hover { background: var(--primary-tint); }
  .utilities:empty { display: none; }
  section[aria-label] h2 { font-size: 14px; margin: 8px 0 4px; }
  .inventory-reader, .help-reader { white-space: pre-wrap; overflow: auto; padding: 12px 14px; font-size: 14px; line-height: 1.45; border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface-alt); color: var(--ink); }
  .inventory-reader { max-height: 78px; margin-bottom: 10px; padding: 8px 12px; }
  .help-reader { max-height: 55vh; }
  .help-reader.compact { max-height: 43vh; }
  .nested { margin-top: 8px; padding-top: 8px; border-top: 1px solid var(--border); font-size: 13px; color: var(--muted); }
  .nested-intro { font-weight: 600; margin-bottom: 4px; }
  .nested-item { margin-top: 6px; }
  .inventory-reader:focus-visible, .help-reader:focus-visible { outline: 3px solid var(--focus); outline-offset: 1px; }
  details.compare { border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface); margin: 0 0 12px; padding: 0; }
  details.compare > summary { list-style: none; cursor: pointer; font-size: 14px; font-weight: 700; padding: 12px 16px; display: flex; align-items: center; gap: 10px; color: var(--ink); }
  details.compare > summary::-webkit-details-marker, details.compare > summary::marker { display: none; content: none; }
  details.compare > summary::before { content: ""; width: 22px; height: 22px; flex: none; border: 2px solid var(--border-strong); border-radius: 10px; background: var(--surface); box-sizing: border-box; }
  details.compare[open] > summary::before { content: "✓"; color: #fff; background: var(--primary); border-color: var(--primary); font-size: 14px; font-weight: 700; line-height: 18px; text-align: center; }
  details.compare > summary:focus-visible { outline: 3px solid var(--focus); outline-offset: 2px; border-radius: 8px; }
  .compare-body { padding: 0 16px 16px; }
  .compare-body > p { margin: 0 0 12px; font-size: 14px; color: var(--muted); }
  .compare-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 320px), 1fr)); gap: 12px; }
  .compare-pre { white-space: pre-wrap; overflow-wrap: anywhere; font: inherit; margin: 0; padding: 12px 14px; border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface-alt); color: var(--ink); }
  .compare-pre:focus-visible { outline: 3px solid var(--focus); outline-offset: 2px; }
  .disktype { display: block; font-size: 14px; font-weight: 400; color: var(--muted); margin-top: 0; }
  .card .title, .card .meta { overflow-wrap: anywhere; }
  /* Grid/flex items default to min-width:auto: a long unbroken serial,
     model, or warning would push past the card instead of wrapping. */
  .card .meta > *, .panel > div { min-width: 0; }
  .panel > div { overflow-wrap: anywhere; }
  .card .meta { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 4px 16px; }
  .connection { grid-column: 1 / -1; }
  .compact-notice { padding: 8px 16px; font-size: 14px; }
  .card .meta .ser { display: block; }
  .page, .shell, .body, .col { min-width: 0; }
  @media (max-width: 1000px) { .hdr { padding: 0 16px; } }
  @media (max-width: 700px) {
    .review-grid { grid-template-columns: minmax(0, 1fr); }
    .review-grid .ringwrap { padding: 12px 0; }
    .pick-tools { flex-wrap: wrap; }
    .page { padding: 12px 8px 24px; }
    .body { padding: 0 16px 16px; }
    .hdr { padding: 0 16px; }
    .foot { padding: 0 16px; }
    .footrow { flex-wrap: wrap; gap: 12px; }
    .fhint { order: 3; flex-basis: 100%; text-align: left; }
    .fright { margin-left: auto; }
    .fleft { flex-wrap: wrap; }
    h1 { font-size: 28px; line-height: 1.2; }
    .wordmark { font-size: 42px; }
    .shell { min-height: 680px; }
    .card .row { gap: 10px; }
    .card .size { font-size: 18px; }
    .panel { padding: 12px; }
    .bootbanner { margin-left: 0; border-radius: 6px; }
    .preview-stripe { padding: 8px 16px; }
  }
  @media (prefers-reduced-motion: reduce) {
    *, *::before, *::after { animation: none !important; transition: none !important; }
  }
</style>
</head>
<body>
<div class="page">
  <div class="note">
    __GALLERY_NOTE__
  </div>
  <div class="scenarios">
    <button type="button" onclick="boot('happy')">__GALLERY_HAPPY__</button>
    <button type="button" onclick="boot('empty')">__GALLERY_EMPTY__</button>
    <button type="button" onclick="boot('blocked')">__GALLERY_BLOCKED__</button>
    <button type="button" onclick="boot('fail')">__GALLERY_FAIL__</button>
    <label>__GALLERY_FAKE_POWER__ <select id="power-choice" onchange="updatePower(this.value)">
      <option value="unknown">__GALLERY_POWER_UNKNOWN__</option><option value="ac">__GALLERY_POWER_AC__</option>
      <option value="battery">__GALLERY_POWER_BATTERY__</option><option value="low">__GALLERY_POWER_LOW__</option>
      <option value="desktop">__GALLERY_POWER_DESKTOP__</option>
    </select></label>
  </div>
  <div class="shell">
    <div class="preview-stripe" id="stripe"></div>
    <div class="hdr"><div class="brandrow"><span class="brandchip">__LOGO_HEADER__</span><div id="brand"></div></div><ol class="journey" id="journey" aria-label="__GALLERY_ERASE_STEPS__"></ol><span class="steptext" id="step"></span></div>
    <div class="strip"><div class="sfill" id="sfill"></div></div>
    <div class="body" id="body"><div class="col" id="main"></div></div>
    <div class="foot" id="foot"><div class="utilities" id="utilities"></div><div class="footrow"><div class="fleft" id="btnsL"></div><div class="fhint" id="hint"></div><div class="fright" id="btnsR"></div></div></div>
  </div>
</div>
<script>
const P = __PAYLOAD__;
let powerChoice = "unknown";
function powerText() { return P.chrome.previewPower + P.powerScenarios[powerChoice]; }
function powerPanel(reminder=true) {
  return `<div class="panel info"><div>${reminder ? `<div>${P.powerKeep}</div>` : ""}<div id="power-status" role="status" aria-live="polite">${powerText()}</div></div></div>`;
}
function updatePower(value) {
  powerChoice = Object.hasOwn(P.powerScenarios, value) ? value : "unknown";
  const status = document.getElementById("power-status");
  if (status) status.textContent = powerText();
}
let screen = "splash";
let soundsOn = false;
let renderedScreen = null;
let reportWanted = false;
let reportHelpFrom = "what";
let refreshFrom = "what";
let shutdownFrom = "what";
let anotherPending = false;
let owner = false;
let selected = null;
let token = "";
let keyboardLayout = "us";
let textSize = "standard";
let method = "everyday";
let tLeft = 5;
let timer = null;
let fail = false;
let mode = "happy";
let demoPct = null;
let demoFrac = null;
let progressKey = "";
let showMore = false;

document.getElementById("stripe").textContent = P.previewBanner;
document.getElementById("brand").textContent = P.app;

// Filled badge icons, mirroring _icon_alert in the Tk UI. Every severity
// differs by shape, not color: triangle warn, circle-X danger, circle-i
// info, circle-check ok, document limits.
function badge(kind, size) {
  const s = size;
  if (kind === "info") {
    const c = "#1C4A73";
    return `<svg width="${s}" height="${s}" viewBox="0 0 ${s} ${s}">` +
      `<circle cx="${s/2}" cy="${s/2}" r="${s/2-2}" fill="${c}"/>` +
      `<circle cx="${s/2}" cy="${s*0.26}" r="${s*0.075}" fill="#fff"/>` +
      `<line x1="${s/2}" y1="${s*0.46}" x2="${s/2}" y2="${s*0.74}" stroke="#fff" stroke-width="${s*0.09}" stroke-linecap="round"/></svg>`;
  }
  if (kind === "danger") {
    const c = "#B3261E";
    return `<svg width="${s}" height="${s}" viewBox="0 0 ${s} ${s}">` +
      `<circle cx="${s/2}" cy="${s/2}" r="${s/2-2}" fill="${c}"/>` +
      `<line x1="${s*0.30}" y1="${s*0.30}" x2="${s*0.70}" y2="${s*0.70}" stroke="#fff" stroke-width="${s*0.10}" stroke-linecap="round"/>` +
      `<line x1="${s*0.30}" y1="${s*0.70}" x2="${s*0.70}" y2="${s*0.30}" stroke="#fff" stroke-width="${s*0.10}" stroke-linecap="round"/></svg>`;
  }
  if (kind === "ok") {
    const c = "#17703F";
    return `<svg width="${s}" height="${s}" viewBox="0 0 ${s} ${s}">` +
      `<circle cx="${s/2}" cy="${s/2}" r="${s/2-2}" fill="${c}"/>` +
      `<path d="M ${s*0.26} ${s*0.54} L ${s*0.44} ${s*0.70} L ${s*0.74} ${s*0.30}" fill="none" stroke="#fff" stroke-width="${s*0.10}" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
  }
  if (kind === "limits") {
    const c = "#1C4A73";
    return `<svg width="${s}" height="${s}" viewBox="0 0 ${s} ${s}">` +
      `<rect x="2" y="2" width="${s-4}" height="${s-4}" rx="${s*0.22}" fill="${c}"/>` +
      `<line x1="${s*0.28}" y1="${s*0.36}" x2="${s*0.72}" y2="${s*0.36}" stroke="#fff" stroke-width="${s*0.07}" stroke-linecap="round"/>` +
      `<line x1="${s*0.28}" y1="${s*0.52}" x2="${s*0.72}" y2="${s*0.52}" stroke="#fff" stroke-width="${s*0.07}" stroke-linecap="round"/>` +
      `<line x1="${s*0.28}" y1="${s*0.68}" x2="${s*0.72}" y2="${s*0.68}" stroke="#fff" stroke-width="${s*0.07}" stroke-linecap="round"/></svg>`;
  }
  const c = "#7A5200";
  return `<svg width="${s}" height="${s}" viewBox="0 0 ${s} ${s}">` +
    `<path d="M ${s/2} ${2} L ${s-2} ${s-3} L 2 ${s-3} Z" fill="${c}" stroke="${c}" stroke-width="${s*0.18}" stroke-linejoin="round"/>` +
    `<line x1="${s/2}" y1="${s*0.36}" x2="${s/2}" y2="${s*0.62}" stroke="#fff" stroke-width="${s*0.09}" stroke-linecap="round"/>` +
    `<circle cx="${s/2}" cy="${s*0.75}" r="${s*0.06}" fill="#fff"/></svg>`;
}
const ICON_NO = '<svg width="22" height="22" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="9.2" stroke="#B3261E" stroke-width="2.6"/><line x1="6" y1="18" x2="18" y2="6" stroke="#B3261E" stroke-width="2.6" stroke-linecap="round"/></svg>';
const MATCH_WAIT = '<svg width="22" height="22" viewBox="0 0 22 22"><circle cx="11" cy="11" r="8" fill="none" stroke="#6E7C8A" stroke-width="2"/></svg>';
const MATCH_OK = '<svg width="22" height="22" viewBox="0 0 22 22"><circle cx="11" cy="11" r="10" fill="#17703F"/><path d="M6 11.5 9.5 15 16 7.5" fill="none" stroke="#fff" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/></svg>';
const EMBLEM = '__LOGO_SPLASH__';

// Key names inside hint copy render as key-caps, mirroring _hint_bar.
const KEY_RE = /(Up\/Down|1, 2, or 3|any key|Enter|Esc|Space)/g;
const KEY_MAP = {"Up/Down": ["↑", "↓"], "1, 2, or 3": ["1", "2", "3"]};
function renderHint(text) {
  const el = document.getElementById("hint");
  el.innerHTML = "";
  let pos = 0;
  for (const m of text.matchAll(KEY_RE)) {
    if (m.index > pos) el.append(document.createTextNode(text.slice(pos, m.index)));
    const keys = KEY_MAP[m[0]] || [m[0]];
    keys.forEach((k, i) => {
      if (i > 0) el.append(document.createTextNode(" "));
      const cap = document.createElement("span");
      cap.className = "kbd";
      cap.textContent = k;
      el.append(cap);
    });
    pos = m.index + m[0].length;
  }
  if (pos < text.length) el.append(document.createTextNode(text.slice(pos)));
}

function boot(m) {
  anotherPending = false;
  reportWanted = false;
  reportHelpFrom = "what";
  mode = m;
  fail = (m === "fail");
  if (m === "fail") mode = "happy";
  screen = "splash";
  owner = false;
  selected = null;
  token = "";
  keyboardLayout = "us";
  method = "everyday";
  tLeft = 5;
  demoPct = null;
  demoFrac = null;
  progressKey = "";
  showMore = false;
  if (timer) clearInterval(timer);
  draw();
}
function disks() {
  let list;
  if (mode === "blocked") list = [];
  else if (mode === "empty") list = P.disks.filter(d => d.isBoot);
  else list = P.disks.slice();
  list.sort((a, b) => (a.isBoot - b.isBoot) || a.path.localeCompare(b.path));
  return list;
}
function selectable() { return disks().filter(d => d.eligible); }
function stepInfo() {
  const stepOf = (n) => P.steps[n];
  const map = {splash:[0,"",""], keyboard:[0,"",P.titles.keyboard], what:[1,stepOf(1),P.titles.what], owner:[2,stepOf(2),P.stepOwnership],
    pick:[3,stepOf(3),P.titles.pick], blocked:[3,stepOf(3),P.titles.pick], empty:[3,stepOf(3),P.titles.pick],
    confirm:[4,stepOf(4),P.titles.confirm], method:[5,stepOf(5),P.titles.method],
    disk_help:[3,P.diskHelpTitle,P.diskHelpTitle], limits:[5,P.limitsTitle,P.limitsTitle], advanced:[5,P.titles.advanced,P.titles.advanced], last:[6,stepOf(6),P.titles.last],
    stop_confirm:[7,stepOf(7),P.stop.title], stopping:[7,stepOf(7),P.stoppingErase],
    stop_unconfirmed:[7,stepOf(7),P.stop.unconfirmed.message], stopped:[8,stepOf(8),P.stop.stopped.message],

    working:[7,stepOf(7),P.titles.working], done:[8,stepOf(8),P.titles.doneOk],
    refresh_confirm:[0,"",P.titles.refresh]};
  return map[screen] || [0,"",""];
}
function supportBlock() {
  return `<div class="support"><div aria-hidden="true">${P.supportQr}</div><p tabindex="0">${P.supportLead}</p></div>`;
}
function supportCodeBlock(code, extra) {
  const save = extra ? `<p class="row"><span class="k">${esc(P.supportSaveLabel)}</span><span class="v">${esc(extra)}</span></p>` : "";
  return `<div class="support-code" tabindex="0"><p class="row"><span class="k">${esc(P.supportCodeLabel)}</span><span class="v">${esc(code)}</span></p>${save}<p class="row"><span class="k">${esc(P.supportBuildLabel)}</span><span class="v">${esc(P.sampleBuild)}</span></p><p class="hint">${esc(P.supportCodeHint)}</p></div>`;
}
function btn(label, fn, cls, disabled) {
  const b = document.createElement("button");
  b.textContent = label;
  b.className = "btn " + (cls || "secondary");
  b.disabled = !!disabled;
  b.onclick = fn;
  return b;
}
function closePreview() {
  anotherPending = false;
  if (reportWanted && screen !== "shutdown_confirm") {
    shutdownFrom = screen; screen = "shutdown_confirm"; draw(); return;
  }
  alert(P.chrome.closeTab);
}
function tokenOk() {
  return selected && token.trim().toLowerCase() === selected.token.toLowerCase();
}
function panel(kind, text, compact = false) {
  const sev = {warn: P.sevWarning, danger: P.sevError, ok: P.sevSaved, limits: P.sevLimits}[kind];
  const role = kind === "warn" || kind === "danger" ? ' role="alert"'
    : kind === "ok" ? ' role="status"' : kind === "limits" ? ' role="note"' : "";
  const label = sev ? `<div class="sev">${esc(sev)}</div>` : "";
  return `<div class="panel ${kind}${compact ? " compact-notice" : ""}"${role}>${badge(kind, 28)}<div>${label}${esc(text)}</div></div>`;
}
function moreLink(controlsId) {
  const controls = controlsId ? ` aria-controls="${controlsId}"` : "";
  return `<button type="button" class="linkbtn morelink" id="more" aria-expanded="${showMore}"${controls}>${showMore ? P.buttons.less : P.buttons.more}</button>`;
}
function bindMore() {
  const el = document.getElementById("more");
  if (el) el.onclick = () => { showMore = !showMore; draw(); document.getElementById("more").focus(); };
}
function moreDetail(html) {
  return `<div id="more-detail">${html || ""}</div>`;
}
function esc(s) {
  return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}
function recoveryHtml(sections) {
  if (!sections) return "";
  const L = P.recoveryLabels;
  let html = `<section class="recovery">
    <h2>${esc(L.happened)}</h2><p>${esc(sections.happened)}</p>
    <h2>${esc(L.meaning)}</h2><p>${esc(sections.meaning)}</p>
    <h2>${esc(L.next)}</h2><p>${esc(sections.next)}</p>`;
  if (sections.technical) {
    html += `<details class="recovery-tech"><summary>${esc(L.technical)}</summary>
      <p class="small muted">${esc(sections.technical)}</p></details>`;
  }
  return html + `</section>`;
}
function metaLine(d, opts) {
  const detailId = opts && opts.detailId;
  const notes = [d.missingNote, d.duplicateNote, d.ambiguousNote, d.connectionNote, screen === "pick" ? d.comparisonNote : ""].filter(Boolean)
    .map(note => `<div class="small muted">${esc(note)}</div>`).join("");
  const extra = showMore
    ? `<div class="small muted more-path"${detailId ? ` id="${detailId}"` : ""}>${esc(P.pathNote)}: ${esc(d.path)}</div>`
    : (detailId ? `<div id="${detailId}" hidden></div>` : "");
  return `<div class="meta"><span class="serialpair"><span class="serial-label">${esc(d.idLabel || P.serialLabel)}</span><span class="mono ser">${esc(screen === "pick" && !d.isBoot ? d.markedSerial || d.serial : d.serial)}</span></span>
    <span class="disktype">${esc(d.kindLabel)}</span>
    <div class="connection"><span class="serial-label">${esc(P.connectionLabel)}</span><span>${esc(d.connection || d.bus)}</span></div>${notes}${extra}</div>`;
}
function summaryCard(d) {
  return `<div class="card hero identity"><div class="identity-label">${P.selectedDisk}</div><div class="row" style="align-items:flex-start">
    <div class="title grow">${esc(d.name)}</div>
    <div class="size">${esc(d.size)}</div></div>
    ${metaLine(d, {detailId: "more-detail"})}
  </div>`;
}
function nestedComponents(d) {
  const items = d.components || [];
  if (!items.length) return "";
  return `<div class="nested">
    <div class="nested-intro">${esc(P.nestedIntro)}</div>
    ${items.map(c => `<div class="nested-item"><div>${esc(c.heading)}</div>${c.reason ? `<div>${esc(c.reason)}</div>` : ""}</div>`).join("")}
  </div>`;
}
function diskCard(d) {
  const sel = selected && selected.path === d.path;
  const cls = d.isBoot ? "card boot" : ("card pickable" + (sel ? " sel" : ""));
  const icon = d.isBoot ? `<span class="radio" style="border:0;background:none">${ICON_NO}</span>` : `<span class="radio"></span>`;
  // Use esc for attribute to prevent `"` breakout
  return `<div class="${cls}" data-path="${esc(d.path)}" ${d.isBoot ? `role="region" aria-label="${esc(d.bus === "USB" ? P.bootUsb : P.bootDisc)}"` : `tabindex="0" role="button" aria-pressed="${!!sel}"`}>
    <div class="row">${icon}
      <div class="grow">
        ${d.isBoot ? `<div class="bootbanner">${esc(d.bus === "USB" ? P.bootUsb : P.bootDisc)}</div>` : ""}
        <div class="row" style="align-items:flex-start">
          <div class="title grow">${esc(d.name)}</div>
          <div class="size">${esc(d.size)}</div>
        </div>
        ${metaLine(d)}
        ${nestedComponents(d)}
      </div>
    </div>
  </div>`;
}
function requestRefresh() {
  if (["working", "done", "splash", "stop_confirm", "stopping", "stopped", "stop_unconfirmed", "shutdown_confirm"].includes(screen)) return;
  if (screen === "refresh_confirm") return;
  refreshFrom = screen;
  screen = "refresh_confirm";
  draw();
}
function refreshPreview() {
  reportHelpFrom = "what";
  if (["working", "done", "splash"].includes(screen)) return;
  if (timer) clearInterval(timer);
  timer = null; selected = null; token = ""; owner = false;
  method = "everyday"; tLeft = 5; showMore = false; demoPct = null; demoFrac = null; progressKey = ""; screen = "what";
  draw();
}
function headerCaption(info) {
  const n = info[0], label = info[1];
  if (n && String(label).indexOf(P.stepPrefix) === 0) return P.journey[n - 1] + " · " + label;
  return label;
}
function applyTextSize() {
  const shell = document.querySelector(".shell");
  if (shell) shell.setAttribute("data-text", textSize);
}
function draw() {
  applyTextSize();
  // Countdown redraws must preserve deliberate keyboard focus. Entering
  // final review always starts on Back, including screenshot deep links.
  const reviewFocus = screen === "last" && renderedScreen === "last"
    && document.activeElement.matches(".foot button") ? document.activeElement.textContent : null;
  const info = stepInfo();
  const stepEl = document.getElementById("step");
  document.getElementById("journey").innerHTML = info[0]
    ? `<li aria-current="step">${esc(headerCaption(info))}</li>` : "";
  stepEl.textContent = headerCaption(info);
  stepEl.style.visibility = stepEl.textContent ? "visible" : "hidden";
  document.getElementById("sfill").style.width = (info[0] / 8 * 100) + "%";
  const main = document.getElementById("main");
  const btnsL = document.getElementById("btnsL");
  const btnsR = document.getElementById("btnsR");
  const foot = document.getElementById("foot");
  main.innerHTML = "";
  const utilities = document.getElementById("utilities");
  utilities.innerHTML = "";
  btnsL.innerHTML = "";
  btnsR.innerHTML = "";
  // The splash keeps the white field clean: no header, no progress strip,
  // no footer — just the mark, the type, and one action.
  const splash = screen === "splash";
  document.querySelector(".hdr").style.display = splash ? "none" : "";
  document.querySelector(".strip").style.display = splash ? "none" : "";
  foot.style.display = splash ? "none" : "";
  renderHint(P.hints.default);
  if (screen === "splash") {
    main.innerHTML = `<div class="splashwrap">
      <div class="marktile">${EMBLEM}</div>
      <div class="wordmark">${P.app}</div>
      <p class="splashlead">${P.splash}</p><p class="splash-roadmap">${P.splashRoadmap}</p>
      <button class="btn primary" id="herogo">${P.buttons.continue}</button>
      <div class="anykeycap">${P.hints.splash}</div></div>`;
    main.querySelector("#herogo").onclick = () => { screen = "keyboard"; draw(); };
  } else if (screen === "keyboard") {
    const layouts = P.keyboardLayouts.map((item, i) => {
      const selected = (keyboardLayout || "us") === item.id;
      return `<div class="card pickable${selected ? " sel" : ""}" data-layout="${item.id}" tabindex="0" role="button" aria-pressed="${selected}"><div class="row"><span class="radio"></span><div class="grow"><div class="title">${item.title}</div><p class="small muted">${item.note}</p></div><span class="kbd">${i+1}</span></div></div>`;
    }).join("");
    const sizes = P.textSizes.map(item => `<button type="button" class="btn${textSize === item.id ? " primary" : ""}" data-text="${item.id}">${item.label}</button>`).join("");
    const langs = P.languages.map(l => `<div class="small">${l.active ? ">" : "&nbsp;"} ${l.name}</div>`).join("");
    main.innerHTML = `<h1 class="sub">${P.titles.keyboard}</h1><p class="subtitle">${P.keyboardLead}</p>
      <p class="small muted">${P.keyboardLimits}</p>
      <p class="small">${P.textSizeLead}</p>
      <div class="textsizes">${sizes}</div>
      <div class="cz"><div class="czc">${layouts}
      <p class="small" style="margin-top:12px"><strong>${P.languageTitle}</strong></p>
      <p class="small muted">${P.languageLead}</p>${langs}
      <p class="small">${P.keyboardCheck}</p>
      <div class="entryshell"><input class="token" id="kbcheck" type="text" autocomplete="off" spellcheck="false" value=""></div>
      </div></div>`;
    main.querySelectorAll("[data-layout]").forEach(el => {
      const pick = () => { keyboardLayout = el.dataset.layout; owner = false; token = ""; selected = null; draw(); };
      el.onclick = pick;
      el.onkeydown = (e) => { if (e.key === " " || e.key === "Enter") { e.preventDefault(); pick(); } };
    });
    main.querySelectorAll("[data-text]").forEach(el => {
      el.onclick = () => { textSize = el.dataset.text; draw(); };
    });
    const box = main.querySelector("#kbcheck");
    if (box) box.value = "";
    btnsL.append(btn(P.buttons.closePreview, closePreview, "secondary"));
    renderHint(P.hints.keyboard);
    btnsR.append(btn(P.buttons.continue, () => { screen = "what"; draw(); }, "primary"));
  } else if (screen === "what") {
    main.innerHTML = `<h1 class="sub">${P.titles.what}</h1><p class="subtitle">${P.whatLead}</p><div class="cz"><div class="czc">
      <ul class="bullets">${P.what.map(x=>"<li>"+x+"</li>").join("")}</ul>
      <div style="margin-top:12px">${panel("info", P.reportMediaWhat, true)}</div>
      <div class="panel info" style="margin-top:12px">${badge("info", 28)}<div>
      <div>${P.powerReminder}</div><div class="extra">${P.powerBlanking}</div>
      <div id="power-status" role="status" aria-live="polite">${powerText()}</div></div></div>
      ${moreLink("more-detail")}
      ${moreDetail(showMore ? `<div class="panel info" style="margin-top:12px">${badge("info", 28)}<div>
      <div>${P.secureBoot}</div><div class="extra">${P.engine} ${P.powerEvents}</div></div></div>` : "")}</div></div>`;
    bindMore();
    btnsL.append(btn(P.buttons.closePreview, closePreview, "secondary"));
    btnsR.append(btn(P.buttons.understand, () => { screen = "owner"; draw(); }, "primary"));
  } else if (screen === "owner") {
    main.innerHTML = `<h1 class="sub">${P.titles.owner}</h1>
      <p class="subtitle">${P.ownerLead}</p>
      <div class="cz"><div class="czc"><div class="ownercard${owner ? " checked" : ""}" id="own" tabindex="0" role="checkbox" aria-checked="${owner}">
        <span class="cbox">${owner ? "✓" : ""}</span><span>${P.owner}</span></div></div></div>`;
    const card = main.querySelector("#own");
    const toggle = () => { owner = !owner; draw(); document.getElementById("own").focus(); };
    card.onclick = toggle;
    card.onkeydown = (e) => { if (e.key === " ") { e.preventDefault(); toggle(); } };
    btnsL.append(btn(P.buttons.back, () => { screen = "what"; draw(); }));
    renderHint(P.hints.owner);
    btnsR.append(btn(P.buttons.continue, () => { if (owner) { if (mode==="blocked") screen="blocked"; else if (!selectable().length) screen="empty"; else screen="pick"; draw(); } }, "primary", !owner));
  } else if (screen === "blocked") {
    main.innerHTML = `<div class="centerstage"><div class="badgehalo danger">${badge("danger", 51)}</div>
      <h1>${P.titles.blocked}</h1>${recoveryHtml(P.blockedRecovery)}${supportCodeBlock(P.sampleBlockedCode)}</div>`;
    btnsL.append(btn(P.buttons.back, () => { screen = "owner"; draw(); }));
    btnsR.append(btn(P.buttons.closePreview, closePreview, "primary"));
  } else if (screen === "empty") {
    let html = `<div class="centerstage"><div class="badgehalo info">${badge("info", 51)}</div>
      <h1>${P.titles.empty}</h1>${recoveryHtml(P.emptyRecovery)}${supportBlock()}${supportCodeBlock(P.sampleEmptyCode)}</div>`;
    html += `<div class="disklist">` + disks().map(diskCard).join("") + `</div>`;
    main.innerHTML = html;
    renderOtherDevices();
    btnsL.append(btn(P.buttons.back, () => { screen = "owner"; draw(); }));
    btnsR.append(btn(P.buttons.closePreview, closePreview, "primary"));
  } else if (screen === "pick") {
    let html = `<h1 class="sub">${P.titles.pick}</h1><p class="subtitle">${P.pickSubtitle}</p>`;
    if (P.sameSizeConflict && mode === "happy") html += `<div style="margin-bottom:12px">${panel("warn", P.sameSize)}</div>`;
    if (selected && (selected.kind === "SSD" || selected.kind === "NVMe")) html += `<div style="margin-bottom:12px">${panel("limits", P.ssd, true)}</div>`;
    if (reportWanted) html += `<div style="margin-bottom:12px">${panel("info", P.reportMediaWanted, true)}</div>`;
    html += `<div class="pick-tools"><span class="small muted">${selectable().length} ${selectable().length === 1 ? "disk available" : "disks available"} · ${selected ? "1 selected" : "Choose one disk"}</span>${moreLink()}</div>`;
    html += `<div class="disklist">`;
    disks().filter(d => d.isBoot).forEach(d => { html += diskCard(d); });
    if (selectable().length > 1) html += `<details class="compare"><summary>${esc(P.compareTitle)}</summary><div class="compare-body"><p>${esc(P.compareIntro)}</p><div class="compare-grid">${P.comparison.map(text => `<pre class="compare-pre" tabindex="0">${esc(text)}</pre>`).join("")}</div></div></details>`;
    selectable().forEach(d => { html += diskCard(d); });
    html += `</div>`;
    main.innerHTML = html;
    const unsure = btn(P.diskHelpButton, () => {
      if (screen !== "pick") return;
      selected = null; token = ""; tLeft = 5;
      if (timer) clearInterval(timer);
      timer = null; screen = "disk_help"; draw();
    }, "ghost");
    unsure.id = "unsure-disk";
    main.querySelector(".subtitle").after(unsure);
    renderOtherDevices();
    bindMore();
    main.querySelectorAll(".card.pickable").forEach(el => {
      const pick = () => {
        if (screen !== "pick") return;
        selected = disks().find(d => d.path === el.dataset.path);
        draw();
        Array.from(main.querySelectorAll(".card.pickable"))
          .find(card => card.dataset.path === selected.path).focus();
      };
      el.onclick = pick;
      el.onkeydown = (e) => { if (e.key === " " || e.key === "Enter") { e.preventDefault(); pick(); } };
    });
    renderHint(P.hints.pick);
    btnsL.append(btn(P.buttons.back, () => { screen = "owner"; draw(); }));
    btnsR.append(btn(P.buttons.continue, () => { if (selected && !selected.isBoot) { screen = "confirm"; token=""; draw(); } }, "primary", !(selected && !selected.isBoot)));
  } else if (screen === "confirm") {
    const d = selected;
    main.innerHTML = `<h1>${P.titles.confirm}</h1><div class="cz"><div class="czc">
      ${summaryCard(d)}
      ${moreLink("more-detail")}
      <div style="margin-top:12px">${panel("warn", d.warning)}</div>
      <p class="small muted" style="margin-top:8px">${P.confirmKeyboard}</p>
      <p style="font-size:16px;margin:14px 0 8px;overflow-wrap:anywhere"><label for="tok">${esc(d.prompt)}</label></p>
      <div class="entryshell"><input class="token" id="tok" aria-describedby="match" autocomplete="off" spellcheck="false"></div>
      <p class="match" id="match" role="status" aria-live="polite"></p></div></div>`;
    bindMore();
    const inp = main.querySelector("#tok");
    const matchEl = main.querySelector("#match");
    inp.value = token;
    const sync = () => {
      token = inp.value;
      const cont = document.getElementById("cont");
      if (cont) cont.disabled = !tokenOk();
      if (tokenOk()) { matchEl.innerHTML = MATCH_OK + "<span>" + P.matchOk + "</span>"; matchEl.className = "match ok"; }
      else { matchEl.innerHTML = MATCH_WAIT + "<span>" + P.matchWait + "</span>"; matchEl.className = "match"; }
    };
    inp.oninput = sync;
    inp.onkeydown = (e) => { if (e.key === "Enter" && tokenOk()) { e.preventDefault(); screen = "method"; draw(); } };
    sync();
    setTimeout(() => { inp.focus(); inp.setSelectionRange(token.length, token.length); }, 0);
    renderHint(P.hints.confirm);
    btnsL.append(btn(P.buttons.back, () => { screen = "pick"; draw(); }));
    const cont = btn(P.buttons.continue, () => { if (tokenOk()) { screen = "method"; draw(); } }, "primary", !tokenOk());
    cont.id = "cont";
    btnsR.append(cont);
  } else if (screen === "method") {
    let html = `<h1 class="compact sub">${P.titles.method}</h1><p class="subtitle" style="margin-bottom:6px">${P.methodLead}</p>${selected ? summaryCard(selected) + moreLink("more-detail") : ""}<div id="storage-notice" role="note">${panel("limits", selected ? selected.storageNotice : P.ssd, true)}</div><button id="limits" class="linkbtn" aria-describedby="storage-notice">${P.limitsButton}</button><div class="cz"><div class="czc">`;
    ["everyday","extra","quick_zero"].forEach(id => {
      const m = P.methods[id];
      const sel = method === id;
      html += `<div class="card pickable${sel ? " sel" : ""}" data-id="${id}" tabindex="0" role="button" aria-pressed="${sel}" style="padding-top:9px;padding-bottom:9px;margin-bottom:8px">
        <div class="row"><span class="radio"></span>
          <div class="grow">
            <div class="title">${m.title}${id === "everyday" ? `<span class="chip ok">${P.recommended}</span>` : (m.mark ? `<span class="chip${m.checks ? "" : " warn"}">${m.mark}</span>` : "")}</div>
            <div class="methodblurb">${m.blurb}</div>
            <div class="methodpace">${m.checks ? `<svg width="16" height="16" viewBox="0 0 16 16"><circle cx="8" cy="8" r="6.5" fill="none" stroke="#4A5A6A" stroke-width="1.6"/><path d="M8 4.2V8l2.6 1.7" fill="none" stroke="#4A5A6A" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>` : ""}<span>${m.pace}</span></div>
            ${m.extra ? `<div class="methodextra">${m.extra}</div>` : ""}
          </div>
          <span class="kbd">${m.key}</span>
        </div>
      </div>`;
    });
    html += `<button class="linkbtn" id="adv">${P.buttons.advanced}</button></div></div>`;
    main.innerHTML = html;
    bindMore();
    main.querySelectorAll(".card.pickable").forEach(el => {
      const pick = () => { method = el.dataset.id; draw(); };
      el.onclick = pick;
      el.onkeydown = (e) => { if (e.key === " " || e.key === "Enter") { e.preventDefault(); pick(); } };
    });
    main.querySelector("#limits").onclick = () => { screen = "limits"; draw(); };
    main.querySelector("#adv").onclick = () => { screen = "advanced"; draw(); };
    renderHint(P.hints.method);
    btnsL.append(btn(P.buttons.back, () => { screen = "confirm"; draw(); }));
    btnsR.append(btn(P.buttons.continue, () => { screen = "last"; tLeft = 5; startCount(); draw(); }, "primary"));
  } else if (screen === "refresh_confirm") {
    main.innerHTML = `<h1 class="sub">${P.titles.refresh}</h1><p class="subtitle">${P.refreshLead}</p>`;
    btnsL.append(btn(P.buttons.back, () => { screen = refreshFrom; draw(); }));
    const go = btn(P.refreshButton, refreshPreview, "primary");
    btnsR.append(go);
    renderHint(P.refreshHint);
    go.focus();
  } else if (screen === "shutdown_confirm") {
    main.innerHTML = `<h1>${anotherPending ? P.anotherTitle : P.shutdownTitle}</h1><p>${anotherPending ? P.anotherLoss : P.shutdownLoss}</p>
      <h2>${esc(P.mediaStepsTitle)}</h2><p style="white-space:pre-wrap">${esc(anotherPending ? P.mediaStepsAnother : P.mediaSteps)}</p>`;
    btnsL.append(btn(anotherPending ? P.anotherDiscard : P.shutdownDiscard, () => {
      if (anotherPending) { anotherPending = false; boot(fail ? "fail" : mode); }
      else alert(P.chrome.closeTab);
    }));
    const keep = btn(P.shutdownKeep, () => { screen = shutdownFrom; draw(); }, "primary");
    btnsR.append(keep);
    renderHint(P.shutdownHint);
    keep.focus();
  } else if (screen === "report_help") {
    main.innerHTML = `<h1>${P.reportHelpTitle}</h1><div id="report-text" class="help-reader compact" role="region" aria-label="Report requirements" tabindex="0"></div>
      <div class="checkrow${reportWanted ? " checked" : ""}" id="report-wanted" tabindex="0" role="checkbox" aria-checked="${reportWanted}"><span class="cbox">${reportWanted ? "✓" : ""}</span><span>${P.reportWanted}</span></div>`;
    main.querySelector("#report-text").textContent = P.reportHelpText;
    const wanted = main.querySelector("#report-wanted");
    const syncWanted = () => {
      wanted.classList.toggle("checked", reportWanted);
      wanted.setAttribute("aria-checked", reportWanted);
      wanted.querySelector(".cbox").textContent = reportWanted ? "✓" : "";
    };
    wanted.onclick = () => { reportWanted = !reportWanted; syncWanted(); };
    wanted.onkeydown = (e) => { if (e.key === " " || e.key === "Enter") { e.preventDefault(); reportWanted = !reportWanted; syncWanted(); } };
    btnsL.append(btn(P.buttons.back, () => { screen = reportHelpFrom; draw(); }));
    renderHint("Nothing is saved here. Esc returns.");
  } else if (screen === "disk_help") {
    main.innerHTML = `<h1>${P.diskHelpTitle}</h1><div id="disk-help-text" class="help-reader" role="region" aria-label="Identify the disk" tabindex="0"></div>`;
    main.querySelector("#disk-help-text").textContent = P.diskHelpText;
    main.querySelector("#disk-help-text").focus();
    btnsL.append(btn(P.buttons.back, () => { screen = "pick"; draw(); main.querySelector("#unsure-disk").focus(); }));
    btnsR.append(btn(P.diskHelpStop, closePreview));
    renderHint("Esc returns with no disk selected.");
  } else if (screen === "limits") {
    main.innerHTML = `<h1>${P.limitsTitle}</h1><div id="limits-text" class="help-reader" role="region" aria-label="Supported storage limits" tabindex="0"></div>`;
    main.querySelector("#limits-text").textContent = P.limitsText;
    main.querySelector("#limits-text").focus();
    btnsL.append(btn(P.buttons.back, () => { screen = "method"; draw(); main.querySelector("#limits").focus(); }));
  } else if (screen === "advanced") {
    let html = `<h1 class="compact sub">${P.titles.advanced}</h1><p class="subtitle" style="margin-bottom:6px">${P.advancedLead}</p><div class="cz"><div class="czc"><div class="card hero" style="padding:12px 20px">`;
    ["everyday","extra","quick_zero"].forEach(id => {
      const m = P.methods[id];
      html += `<p class="mono advrow">${id}: nwipe --method=${m.nwipe} &nbsp;(${m.docs})</p>`;
    });
    html += `</div><p class="muted small" style="margin:14px 0 4px">${P.advancedLogLabel}<span class="mono" style="color:var(--ink)">${P.noWipeYet}</span></p>
      <p class="muted small">${P.advancedNote}</p></div></div>`;
    main.innerHTML = html;
    btnsL.append(btn(P.buttons.back, () => { screen = "method"; draw(); }));
    btnsR.append(btn(P.buttons.continue, () => { screen = "method"; draw(); }, "primary"));
  } else if (screen === "last") {
    if (!selected) { screen = "pick"; draw(); return; }
    const ready = tLeft <= 0;
    const CIRC = 2 * Math.PI * 81;
    const frac = ready ? 1 : Math.max(0, Math.min(1, tLeft / 5));
    const ringColor = "var(--primary)";
    main.innerHTML = `<h1 class="sub">${P.titles.last}</h1><p class="subtitle">${P.lastLead}</p>
      <div class="review-grid"><div>${summaryCard(selected)}<p style="font-weight:700">${esc(P.methods[method].operation)}</p><p class="review-warning">${P.sevWarning}: ${esc(selected.eraseLabel)}</p><p class="small">${P.methods[method].summary}</p>${powerPanel()}</div><div class="ringwrap"><div style="position:relative;width:64px;height:64px">
        <svg width="64" height="64" viewBox="0 0 190 190">
          <circle cx="95" cy="95" r="81" fill="none" stroke="var(--track)" stroke-width="11"/>
          ${ready ? `<circle cx="95" cy="95" r="81" fill="none" stroke="var(--primary)" stroke-width="11"/>` :
            `<circle cx="95" cy="95" r="81" fill="none" stroke="${ringColor}" stroke-width="11" stroke-linecap="round"
              stroke-dasharray="${CIRC}" stroke-dashoffset="${CIRC * (1 - frac)}" transform="rotate(-90 95 95)"/>`}
        </svg>
        <div class="ringnum" style="${ready ? "color:var(--primary)" : ""}">${ready ? "0" : tLeft}</div></div>
      <div class="countcap${ready ? " ready" : ""}">${ready ? P.countdownReady : P.countdownCaption}</div></div></div>`;
    btnsL.append(btn(P.buttons.back, () => { if (timer) clearInterval(timer); screen = "method"; draw(); }));
    btnsR.append(btn(P.buttons.erase, () => { if (tLeft<=0) startWork(); }, "danger", tLeft>0));
    renderHint(P.hints.lastChance);
  } else if (screen === "working") {
    if (!selected) { screen = "pick"; draw(); return; }
    const m = P.methods[method];
    const state = currentProgress();
    const known = state.percent != null;
    const fillPct = known ? Math.max(2, state.percent) : 30;
    main.innerHTML = `<h1>${P.titles.working}</h1>
      ${summaryCard(selected)}
      ${moreLink("more-detail")}
      <div class="cz"><div class="czc">
      <div class="progress-card"><div class="progress-label">${P.eraseProgress}</div>
      <div class="bigstat" id="pct" style="margin:0 0 12px">${esc(state.percentText)}</div>
      <div class="bar"><div class="fill${state.animate ? " indet" : ""}" id="fill" style="width:${fillPct}%"></div></div>
      <p class="progress-timing" id="pulse">${esc(state.timingText)}</p>
      <div id="power-status" role="status" aria-live="polite" class="small muted">${powerText()}</div>
      <p class="small muted">${m.summary}</p>
      <p class="small muted" id="soundsNote" role="status"></p></div></div></div>`;
    bindMore();
    btnsL.append(btn(P.stop.ask, () => {
      if (screen === "working") { screen = "stop_confirm"; draw(); }
    }));
    btnsL.append(btn(soundsOn ? P.sounds.toggleOn : P.sounds.toggleOff, function() {
      soundsOn = !soundsOn;
      this.textContent = soundsOn ? P.sounds.toggleOn : P.sounds.toggleOff;
      document.getElementById("soundsNote").textContent = this.textContent;
    }));
    btnsL.append(btn(P.sounds.hear, () => {
      document.getElementById("soundsNote").textContent = P.sounds.offLive;
    }));
    renderHint(P.hints.working);
  } else if (["stop_confirm", "stopping", "stopped", "stop_unconfirmed"].includes(screen)) {
    const result = screen === "stopped" ? P.stop.stopped : P.stop.unconfirmed;
    const title = screen === "stop_confirm" ? P.stop.title : screen === "stopping" ? P.stoppingErase : result.message;
    const recovery = screen === "stopped" ? P.stop.stoppedRecovery
      : screen === "stop_unconfirmed" ? P.stop.unconfirmedRecovery : null;
    const detail = screen === "stop_confirm" ? P.stop.lead : screen === "stopping" ? P.stop.stopping : "";
    const stopSupport = (screen === "stopped" || screen === "stop_unconfirmed") ? supportBlock() : "";
    const stopProgress = screen === "stopping" ? P.progress.states.stopping : "";
    main.innerHTML = `<h1 tabindex="-1" id="stop-heading">${title}</h1>
      ${recovery ? recoveryHtml(recovery) : `<p role="status" aria-live="polite">${detail}</p>`}
      <p>Preview only. Nothing on this computer was erased.</p>
      ${selected ? summaryCard(selected) : ""}
      ${stopProgress ? `<p class="progress-timing" id="stop-timing">${esc(stopProgress.timingText)}</p>` : ""}
      ${stopSupport}
      <p class="small muted" id="stop-method">${P.methods[method].operation}</p>`;
    renderHint("Keep the disk and Beamo USB connected.");
    if (screen === "stop_confirm") {
      const confirmation = main.firstElementChild;
      const keep = btn(P.stop.keep, () => {
        if (screen !== "stop_confirm" || main.firstElementChild !== confirmation) return;
        screen = "working"; draw();
      }, "primary");
      btnsL.append(keep);
      btnsR.append(btn(P.stop.confirm, () => {
        if (screen !== "stop_confirm" || main.firstElementChild !== confirmation) return;
        if (timer) clearInterval(timer);
        screen = "stopping"; draw();
        timer = setTimeout(() => { screen = "stopped"; draw(); }, 1500);
      }, "danger"));
      keep.focus();
    } else {
      main.querySelector("#stop-heading").focus();
      if (screen === "stop_unconfirmed")
        btnsL.append(btn("Review stop again (preview)", () => { screen = "stop_confirm"; draw(); }));
      if (screen === "stopped")
        btnsR.append(btn(P.buttons.runAgain, () => boot(mode), "primary"));
    }
  } else if (screen === "done") {
    if (!selected) { screen = "pick"; draw(); return; }
    const ok = !fail;
    const result = P.previewResults[ok ? "ok" : "failed"];
    const recovery = ok ? "" : recoveryHtml(result.recovery);
    main.innerHTML = `<div class="result"><div class="status" aria-hidden="true"><div class="core">i</div></div>
      <section aria-labelledby="erase-status-heading"><h1 id="erase-status-heading">${result.message}</h1>
      ${ok ? `<p class="statustext" style="color:var(--ink)">${result.next_step}</p>` : recovery}
      <p>${P.methods[method].summary}</p>
      </section>
      <div style="width:100%;margin-top:12px">${summaryCard(selected)}</div>
      <section aria-labelledby="report-status-heading">
      <h2 id="report-status-heading">${P.reportStatusTitle}</h2>
      <p>${P.reportPreview}</p><p class="small">${P.reportStatusNotice}</p></section>
      <p class="small muted" id="soundsNote" role="status"></p>
      ${moreLink("more-detail")}</div>`;
    bindMore();
    utilities.append(btn(P.eraseAnother, () => {
      if (screen !== "done") return;
      anotherPending = true; shutdownFrom = "done"; screen = "shutdown_confirm"; draw();
    }, "secondary"));
    btnsL.append(btn(P.buttons.closePreview, closePreview, "secondary"));
    btnsL.append(btn(soundsOn ? P.sounds.toggleOn : P.sounds.toggleOff, function() {
      soundsOn = !soundsOn;
      this.textContent = soundsOn ? P.sounds.toggleOn : P.sounds.toggleOff;
      document.getElementById("soundsNote").textContent = this.textContent;
    }));
    btnsL.append(btn(P.sounds.hearAgain, () => {
      document.getElementById("soundsNote").textContent = P.sounds.offLive;
    }));
    btnsR.append(btn(P.buttons.runAgain, () => boot(fail ? "fail" : mode), "primary"));
  }
  if (["what", "method", "advanced"].includes(screen)) {
    utilities.append(btn(P.reportHelpTitle, () => { reportHelpFrom = screen; screen = "report_help"; draw(); }, "ghost"));
  }
  if (!["working", "stop_confirm", "stopping", "stopped", "stop_unconfirmed", "done", "splash", "shutdown_confirm", "refresh_confirm"].includes(screen)) {
    utilities.prepend(btn(P.refreshUtility, requestRefresh, "ghost"));
  }
  if (!["splash", "keyboard", "working", "stop_confirm", "stopping", "stopped", "stop_unconfirmed", "done", "shutdown_confirm", "refresh_confirm"].includes(screen)) {
    const current = (P.textSizes.find(s => s.id === textSize) || P.textSizes[0]).label;
    utilities.append(btn(`${P.textSizeUtility}: ${current}`, () => {
      const ids = P.textSizes.map(s => s.id);
      const i = Math.max(0, ids.indexOf(textSize));
      textSize = ids[(i + 1) % ids.length];
      draw();
    }, "ghost"));
  }
  if (screen === "last") {
    const focused = Array.from(foot.querySelectorAll("button"))
      .find(button => button.textContent === reviewFocus && !button.disabled);
    (focused || btnsL.querySelector("button")).focus();
  }
  renderedScreen = screen;
}
document.addEventListener("keydown", e => {
  if (["working", "stop_confirm"].includes(screen) && e.key === "Escape") {
    e.preventDefault();
    if (!e.repeat) { screen = screen === "working" ? "stop_confirm" : "working"; draw(); }
    return;
  }
  if (screen === "stop_confirm" && e.repeat && ["Enter", " "].includes(e.key)) {
    e.preventDefault(); return;
  }
  if (screen === "refresh_confirm" && e.key === "Escape") {
    e.preventDefault(); screen = refreshFrom; draw(); return;
  }
  if (screen === "shutdown_confirm" && ["Escape", "Enter"].includes(e.key)) {
    e.preventDefault(); screen = shutdownFrom; draw(); return;
  }
  if (screen === "disk_help" && e.key === "Escape") {
    e.preventDefault(); screen = "pick"; draw(); main.querySelector("#unsure-disk").focus(); return;
  }
  if (screen === "report_help" && e.key === "Escape") {
    e.preventDefault(); screen = reportHelpFrom; draw(); return;
  }
  if (e.key === "F5" && !e.repeat && !["working", "stop_confirm", "stopping", "stopped", "stop_unconfirmed", "done", "splash", "shutdown_confirm"].includes(screen)) {
    e.preventDefault();
    if (screen === "refresh_confirm") refreshPreview();
    else requestRefresh();
    return;
  }
  if (screen === "method" && e.key.toLowerCase() === "l") {
    e.preventDefault(); screen = "limits"; draw();
  } else if (screen === "limits" && e.key === "Escape") {
    e.preventDefault(); screen = "method"; draw(); main.querySelector("#limits").focus();
  }
});
function renderOtherDevices() {
  const section = document.createElement("section");
  section.setAttribute("aria-label", P.otherTitle);
  const heading = document.createElement("h2");
  heading.textContent = P.otherTitle;
  const text = document.createElement("div");
  text.tabIndex = 0;
  text.className = "inventory-reader";
  text.textContent = P.otherDevices[mode === "empty" ? "empty" : "happy"];
  section.append(heading, text);
  const list = main.querySelector(".disklist");
  (list || main).append(section);
}
function startCount() {
  if (timer) clearInterval(timer);
  timer = setInterval(() => {
    tLeft -= 1;
    if (tLeft <= 0) { tLeft = 0; clearInterval(timer); }
    if (screen === "last") draw();
  }, 1000);
}
function currentProgress() {
  if (progressKey && P.progress.states[progressKey]) return P.progress.states[progressKey];
  const frames = (P.progress.demo[method] || P.progress.demo.everyday);
  if (demoFrac === null && demoPct === null) return frames[0].state;
  const frac = demoFrac !== null ? demoFrac : Math.min(0.96, Math.max(0, Number(demoPct) / 100));
  let chosen = frames[0];
  for (const frame of frames) if (frame.frac <= frac) chosen = frame;
  return chosen.state;
}
function startWork() {
  screen = "working";
  progressKey = "";
  demoPct = null;
  demoFrac = null;
  draw();
  const frames = P.progress.demo[method] || P.progress.demo.everyday;
  let i = 0;
  if (timer) clearInterval(timer);
  timer = setInterval(() => {
    i += 1;
    if (i >= frames.length) {
      clearInterval(timer);
      timer = null;
      if (screen === "working" || screen === "stop_confirm") { screen = "done"; draw(); }
      return;
    }
    demoFrac = frames[i].frac;
    demoPct = frames[i].state.percent;
    if (screen === "working") draw();
  }, 280);
}
// Deep-link for screenshot verification, e.g.:
// #scenario=happy&s=confirm&disk=0&typed=1  ·  #s=last&ready=1  ·  #s=working&pct=42
// #s=working&progress=stale  ·  #s=working&more=1  ·  #s=stopping&disk=0
function applyHash() {
  const q = new URLSearchParams(location.hash.slice(1));
  const scenario = q.get("scenario") || "happy";
  boot(scenario);
  const di = q.get("disk");
  if (di !== null) selected = selectable()[parseInt(di, 10)] || null;
  if (q.get("typed") === "1" && selected) token = selected.token;
  if (q.get("owner") === "1") owner = true;
  if (q.get("method")) method = q.get("method");
  if (q.get("ready") === "1") tLeft = 0;
  if (q.get("text")) textSize = q.get("text");
  if (q.get("progress") && P.progress.states[q.get("progress")]) progressKey = q.get("progress");
  if (q.get("pct")) {
    const n = parseInt(q.get("pct"), 10);
    if (Number.isFinite(n)) {
      progressKey = "";
      demoFrac = Math.min(0.96, Math.max(0, n / 100));
      demoPct = n >= 100 ? 99.9 : n;
    }
  }
  if (q.get("more") === "1") showMore = true;
  reportWanted = q.get("report") === "1";
  const s = q.get("s");
  if (s === "disk_help") { selected = null; token = ""; tLeft = 5; }
  if (s) { screen = s; draw(); }
}
if (location.hash) applyHash(); else boot("happy");
</script>
</body>
</html>
"""
