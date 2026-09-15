"""
Tests core/i18n.py's translation loading, fallback, and formatting - and a
consistency check across all real translations/*.json files (every
language must define exactly the same keys with exactly the same
str.format() placeholders as English, or a translated page could render a
key name outright or crash with a KeyError while formatting).
"""

import json
import re

import pytest

from core.i18n import SUPPORTED_LANGUAGES, TRANSLATIONS_DIR, translate


def test_translate_returns_english_for_known_key():
    assert translate("common.save", "en") == "Save"


def test_translate_falls_back_to_english_for_missing_key_in_other_language():
    # A key that doesn't exist in any file falls back to itself, proving
    # the fallback chain terminates rather than raising or returning None.
    assert translate("this.key.does.not.exist", "es") == "this.key.does.not.exist"


def test_translate_falls_back_to_english_for_unknown_language():
    # No translations/xx.json file at all - must not raise.
    assert translate("common.save", "xx") == "Save"


def test_translate_applies_format_kwargs():
    result = translate("flash.removed", "en", name="Wikipedia")
    assert result == "Removed 'Wikipedia'."


def test_translate_missing_format_kwarg_does_not_raise():
    # If a caller forgets a placeholder, the raw (unformatted) string comes
    # back rather than the whole page erroring out.
    result = translate("flash.removed", "en")
    assert "{name}" in result


@pytest.mark.parametrize("lang", sorted(SUPPORTED_LANGUAGES.keys()))
def test_every_supported_language_has_a_real_translation_file(lang):
    path = TRANSLATIONS_DIR + f"/{lang}.json"
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    assert len(data) > 0


def test_all_languages_define_exactly_the_same_keys():
    all_data = {}
    for lang in SUPPORTED_LANGUAGES:
        with open(f"{TRANSLATIONS_DIR}/{lang}.json", encoding="utf-8") as f:
            all_data[lang] = json.load(f)

    en_keys = set(all_data["en"].keys())
    for lang, data in all_data.items():
        if lang == "en":
            continue
        assert set(data.keys()) == en_keys, (
            f"{lang}.json key set differs from en.json: "
            f"missing={en_keys - data.keys()} extra={data.keys() - en_keys}"
        )


def test_all_languages_have_matching_format_placeholders():
    """A translator dropping a {placeholder} (or a stray typo introducing
    one) would either silently lose data or raise when .format() runs -
    catch it here instead of live, in whichever language triggers it."""
    def placeholders(s):
        return set(re.findall(r"\{(\w+)\}", s))

    all_data = {}
    for lang in SUPPORTED_LANGUAGES:
        with open(f"{TRANSLATIONS_DIR}/{lang}.json", encoding="utf-8") as f:
            all_data[lang] = json.load(f)

    for key, en_value in all_data["en"].items():
        en_ph = placeholders(en_value)
        for lang, data in all_data.items():
            if lang == "en":
                continue
            other_ph = placeholders(data[key])
            assert other_ph == en_ph, (
                f"{key} ({lang}): placeholders {other_ph} != english {en_ph}"
            )
