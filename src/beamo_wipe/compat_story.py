# SPDX-License-Identifier: GPL-3.0-or-later
"""Current USB-image customer story. Not the historical compatibility matrix."""

from __future__ import annotations

import html
from typing import Any, Mapping, TypedDict

from beamo_wipe import __version__

# Status labels duplicated from build_identity so this module can hold customer
# copy without importing safety/copy (circular). Values must stay in lockstep.
STATUS_UNAVAILABLE = "unavailable"
STATUS_PRODUCTION = "production"
STATUS_DEVELOPMENT = "development"
STATUS_DIRTY = "dirty"
STATUS_MISMATCH = "source_mismatch"

# Markers in helper/index.html. Injection replaces the inner text once.
MARKERS = (
    "BEAMO_BUILD_LABEL",
    "BEAMO_VERSION",
    "BEAMO_BUILD_ID",
    "BEAMO_SOURCE_COMMIT",
    "BEAMO_BUILD_STATUS",
)

SOURCE_STUB = (
    "This copy is not a manufactured USB image. "
    "It is the source helper used while building one."
)
PREVIEW_STUB = "This launcher is a preview. It is not a manufactured USB image."
SESSION_STUB = "This session is not a manufactured USB image."
LAUNCHER_STUB = "This launcher is not from a manufactured USB image."
LABEL_PRODUCTION = "This USB is a manufactured Beamo Wipe image."
LABEL_DEVELOPMENT = "This USB is a development image, not a manufactured release."
LABEL_DIRTY = (
    "This USB was built from changed source. It is not a manufactured release."
)
LABEL_MISMATCH = "This launcher does not match the USB image identity."
NOT_PACKAGED = "not packaged"
STATUS_SOURCE = "not a manufactured image"

PLATFORMS = (
    "For 64-bit Intel/AMD Windows or Linux PCs that start from this USB. "
    "Not Apple Silicon Macs. Not Chromebooks."
)
PLATFORMS_HELPER = (
    PLATFORMS + " Some Intel Macs may show this USB; many will not."
)
SECURE_BOOT = (
    "This USB uses Debian's signed boot files. Whether your computer starts it "
    "depends on that computer's firmware trust settings and revocation updates. "
    "Beamo Wipe does not change Secure Boot and does not bypass a refusal."
)
SECURE_BOOT_HINT = (
    "This USB uses Debian's signed boot files. If it does not show up, you may "
    "need to allow USB start in that computer's settings. Beamo Wipe does not "
    "change Secure Boot."
)
OLDER_MEDIA = (
    "The pages on this USB describe this image. "
    "Older sticks may use different startup files."
)
THIS_IMAGE_ONLY = (
    "The lines below are this image's start and compatibility notes, "
    "not a history of other builds."
)

# Phrases that belong in operator history, not on this USB's customer pages.
HISTORY_DUMP = (
    "bf-001",
    "matrix v1",
    "this card describes the development image",
    "0.1.0-amd64",
    "this image is unsigned",
    "this image may be unsigned",
)

STATUS_DISPLAY = {
    STATUS_PRODUCTION: "production",
    STATUS_DEVELOPMENT: "development",
    STATUS_DIRTY: "dirty",
    STATUS_MISMATCH: "source mismatch",
    STATUS_UNAVAILABLE: "unavailable",
}

class LocalizedHelperIdentity(TypedDict):
    source_label: str
    source_status: str
    labels: dict[str, str]
    statuses: dict[str, str]


LOCALIZED_HELPER_IDENTITY: dict[str, LocalizedHelperIdentity] = {
    "fr": {
        "source_label": (
            "Cette copie n’est pas une image USB fabriquée. "
            "C’est l’aide source utilisée pour en créer une."
        ),
        "source_status": "pas une image fabriquée",
        "labels": {
            STATUS_PRODUCTION: "Cette clé USB est une image Beamo Wipe fabriquée.",
            STATUS_DEVELOPMENT: "Cette clé USB est une image de développement, pas une version de production.",
            STATUS_DIRTY: "Cette clé USB a été créée à partir d’un code source modifié. Ce n’est pas une version de production.",
            STATUS_MISMATCH: "Ce lanceur ne correspond pas à l’identité de l’image USB.",
            STATUS_UNAVAILABLE: "Cette session ne provient pas d’une image USB fabriquée.",
        },
        "statuses": {
            STATUS_PRODUCTION: "production",
            STATUS_DEVELOPMENT: "développement",
            STATUS_DIRTY: "modifié",
            STATUS_MISMATCH: "source différente",
            STATUS_UNAVAILABLE: "indisponible",
        },
    },
    "de": {
        "source_label": (
            "Diese Kopie ist kein hergestelltes USB-Abbild. "
            "Dies ist die Quellhilfe für die Erstellung eines solchen Abbilds."
        ),
        "source_status": "kein hergestelltes Abbild",
        "labels": {
            STATUS_PRODUCTION: "Dieser USB-Stick enthält ein hergestelltes Beamo Wipe-Abbild.",
            STATUS_DEVELOPMENT: "Dieser USB-Stick enthält ein Entwicklungsabbild, keine Produktionsversion.",
            STATUS_DIRTY: "Dieser USB-Stick wurde aus geändertem Quellcode erstellt. Er ist keine Produktionsversion.",
            STATUS_MISMATCH: "Dieser Starter passt nicht zur Identität des USB-Abbilds.",
            STATUS_UNAVAILABLE: "Diese Sitzung stammt nicht von einem hergestellten USB-Abbild.",
        },
        "statuses": {
            STATUS_PRODUCTION: "Produktion",
            STATUS_DEVELOPMENT: "Entwicklung",
            STATUS_DIRTY: "geändert",
            STATUS_MISMATCH: "Quellcode stimmt nicht überein",
            STATUS_UNAVAILABLE: "nicht verfügbar",
        },
    },
}


def customer_label(status: str, *, packaged: bool) -> str:
    if not packaged or status == STATUS_UNAVAILABLE:
        return SOURCE_STUB if not packaged else SESSION_STUB
    if status == STATUS_PRODUCTION:
        return LABEL_PRODUCTION
    if status == STATUS_DEVELOPMENT:
        return LABEL_DEVELOPMENT
    if status == STATUS_DIRTY:
        return LABEL_DIRTY
    if status == STATUS_MISMATCH:
        return LABEL_MISMATCH
    return SESSION_STUB


def packaged_sentence_from_runtime(build: Mapping[str, Any] | None = None) -> str:
    from beamo_wipe.build_identity import load_build

    record = dict(build) if build is not None else load_build()
    status = str(record.get("status") or STATUS_UNAVAILABLE)
    packaged = bool(record.get("build_id"))
    if not packaged:
        return SESSION_STUB
    return customer_label(status, packaged=True)


def sentence_from_application(app: Mapping[str, Any] | None) -> str:
    if not isinstance(app, dict):
        return SESSION_STUB
    injected = app.get("build")
    status = str(app.get("build_status") or STATUS_UNAVAILABLE)
    return customer_label(status, packaged=isinstance(injected, dict) and bool(injected))


def version_report(*, version: str = __version__, build: Mapping[str, Any] | None = None) -> str:
    from beamo_wipe.build_identity import BUILD_ID_RE, COMMIT_RE, load_build

    record = dict(build) if build is not None else load_build()
    status = str(record.get("status") or STATUS_UNAVAILABLE)
    packaged = bool(record.get("build_id"))
    build_id = str(record.get("build_id") or "")
    commit = str(record.get("source_commit") or "")
    if not packaged:
        label = SESSION_STUB
        build_id = build_id or NOT_PACKAGED
        commit = commit or NOT_PACKAGED
        status_text = STATUS_SOURCE
    else:
        label = customer_label(status, packaged=True)
        status_text = STATUS_DISPLAY.get(status, "unavailable")
        if not BUILD_ID_RE.fullmatch(build_id):
            build_id = "unavailable"
        if not COMMIT_RE.fullmatch(commit):
            commit = "unavailable"
    return (
        f"Beamo Wipe {version}\n"
        f"{label}\n"
        f"Release build: {build_id}\n"
        f"Source: {commit}\n"
        f"Build status: {status_text}\n"
    )


def _replace_once(html_text: str, name: str, value: str) -> str:
    start = f"<!--{name}-->"
    end = f"<!--/{name}-->"
    if html_text.count(start) != 1 or html_text.count(end) != 1:
        raise RuntimeError(f"helper identity marker {name} missing or duplicated")
    before, rest = html_text.split(start, 1)
    inner, after = rest.split(end, 1)
    if start in inner or end in inner:
        raise RuntimeError(f"helper identity marker {name} nested")
    return before + start + html.escape(value, quote=False) + end + after


def inject_helper_html(
    html_text: str,
    *,
    version: str,
    injected: Mapping[str, Any] | None,
    packaged: bool,
    language: str = "en",
) -> str:
    """Fill helper identity markers. Story paragraphs stay in the source HTML."""
    from beamo_wipe.build_identity import BUILD_ID_RE, COMMIT_RE, classify_status

    if language not in ("en", *LOCALIZED_HELPER_IDENTITY):
        raise RuntimeError("unsupported helper language")
    localized = LOCALIZED_HELPER_IDENTITY.get(language)
    if packaged and injected is None:
        raise RuntimeError("manufactured helper requires injected identity")
    if not packaged:
        label = localized["source_label"] if localized else SOURCE_STUB
        build_id = NOT_PACKAGED
        commit = NOT_PACKAGED
        status_text = localized["source_status"] if localized else STATUS_SOURCE
    else:
        payload = dict(injected or {})
        status = classify_status(
            build_id=str(payload.get("build_id") or ""),
            source_dirty=bool(payload.get("source_dirty")),
            source_sha256=str(payload.get("source_sha256") or ""),
            runtime_sha256=str(payload.get("source_sha256") or "") or None,
        )
        label = (
            localized["labels"].get(status, localized["labels"][STATUS_UNAVAILABLE])
            if localized
            else customer_label(status, packaged=True)
        )
        build_id = str(payload.get("build_id") or "")
        commit = str(payload.get("source_commit") or "")
        if not BUILD_ID_RE.fullmatch(build_id):
            raise RuntimeError("invalid build identity")
        if not COMMIT_RE.fullmatch(commit):
            raise RuntimeError("invalid build identity")
        status_text = (
            localized["statuses"].get(status, localized["statuses"][STATUS_UNAVAILABLE])
            if localized
            else STATUS_DISPLAY.get(status, "unavailable")
        )
    out = html_text
    for name, value in (
        ("BEAMO_BUILD_LABEL", label),
        ("BEAMO_VERSION", version),
        ("BEAMO_BUILD_ID", build_id),
        ("BEAMO_SOURCE_COMMIT", commit),
        ("BEAMO_BUILD_STATUS", status_text),
    ):
        out = _replace_once(out, name, value)
    return out


def required_story_phrases() -> tuple[str, ...]:
    return (PLATFORMS, SECURE_BOOT, OLDER_MEDIA, THIS_IMAGE_ONLY)
