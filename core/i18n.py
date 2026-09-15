"""
i18n: lightweight JSON-file translation system for the admin UI and
student portal chrome. Deliberately NOT catalogue/module content (a ZIM's
articles, a module's own name/description) - those stay in whatever
language they were published in, same as a real encyclopedia would; this
only covers the app's own labels, buttons, and messages.

Deliberately not Flask-Babel: that needs a .po/.mo compile step and a
heavier dependency for what's currently a few hundred short strings. Plain
JSON files under translations/<lang>.json, keyed by a stable dotted id
("nav.modules"), are enough - loaded once and cached (they only change via
a code edit + restart, never at runtime) and always fall back to English
so a partially-translated language never renders a blank string instead of
just showing English for that one missing key.
"""

import json
import logging
import os
import sys

logger = logging.getLogger(__name__)

# Same frozen-vs-source path resolution as core/version.py, so this works
# identically from `python main.py` and from the compiled OfflineHub.exe.
if getattr(sys, "frozen", False):
    _APP_ROOT = os.path.dirname(sys.executable)
else:
    _APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TRANSLATIONS_DIR = os.path.join(_APP_ROOT, "translations")

# Displayed in the Settings language picker - the value is the language's
# own name written in itself ("Deutsch" not "German"), the usual convention
# so someone who can't read the current language can still find their own.
SUPPORTED_LANGUAGES: dict[str, str] = {
    "en": "English",
    "es": "Español",
    "fr": "Français",
    "de": "Deutsch",
}

DEFAULT_LANGUAGE = "en"

_cache: dict[str, dict[str, str]] = {}


def _load(lang: str) -> dict[str, str]:
    if lang in _cache:
        return _cache[lang]
    path = os.path.join(TRANSLATIONS_DIR, f"{lang}.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        logger.warning("Could not load translations/%s.json - falling back to English for it.", lang)
        data = {}
    _cache[lang] = data
    return data


def translate(key: str, lang: str = DEFAULT_LANGUAGE, **kwargs) -> str:
    """
    Looks up `key` in `lang`'s translation file, falling back to English,
    then to the key itself (so a missing translation is visibly wrong -
    "settings.title" showing up on screen - rather than silently blank).
    `**kwargs` are applied via str.format for the handful of strings that
    take a value (e.g. "{count} people ahead of you").
    """
    en = _load(DEFAULT_LANGUAGE)
    strings = _load(lang) if lang != DEFAULT_LANGUAGE else en
    text = strings.get(key) or en.get(key) or key
    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, IndexError):
            pass
    return text
