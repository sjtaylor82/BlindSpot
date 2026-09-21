"""Localisation: gettext catalogues with English as the built-in fallback.

English source strings are the message ids. A language is a compiled
``locale/<code>/LC_MESSAGES/blindspot.mo`` file; any string without a
translation is shown in English, so partial translations are safe.

Four helpers mark and look up text:

* ``tr(text)`` translates at call time.
* ``ntr(singular, plural, count)`` chooses the right plural form.
* ``ptr(context, text)`` disambiguates identical English text.
* ``tr_noop(text)`` marks text in a module-level table for extraction only;
  translate it with ``tr`` when it is displayed.
"""

from __future__ import annotations

import gettext
import locale
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from .portable import resource_directory

DOMAIN = "blindspot"
DEFAULT_LANGUAGE = "en"
SYSTEM_LANGUAGE = "system"
# What an installation uses until the user chooses a language: follow the
# operating system, falling back to English when no translation exists.
DEFAULT_LANGUAGE_SETTING = SYSTEM_LANGUAGE

_translations: gettext.NullTranslations = gettext.NullTranslations()
_language = DEFAULT_LANGUAGE
_locale_directory: Path | None = None
_refresh_hooks: list[Callable[[], None]] = []


def locale_directory() -> Path:
    if _locale_directory is not None:
        return _locale_directory
    return resource_directory() / "locale"


def tr(text: str) -> str:
    if not text:
        return text
    return _translations.gettext(text)


def ntr(singular: str, plural: str, count: int) -> str:
    return _translations.ngettext(singular, plural, count)


def ptr(context: str, text: str) -> str:
    return _translations.pgettext(context, text)


def tr_noop(text: str) -> str:
    return text


def normalise_language(code: str | None) -> str:
    """Reduce ``pl_PL``, ``pl-PL`` or ``pl_PL.UTF-8`` to ``pl``."""
    if not code:
        return DEFAULT_LANGUAGE
    base = code.replace("-", "_").split(".", 1)[0].split("@", 1)[0]
    return base.split("_", 1)[0].lower() or DEFAULT_LANGUAGE


def _catalogue_path(code: str) -> Path:
    return locale_directory() / code / "LC_MESSAGES" / f"{DOMAIN}.mo"


def _read_catalogue(path: Path) -> gettext.GNUTranslations | None:
    try:
        with path.open("rb") as handle:
            return gettext.GNUTranslations(handle)
    except (OSError, ValueError, UnicodeDecodeError):
        return None


def available_languages() -> list[tuple[str, str]]:
    """Return ``(code, native name)`` pairs, English first."""
    languages = [(DEFAULT_LANGUAGE, "English")]
    directory = locale_directory()
    try:
        entries = sorted(directory.iterdir())
    except OSError:
        return languages
    for entry in entries:
        code = entry.name
        if code == DEFAULT_LANGUAGE or not entry.is_dir():
            continue
        catalogue = _read_catalogue(_catalogue_path(code))
        if catalogue is None:
            continue
        # Literal arguments so the extractor lists this entry for translators.
        name = catalogue.pgettext(
            "The name of this language, written in that language", "English"
        )
        languages.append((code, code if name == "English" else name))
    return languages


def detect_system_language() -> str:
    """Best guess at the operating system's display language."""
    if sys.platform == "win32":
        try:
            import ctypes

            buffer = ctypes.create_unicode_buffer(85)
            if ctypes.windll.kernel32.GetUserDefaultLocaleName(buffer, 85):
                return normalise_language(buffer.value)
        except (AttributeError, OSError):
            pass
    elif sys.platform == "darwin":
        try:
            result = subprocess.run(
                ["defaults", "read", "-g", "AppleLanguages"],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
            for line in result.stdout.splitlines():
                cleaned = line.strip().strip('(),"')
                if cleaned:
                    return normalise_language(cleaned)
        except (OSError, subprocess.SubprocessError):
            pass
    for variable in ("LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(variable)
        if value and value != "C":
            return normalise_language(value)
    try:
        return normalise_language(locale.getlocale()[0])
    except (ValueError, TypeError):
        return DEFAULT_LANGUAGE


def set_language(code: str | None = SYSTEM_LANGUAGE) -> str:
    """Activate a language and return the code actually in use.

    Unknown or unreadable languages fall back to English.
    """
    global _translations, _language
    resolved = (
        detect_system_language()
        if not code or code == SYSTEM_LANGUAGE
        else normalise_language(code)
    )
    catalogue = None
    if resolved != DEFAULT_LANGUAGE:
        catalogue = _read_catalogue(_catalogue_path(resolved))
    if catalogue is None:
        _translations = gettext.NullTranslations()
        _language = DEFAULT_LANGUAGE
    else:
        _translations = catalogue
        _language = resolved
    for hook in list(_refresh_hooks):
        hook()
    return _language


def current_language() -> str:
    return _language


def on_language_change(hook: Callable[[], None]) -> None:
    """Register a callback run after every ``set_language``."""
    if hook not in _refresh_hooks:
        _refresh_hooks.append(hook)


def use_locale_directory(directory: Path | None) -> None:
    """Point the loader at another catalogue folder (used by tests)."""
    global _locale_directory
    _locale_directory = directory
