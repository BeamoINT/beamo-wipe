# SPDX-License-Identifier: GPL-3.0-or-later
"""UI language selection. English is the source; French and German tables
in locales/ override module attributes. Tables hold data only (never
functions); builders format translated templates, and modules with derived
text rebuild it in _apply_language().
"""

from __future__ import annotations

import importlib

LANGUAGE_ORDER = ("en", "fr", "de")

# Own-language names. Never translated, never in the tables.
LANGUAGE_NAMES = {"en": "English", "fr": "Français", "de": "Deutsch"}

# Translated modules in dependency order: a module's _apply_language() may
# read another module's already-translated attributes (copy reads outcomes,
# methods, inventory, storage_limits), so leaves come first and copy last.
TRANSLATED_MODULES = (
    "methods",
    "outcomes",
    "inventory",
    "storage_limits",
    "identity",
    "keyboard",
    "power",
    "progress",
    "engine_checks",
    "result_summary",
    "privacy",
    "diagnostic_report",
    "session_recovery",
    "safety",
    "discover",
    "models",
    "sound",
    "app",
    "wizard",
    "support_export",
    "copy",
    "recovery",
)

_current = "en"
_SNAPSHOT = None


def _modules():
    return {
        name: importlib.import_module(f"beamo_wipe.{name}")
        for name in TRANSLATED_MODULES
    }


def _tables(code: str):
    if code == "en":
        return {}
    module = importlib.import_module(f"beamo_wipe.locales.{code}")
    return module.STRINGS


def _snapshot():
    """English values for every translated name. Fails fast on typos."""
    global _SNAPSHOT
    if _SNAPSHOT is None:
        modules = _modules()
        snap = {}
        for module_name, table in _tables("fr").items():
            module = modules[module_name]
            snap[module_name] = {name: getattr(module, name) for name in table}
        _SNAPSHOT = snap
    return _SNAPSHOT


def current() -> str:
    return _current


def is_supported(code: object) -> bool:
    return isinstance(code, str) and code in LANGUAGE_ORDER


def surface():
    """{module: {name: english value}} for the translated surface."""
    return {module: dict(names) for module, names in _snapshot().items()}


def keys(code: str, module: str):
    if code == "en":
        return list(_snapshot()[module])
    return list(_tables(code)[module])


def english(module: str, name: str):
    return _snapshot()[module][name]


def translated(code: str, module: str, name: str):
    return _tables(code)[module][name]


def _apply_hook(module) -> None:
    hook = getattr(module, "_apply_language", None)
    if callable(hook):
        hook()


def set_language(code: str) -> str:
    """Apply a language to every translated module. Restores English exactly."""
    if not is_supported(code):
        raise ValueError(f"unsupported language: {code!r}")
    global _current
    modules = _modules()
    if code == "en":
        for module_name in TRANSLATED_MODULES:
            names = _snapshot().get(module_name, {})
            for name, value in names.items():
                setattr(modules[module_name], name, value)
            _apply_hook(modules[module_name])
    else:
        tables = _tables(code)
        for module_name in TRANSLATED_MODULES:
            for name, value in tables[module_name].items():
                setattr(modules[module_name], name, value)
            _apply_hook(modules[module_name])
    _current = code
    return code
